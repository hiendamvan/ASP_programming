import argparse
import json
import random
import time
from pathlib import Path

from llm import llm_chat


# ============================================================
# LAW DB (points / clauses) — ngữ cảnh truy xuất cho LLM
# ============================================================

def load_law_index():
    """Load points.json + clauses.json và index theo id."""
    base = Path(__file__).resolve().parent / "law_db"

    points = load_plain(base / "points.json")
    clauses = load_plain(base / "clauses.json")

    point_by_id = {p["point_id"]: p for p in points}
    clause_by_id = {c["clause_id"]: c for c in clauses}

    return point_by_id, clause_by_id


def load_plain(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

_RUNTIME_ENV = None


def load_runtime_env(seed=None):
    """Load point_by_id/clause_by_id (từ law_db) + rng, cache lại
    để generate_dataset() không phải đọc lại points.json/clauses.json
    ở mỗi item trong vòng lặp."""
    global _RUNTIME_ENV
    if _RUNTIME_ENV is None:
        point_by_id, clause_by_id = load_law_index()
        rng = random.Random(seed) if seed is not None else random.Random()
        _RUNTIME_ENV = (point_by_id, clause_by_id, rng)
    return _RUNTIME_ENV

def normalize_point_id(article_id, clause_id, point_label):
    """Build point_id đầy đủ dạng '{article}.{clause}.{label}'.
    multihop lưu clause_id chỉ là số (vd '1'), cần prepend article_id."""
    aid = str(article_id)
    cid = str(clause_id)
    if not cid.startswith(aid + "."):
        cid = f"{aid}.{cid}"
    return f"{cid}.{point_label}"


def collect_source_points(item):
    """Trích danh sách (article_id, clause_id, point_label)
    từ các format source khác nhau của 4 loại câu hỏi."""
    out = []

    src = item.get("source")
    if isinstance(src, dict):
        # simple / insufficient: source = {point_id, clause_id, article_id}
        # exception: source = {article_id, clause_id, point_id(label), content}
        pid = src.get("point_id")
        if pid and "." in pid:
            # point_id đầy đủ dạng '10.1.a' → tách clause_id, label
            *parts, label = pid.split(".")
            clause_id = ".".join(parts)
            out.append((src.get("article_id") or parts[0], clause_id, label))
        elif src.get("point_id"):
            # point_id chỉ là label, vd 'a'
            out.append((src["article_id"], src["clause_id"], src["point_id"]))
        else:
            out.append((src["article_id"], src["clause_id"], src["label"]))

    for s in item.get("sources", []) or []:
        # multihop: sources = [{article_id, clause_id, point_id}, ...]
        out.append((s["article_id"], s["clause_id"], s["point_id"]))

    return out


def resolve_points(item, point_by_id, clause_by_id, rng, num_noise=2):
    """Trả về (main_points, noise_points).
    main_points: [dict] các point thực sự của câu hỏi.
    noise_points: [dict] num_noise point khác cùng article với main point đầu tiên.
    Mỗi dict: {point_id, label, content, clause_id, intro}"""
    refs = collect_source_points(item)
    if not refs:
        return [], []

    main = []
    for article_id, clause_id, label in refs:
        pid = normalize_point_id(article_id, clause_id, label)
        p = point_by_id.get(pid)
        if p:
            cl = clause_by_id.get(p["clause_id"])
            main.append({
                "point_id": p["point_id"],
                "label": p["label"],
                "content": p["content"],
                "clause_id": p["clause_id"],
                "intro": cl["intro"] if cl else "",
            })

    if not main:
        return [], []

    # candidates nhiễu: cùng article, khác point chính
    target_article = main[0]["point_id"].split(".")[0]
    main_ids = {m["point_id"] for m in main}

    candidates = [
        pid for pid, p in point_by_id.items()
        if pid.split(".")[0] == target_article and pid not in main_ids
    ]
    rng.shuffle(candidates)

    noise = []
    for pid in candidates[:num_noise]:
        p = point_by_id[pid]
        cl = clause_by_id.get(p["clause_id"])
        noise.append({
            "point_id": p["point_id"],
            "label": p["label"],
            "content": p["content"],
            "clause_id": p["clause_id"],
            "intro": cl["intro"] if cl else "",
        })

    return main, noise


def format_points(points):
    lines = []
    for i, p in enumerate(points, 1):
        header = f"[{i}] {p['point_id']}"
        if p["intro"]:
            header += f" — {p['intro']}"
        lines.append(header)
        lines.append(f"    Nội dung: {p['content']}")
    return "\n".join(lines)


# ============================================================
# CONFIG
# ============================================================

SLEEP_SECONDS = 10


# ============================================================
# LOAD / SAVE JSON
# ============================================================

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_file = path.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    temp_file.replace(path)


# ============================================================
# SYSTEM PROMPT
# ============================================================
#
# Đây là prompt cho "model đang được đánh giá" (candidate).
# KHÔNG được lộ rubric / đáp án chuẩn / gợi ý về source ra đây,
# vì mục tiêu là sinh ra câu trả lời "mù" giống như user thật hỏi,
# để các phương pháp judge khác nhau chấm lại và so sánh với nhau.

SYSTEM_PROMPT = """
Bạn là một trợ lý AI tư vấn pháp luật giao thông đường bộ Việt Nam.
 
Nhiệm vụ:
Trả lời câu hỏi của người dùng về xử phạt vi phạm giao thông,
dựa trên Nghị định 168/2024/NĐ-CP quy định xử phạt vi phạm hành
chính về trật tự, an toàn giao thông đường bộ và trừ điểm, phục
hồi điểm giấy phép lái xe.
 
Yêu cầu khi trả lời:
 
1. Xác định đúng hành vi vi phạm được mô tả trong tình huống.
2. Liệt kê ĐẦY ĐỦ tất cả các hình thức xử phạt áp dụng cho hành vi
   đó, không được bỏ sót bất kỳ hình thức nào, bao gồm:
   - phạt tiền (mức tối thiểu - tối đa);
   - trừ điểm giấy phép lái xe (nếu có);
   - hình thức xử phạt bổ sung (tước quyền sử dụng giấy phép lái xe,
     tịch thu phương tiện/tang vật...) nếu có;
   - biện pháp khắc phục hậu quả (nếu có).
3. Nếu tình huống thuộc trường hợp loại trừ / ngoại lệ (không bị
   xử phạt), nêu rõ điều đó và lý do, không cần liệt kê hình phạt.
4. Nếu câu hỏi không đủ thông tin để xác định chính xác hành vi vi
   phạm hoặc mức xử phạt, nêu ngắn gọn thông tin còn thiếu và các
   khả năng có thể xảy ra tương ứng, không suy đoán hay bịa đặt.
5. Nếu tình huống liên quan đến nhiều hành vi/quy định, xử lý lần
   lượt từng hành vi rồi liệt kê đầy đủ hình phạt cho từng hành vi.
 
Yêu cầu về hình thức trả lời:
 
- Trả lời NGẮN GỌN, đi thẳng vào kết luận và hình phạt, không tư
  vấn dài dòng, không diễn giải lại tình huống, không thêm lời
  khuyên/cảnh báo/lời chào hỏi, không tự giới thiệu là AI.
- Không thêm định dạng JSON, không thêm Markdown, không trích dẫn
  nguồn nếu không chắc chắn.
"""


def build_user_prompt(item, main_points, noise_points):
    prompt = item["question"].strip()

    # Cung cấp ngữ cảnh truy xuất cho LLM: point chính + 2 point nhiễu cùng article.
    # Lưu ý: các point này là "nguồn tra cứu" được cung cấp, KHÔNG rõ ràng đâu là
    # đúng/sai. Model phải tự phân biệt khi trả lời.
    if main_points:
        prompt += "\n\n----- NỘI DUNG QUY ĐỊNH TRA CỨU -----"
        prompt += "\nCác quy định dưới đây là trích dẫn từ văn bản pháp luật. "
        prompt += "Hãy đọc kỹ và dùng những quy định PHÙ HỢP với tình huống để trả lời. "
        prompt += "Có một số quy định không liên quan đến tình huống, đừng nhầm lẫn."
        prompt += "\n\n[Quy định liên quan]"
        prompt += "\n" + format_points(main_points)
        if noise_points:
            prompt += "\n\n[Quy định khác cùng văn bản (tham khảo)]"
            prompt += "\n" + format_points(noise_points)

    return prompt.strip()


def generate_answer(item, provider=None, point_by_id=None, clause_by_id=None,
                    rng=None, num_noise=2):
    if point_by_id is None or clause_by_id is None or rng is None:
        point_by_id, clause_by_id, rng = load_runtime_env()

    main_points, noise_points = resolve_points(
        item, point_by_id, clause_by_id, rng, num_noise=num_noise
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(item, main_points, noise_points)},
    ]

    kwargs = {}
    if provider:
        kwargs["provider"] = provider

    result = llm_chat(messages, **kwargs)

    answer = result["content"].strip()

    return answer, result.get("provider")


def generate_dataset(input_file, output_file=None, start_index=1,
                      end_index=None, provider=None, force=False,
                      num_noise=2, seed=42):
    point_by_id, clause_by_id, rng = load_runtime_env(seed=seed)

    input_path = Path(input_file)
    dataset = load_json(input_path)

    output_path = Path(output_file) if output_file else input_path

    total = len(dataset)
    start = max(0, start_index - 1)
    end = total if end_index is None else min(total, end_index)

    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Total samples in file: {total}")
    print(f"Range: {start_index} - {end if end_index else total}")
    print(f"Noise points per item: {num_noise} (seed={seed})")

    generated_count = 0

    for i in range(start, end):
        item = dataset[i]

        if "question" not in item:
            print(f"[SKIP] No 'question' field at index {i}")
            continue

        if not force and item.get("model_answer"):
            print(f"[SKIP] Already has model_answer at index {i}")
            continue

        print("\n" + "=" * 70)
        print(f"[Item {i + 1}/{total}] type={item.get('question_type', 'unknown')}")
        print(f"Question: {item['question'][:100]}...")

        try:
            main_points, _ = resolve_points(
                item, point_by_id, clause_by_id, random.Random(0), num_noise=0
            )
            if not main_points:
                print("[WARN] No law point resolved -> answering without context")

            answer, provider_used = generate_answer(
                item, provider=provider,
                point_by_id=point_by_id, clause_by_id=clause_by_id,
                rng=rng, num_noise=num_noise,
            )

            item["model_answer"] = answer
            item["answer_provider"] = provider_used

            save_json(dataset, output_path)
            generated_count += 1

            print(f"Provider: {provider_used}")
            print(f"Answer: {answer[:200]}...")

        except Exception as e:
            print(f"[ERROR] {type(e).__name__}: {e}")

        if i < end - 1:
            print(f"Sleeping {SLEEP_SECONDS}s...")
            time.sleep(SLEEP_SECONDS)

    print("\n" + "=" * 70)
    print(f"DONE. Generated {generated_count} new answers this run")
    print(f"Total samples in file: {total}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Generate candidate LLM answers directly into each sample of "
            "a benchmark question file (simple / multihop / insufficient / "
            "exception), so different judge methods can be compared later."
        )
    )
    parser.add_argument(
        "input_file", type=str,
        help="Path to question JSON file, e.g. simple_1_100.json, "
             "exception_questions.json, multihop_questions.json, "
             "insufficient_questions.json. Each item must have a "
             "'question' field.",
    )
    parser.add_argument(
        "--start", type=int, default=1,
        help="Start index (1-based, inclusive). Default: 1",
    )
    parser.add_argument(
        "--end", type=int, default=None,
        help="End index (1-based, inclusive). Default: all",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output file path. Default: overwrite the input file in place.",
    )
    parser.add_argument(
        "--provider", type=str, default=None,
        help="Force a specific LLM provider/model, if llm_chat() supports a 'provider' kwarg",
    )
    parser.add_argument(
        "--num-noise", type=int, default=2,
        help="Number of distractor points from the same article. Default: 2",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for picking distractor points (reproducible). Default: 42",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Regenerate answers even for samples that already have model_answer",
    )
    args = parser.parse_args()

    generate_dataset(
        args.input_file, args.output, args.start, args.end,
        args.provider, args.force, args.num_noise, args.seed,
    )