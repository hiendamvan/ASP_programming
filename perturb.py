# -*- coding: utf-8 -*-
"""
Giai đoạn 2 — sinh câu trả lời có NHÃN BIẾT TRƯỚC bằng cách tiêm lỗi có kiểm soát.

Vì dataset không có nhãn vàng do người gán, ta dựng câu trả lời thẳng từ rubric
(không gọi LLM) rồi cố tình làm hỏng theo những kiểu lỗi cụ thể. Nhờ vậy biết
chắc từng mẫu là đúng hay sai, và đo được recall phát hiện lỗi của mỗi judge
TÁCH THEO TỪNG LOẠI LỖI — đây là bảng kết quả chính của luận văn.

Hai loại đặc biệt quan trọng:
  - verbose_correct  : đúng nhưng dài dòng  -> bẫy thiên vị ĐỘ DÀI
  - confident_wrong  : sai nhưng rất tự tin -> bẫy thiên vị VĂN PHONG
ASP judge miễn nhiễm với cả hai theo thiết kế; LLM judge thì không.
"""
import argparse
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_GENERATE = ROOT / "output_generate"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def money(v):
    return f"{v:,.0f}".replace(",", ".") + " đồng"


# ============================================================
# Các mảnh câu dùng chung
# ============================================================

FILLER = (
    "Bạn nên chấp hành nghiêm chỉnh quy định của pháp luật về trật tự, an toàn "
    "giao thông đường bộ để bảo đảm an toàn cho bản thân và những người tham gia "
    "giao thông khác. Việc nắm rõ các quy định xử phạt cũng giúp bạn chủ động "
    "phòng tránh vi phạm. Ngoài ra, mức xử phạt cụ thể trong từng trường hợp còn "
    "có thể được xem xét trên cơ sở tình tiết tăng nặng hoặc giảm nhẹ theo quy "
    "định của Luật Xử lý vi phạm hành chính. Nếu cần, bạn có thể liên hệ cơ quan "
    "chức năng để được hướng dẫn chi tiết hơn."
)

CONFIDENT_PREFIX = (
    "Căn cứ trực tiếp khoản 2 Điều 21 và điểm c khoản 5 Điều 6 Nghị định "
    "168/2024/NĐ-CP, có thể khẳng định chắc chắn rằng "
)


def fine_sentence(fmin, fmax):
    if fmin is None or fmax is None:
        return ""
    if fmin == fmax:
        return f"phạt tiền {money(fmin)}"
    return f"phạt tiền từ {money(fmin)} đến {money(fmax)}"


def points_sentence(pts):
    return f"trừ {pts:02d} điểm giấy phép lái xe" if pts else ""


def revocation_sentence(rev):
    if not rev:
        return ""
    lo, hi = rev.get("value_min"), rev.get("value_max")
    if lo and hi:
        return f"tước quyền sử dụng giấy phép lái xe từ {lo} tháng đến {hi} tháng"
    return "tước quyền sử dụng giấy phép lái xe"


def join_parts(parts):
    parts = [p for p in parts if p]
    if not parts:
        return "không áp dụng hình thức xử phạt nào."
    return "; ".join(parts) + "."


# ============================================================
# Bộ sinh biến thể: mỗi hàm trả list (loại, text, nhãn, mô tả lỗi)
# ============================================================

def _simple_parts(r):
    return [
        fine_sentence(r.get("fine_min"), r.get("fine_max")),
        points_sentence(r.get("license_points_deduction")),
        revocation_sentence(r.get("license_revocation")),
    ]


def gen_simple(item, rng):
    r = item.get("rubrics") or {}
    fmin, fmax = r.get("fine_min"), r.get("fine_max")
    pts = r.get("license_points_deduction")
    rev = r.get("license_revocation")

    base = "Hành vi vi phạm bị xử phạt như sau: " + join_parts(_simple_parts(r))
    out = [("correct", base, "pass", None)]

    out.append((
        "verbose_correct",
        base + " " + FILLER,
        "pass",
        "đúng nội dung nhưng viết dài gấp nhiều lần mức cần thiết",
    ))

    if fmin is not None and fmax is not None:
        bad_min, bad_max = int(fmin * 1.5), int(fmax * 2)
        parts = [fine_sentence(bad_min, bad_max)] + _simple_parts(r)[1:]
        out.append((
            "fine_shift",
            "Hành vi vi phạm bị xử phạt như sau: " + join_parts(parts),
            "fail",
            f"mức phạt đúng {fmin}-{fmax}, trả lời {bad_min}-{bad_max}",
        ))

        parts = [f"phạt tiền {money(fmin)}"] + _simple_parts(r)[1:]
        out.append((
            "fine_partial",
            "Hành vi vi phạm bị xử phạt như sau: " + join_parts(parts),
            "fail",
            f"chỉ nêu cận dưới {fmin}, bỏ cận trên {fmax}",
        ))

        out.append((
            "confident_wrong",
            CONFIDENT_PREFIX
            + f"hành vi này bị {fine_sentence(int(fmin * 3), int(fmax * 3))}. "
            + "Đây là mức xử phạt đã được áp dụng thống nhất trên toàn quốc.",
            "fail",
            "mức phạt sai gấp 3 lần nhưng diễn đạt rất tự tin, có trích dẫn giả",
        ))

    if pts:
        parts = [_simple_parts(r)[0], "", _simple_parts(r)[2]]
        out.append((
            "drop_points",
            "Hành vi vi phạm bị xử phạt như sau: " + join_parts(parts),
            "fail",
            f"bỏ sót trừ {pts} điểm GPLX",
        ))

    if rev:
        parts = _simple_parts(r)[:2] + [""]
        out.append((
            "drop_revocation",
            "Hành vi vi phạm bị xử phạt như sau: " + join_parts(parts),
            "fail",
            "bỏ sót tước quyền sử dụng GPLX",
        ))

    return out


def gen_exception(item, rng):
    r = item.get("rubrics") or {}
    fmin, fmax = r.get("fine_if_penalized_min"), r.get("fine_if_penalized_max")
    exc = r.get("exception", "")

    correct = (
        f"Trường hợp này KHÔNG bị xử phạt. Quy định đã loại trừ rõ: {exc}. "
        "Do đó không áp dụng phạt tiền hay hình thức xử phạt bổ sung nào."
    )
    out = [("correct", correct, "pass", None)]
    out.append((
        "verbose_correct", correct + " " + FILLER, "pass",
        "đúng nội dung nhưng viết dài dòng",
    ))

    if fmin is not None and fmax is not None:
        out.append((
            "exception_ignored",
            "Hành vi này bị xử phạt: " + fine_sentence(fmin, fmax) + ".",
            "fail",
            f"áp mức phạt dù tình huống rơi vào ngoại lệ ({exc})",
        ))
        out.append((
            "confident_wrong",
            CONFIDENT_PREFIX
            + f"hành vi này chắc chắn bị {fine_sentence(fmin, fmax)}, "
            + "không có trường hợp ngoại lệ nào được áp dụng.",
            "fail",
            "phủ nhận ngoại lệ, diễn đạt rất tự tin",
        ))

    return out


def gen_insufficient(item, rng):
    r = item.get("rubrics") or {}
    missing = r.get("missing_info", "")
    fmin = r.get("fine_if_resolved_min")
    fmax = r.get("fine_if_resolved_max")

    correct = (
        "Thông tin hiện tại CHƯA ĐỦ để kết luận chính xác mức xử phạt. "
        f"Cần làm rõ thêm: {missing} "
        "Sau khi xác định được hành vi cụ thể mới có thể nêu mức phạt tương ứng."
    )
    out = [("correct", correct, "pass", None)]
    out.append((
        "verbose_correct", correct + " " + FILLER, "pass",
        "đúng nội dung nhưng viết dài dòng",
    ))

    if fmin is not None and fmax is not None:
        out.append((
            "insufficient_overclaim",
            "Hành vi vi phạm bị " + fine_sentence(fmin, fmax) + ". "
            "Không có hình thức xử phạt bổ sung nào khác.",
            "fail",
            "khẳng định một mức phạt cụ thể trong khi câu hỏi thiếu thông tin",
        ))
        out.append((
            "confident_wrong",
            CONFIDENT_PREFIX
            + f"trường hợp này bị {fine_sentence(fmin, fmax)}. "
            + "Không cần bổ sung thêm thông tin nào.",
            "fail",
            "khẳng định chắc chắn và phủ nhận việc cần làm rõ",
        ))

    return out


def gen_multihop(item, rng):
    exp = item.get("expected") or {}
    fmin, fmax = exp.get("total_fine_min"), exp.get("total_fine_max")
    pts = exp.get("total_points_deduction")
    per_rule = exp.get("per_rule") or []

    revs = exp.get("license_revocations") or []
    rev = None
    if revs:
        rev = {
            "value_min": min(v["value_min"] for v in revs if v.get("value_min")),
            "value_max": max(v["value_max"] for v in revs if v.get("value_max")),
        }

    parts = [fine_sentence(fmin, fmax), points_sentence(pts),
             revocation_sentence(rev)]
    base = "Tổng hợp các hành vi vi phạm, mức xử phạt là: " + join_parts(parts)
    out = [("correct", base, "pass", None)]
    out.append((
        "verbose_correct", base + " " + FILLER, "pass",
        "đúng nội dung nhưng viết dài dòng",
    ))

    if fmin is not None and fmax is not None:
        # chỉ trả lời rule đầu tiên có mức phạt -> thiếu phần cộng dồn
        first = next((r for r in per_rule if r.get("fine_min") is not None), None)
        if first and len(per_rule) > 1 and first["fine_max"] != fmax:
            out.append((
                "multihop_partial",
                "Hành vi vi phạm bị "
                + fine_sentence(first["fine_min"], first["fine_max"]) + ".",
                "fail",
                f"chỉ trả lời {first['rule_id']}, bỏ các quy định còn lại "
                f"(tổng đúng {fmin}-{fmax})",
            ))

        bad_min, bad_max = int(fmin * 1.5), int(fmax * 2)
        out.append((
            "fine_shift",
            "Tổng hợp các hành vi vi phạm, mức xử phạt là: "
            + join_parts([fine_sentence(bad_min, bad_max), points_sentence(pts),
                          revocation_sentence(rev)]),
            "fail",
            f"tổng mức phạt đúng {fmin}-{fmax}, trả lời {bad_min}-{bad_max}",
        ))

        out.append((
            "confident_wrong",
            CONFIDENT_PREFIX
            + f"tổng mức xử phạt là {fine_sentence(int(fmin * 3), int(fmax * 3))}, "
            + "áp dụng thống nhất cho toàn bộ các hành vi nêu trên.",
            "fail",
            "tổng sai gấp 3 lần, diễn đạt rất tự tin",
        ))

    if pts:
        out.append((
            "drop_points",
            "Tổng hợp các hành vi vi phạm, mức xử phạt là: "
            + join_parts([fine_sentence(fmin, fmax), revocation_sentence(rev)]),
            "fail",
            f"bỏ sót trừ {pts} điểm GPLX",
        ))

    return out


GENERATORS = {
    "simple": gen_simple,
    "exception": gen_exception,
    "insufficient": gen_insufficient,
    "multihop": gen_multihop,
}

SOURCES = [
    ("simple", "simple_fixed.json"),
    ("exception", "exception_fixed.json"),
    ("insufficient", "insufficient_fixed.json"),
    ("multihop", "multihop_fixed.json"),
]


def main(per_type, seed, output_file):
    rng = random.Random(seed)
    eval_set = []
    summary = {}

    for qtype, filename in SOURCES:
        path = OUTPUT_GENERATE / filename
        if not path.exists():
            print(f"[SKIP] chưa có {path} — chạy fix_rubrics/ trước")
            continue

        dataset = load_json(path)
        usable = [x for x in dataset if x.get("rubric_status") == "ok"]
        rng.shuffle(usable)

        # Mỗi câu hỏi gốc sinh ra 5-7 biến thể, nên chỉ lấy đủ số câu hỏi gốc
        # cần thiết để chạm mốc `per_type` câu trả lời cho loại này.
        made = 0
        used = 0
        for idx, item in enumerate(usable):
            if made >= per_type:
                break
            used += 1
            for ptype, text, gold, note in GENERATORS[qtype](item, rng):
                eval_set.append({
                    "eval_id": f"{qtype}-{idx}-{ptype}",
                    "question_type": qtype,
                    "source_file": filename,
                    "question": item["question"],
                    "rubrics": item.get("rubrics"),
                    "expected": item.get("expected"),
                    "model_answer": text,
                    "perturbation_type": ptype,
                    "gold_verdict": gold,
                    "injected_error": note,
                })
                made += 1

        summary[qtype] = {"nguon_dung_duoc": len(usable), "cau_hoi_goc_dung": used,
                          "cau_tra_loi": made}

    save_json(eval_set, output_file)

    print(f"Tổng số mẫu đánh giá: {len(eval_set)}")
    for qtype, s in summary.items():
        print(f"  {qtype:14s} {s}")

    print("\nPhân bố nhãn:", dict(Counter(x["gold_verdict"] for x in eval_set)))
    print("Phân bố loại lỗi:")
    for k, v in sorted(Counter(x["perturbation_type"] for x in eval_set).items()):
        print(f"  {k:24s} {v}")
    print(f"\nOutput: {output_file}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Tiêm lỗi có kiểm soát để tạo nhãn vàng")
    p.add_argument("--per-type", type=int, default=50,
                   help="Số CÂU TRẢ LỜI sinh ra cho mỗi loại câu hỏi. Default: 50")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default="eval_set/perturbed.json")
    a = p.parse_args()
    main(a.per_type, a.seed, a.out)
