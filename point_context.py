# -*- coding: utf-8 -*-
"""
[ĐÃ ĐƯỢC THAY THẾ — giữ lại để tham khảo]

Chức năng của module này nay nằm trong generate_answer.py
(resolve_points / format_points / build_user_prompt). Bản trong
generate_answer.py đầy đủ hơn vì có ghép thêm `intro` của khoản
(chứa mức phạt tiền), còn module này chỉ đọc points.json.
Đừng dùng cả hai song song để tránh lệch ngữ cảnh giữa các lần sinh.

Helper: resolve nội dung điểm (point) từ law_db/points.json và chọn điểm nhiễu (decoy).

Dùng để nâng cấp pipeline sinh câu trả lời: đưa point đúng (ground-truth) vào
context của model để model trả lời chính xác hơn, đồng thời chèn 2 point decoy
cùng article để kiểm tra model có nhận diện đúng point hay bị lẫn.

Hỗ trợ 4 loại câu hỏi qua cấu trúc source / sources:
  - simple / insufficient : item["source"]["point_id"]        (vd "10.1.a")
  - exception             : item["source"]["point_id"]        (content có sẵn trong source)
  - multihop              : item["sources"] list, nối thành "{article}.{clause}.{point}"
"""
import json
import random
from pathlib import Path

DEFAULT_PRIMARY_DECOYS = 2
DEFAULT_SEED = 42
POINTS_DB_PATH = Path("law_db") / "points.json"


# ============================================================
# Nạp dữ liệu points.json
# ============================================================

def load_points_db(path=None):
    """Trả về (content_map, article_of, all_ids).

    content_map: {point_id: content}
    article_of : {point_id: article_id (str, phần trước dấu chấm đầu)}
    all_ids    : danh sách point_id
    """
    path = Path(path) if path else POINTS_DB_PATH

    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    content_map = {}
    article_of = {}
    for row in rows:
        pid = row["point_id"]
        content_map[pid] = row.get("content", "")
        article_of[pid] = pid.split(".")[0]

    return content_map, article_of, list(content_map.keys())


# ============================================================
# Tìm point thật (ground-truth) từ item
# ============================================================

def extract_true_point_ids(item):
    """Lấy danh sách point_id thật của một sample (đã chuẩn hoá đầy đủ).

    Trả về list[str] point_id dạng "a.b.c". Trả [] nếu không tìm thấy.
    """
    qtype = item.get("question_type")

    if qtype == "multihop":
        sources = item.get("sources", [])
        ids = []
        for src in sources:
            if not isinstance(src, dict):
                continue
            article = src.get("article_id")
            clause = src.get("clause_id")
            point = src.get("point_id")
            if article is None or clause is None or point is None:
                continue
            ids.append(f"{article}.{clause}.{point}")
        return ids

    # simple / exception / insufficient: source.point_id
    src = item.get("source")
    if isinstance(src, dict):
        pid = src.get("point_id")
        if pid:
            return [pid]

    return []


# ============================================================
# Chọn decoy
# ============================================================

def _settle_article(pid, article_of):
    """article của point; nếu point không có trong map, bóc phần trước dấu chấm đầu."""
    if pid in article_of:
        return article_of[pid]
    return pid.split(".")[0]


def pick_decoys(true_ids, content_map, article_of, target=DEFAULT_PRIMARY_DECOYS,
                seed=DEFAULT_SEED):
    """Chọn `target` decoy.

    Ưu tiên decoy CÙNG ARTICLE với từng point thật (khác point_id và không trùng
    lẫn nhau). Nếu không đủ, bổ sung từ toàn bộ db (khác point thật và decoy cũ).

    Trả về list[str] point_id decoy. Có tính tái lập theo `seed`.
    """
    rng = random.Random(seed)

    candidates = []
    seen = set(true_ids)
    for tid in true_ids:
        art = _settle_article(tid, article_of)
        for pid in content_map:
            if pid in seen:
                continue
            if _settle_article(pid, article_of) == art:
                seen.add(pid)
                candidates.append(pid)

    rng.shuffle(candidates)
    decoys = candidates[:target]

    if len(decoys) < target:
        rest = [pid for pid in content_map if pid not in seen and pid not in decoys]
        rng.shuffle(rest)
        for pid in rest:
            if len(decoys) >= target:
                break
            decoys.append(pid)

    return decoys


# ============================================================
# Build context block cho prompt
# ============================================================

def build_reference_block(true_ids, decoy_ids, content_map):
    """Tạo chuỗi 'DANH SÁCH ĐIỂM XỬ PHẠT THAM KHẢO' trộn point thật + decoy.

    Trộn (shuffle) thứ tự để không tiết lộ cái nào là đúng. Không có mức phạt.
    """
    order = true_ids + decoy_ids
    rng = random.Random()
    rng.shuffle(order)

    lines = [
        "DANH SÁCH ĐIỂM XỬ PHẠT THAM KHẢO (chỉ gồm hành vi; có cả điểm đúng "
        "và điểm gây nhiễu; bạn phải tự chọn điểm áp dụng cho tình huống):"
    ]
    for pid in order:
        content = content_map.get(pid, "")
        lines.append(f"- {pid}: {content}")

    return "\n".join(lines), order


# ============================================================
# Một hàm gói gọn để generate_answer.py dùng
# ============================================================

def build_answer_context(item, content_map, article_of, seed=DEFAULT_SEED,
                         target=DEFAULT_PRIMARY_DECOYS):
    """Trả về dict JSON lưu vào item["answer_context"] và (block_text, shuffled_ids).

    Nếu không resolve được point thật, trả về None (không thêm context).
    """
    true_ids = extract_true_point_ids(item)
    if not true_ids:
        return None, None

    # Đảm bảo mọi point thật tồn tại trong db; nếu miss thì vẫn giữ id (nội dung rỗng)
    decoy_ids = pick_decoys(true_ids, content_map, article_of, target=target, seed=seed)

    block_text, shuffled = build_reference_block(true_ids, decoy_ids, content_map)

    context = {
        "seed": seed,
        "true_points": true_ids,
        "decoy_points": decoy_ids,
        "referenced_points": shuffled,
    }
    return context, block_text


if __name__ == "__main__":
    # Smoke test nhanh
    content_map, article_of, all_ids = load_points_db()
    print(f"Loaded {len(content_map)} points")

    sample = {"question_type": "simple", "source": {"point_id": "10.1.a"}}
    ctx, block = build_answer_context(sample, content_map, article_of)
    print("true:", ctx["true_points"], "decoy:", ctx["decoy_points"])
    print(block)