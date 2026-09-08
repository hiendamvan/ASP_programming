# -*- coding: utf-8 -*-
"""
Giai đoạn 1c — vá rubric cho simple.json và insufficient.json.

Vấn đề:
  - simple: 105/602 mẫu có fine_min = fine_max = None (17%).
  - `additional_penalties` rỗng ở cả 602/602 mẫu -> field vô dụng, bỏ hẳn.
  - insufficient: 246/291 mẫu có mức phạt trong rubric dù đáp án đúng là
    "chưa đủ thông tin" -> mâu thuẫn nội tại. Tách rõ hai phần.

Cách sửa: parse lại mức phạt từ clauses.json intro. Mẫu nào vẫn không ra thì
gắn rubric_status = "incomplete" để LOẠI khỏi tập đánh giá một cách minh bạch,
thay vì âm thầm bỏ qua.
"""
import argparse
from collections import Counter

from law_lookup import (
    load_json, save_json, load_law_db, extract_fine,
    parse_point_penalty, OUTPUT_GENERATE,
)


SUPPLEMENTARY_MARKERS = (
    "hình thức xử phạt bổ sung",
    "biện pháp khắc phục hậu quả",
    "trừ điểm giấy phép lái xe",
    "tịch thu",
)


def is_supplementary(intro):
    low = (intro or "").lower()
    return any(m in low for m in SUPPLEMENTARY_MARKERS)


def fix_sample(sample, clause_by_id, point_by_id, question_type):
    src = sample.get("source") or {}
    rubrics = sample.setdefault("rubrics", {})

    point_id = src.get("point_id")
    clause_id = src.get("clause_id") or (
        ".".join(point_id.split(".")[:-1]) if point_id else None
    )

    # ---- mức phạt: vá từ clause intro nếu rubric đang thiếu ----
    clause = clause_by_id.get(str(clause_id))
    intro = clause["intro"] if clause else ""

    if rubrics.get("fine_min") is None or rubrics.get("fine_max") is None:
        fine = extract_fine(intro)
        if fine:
            rubrics["fine_min"] = fine["fine_min"]
            rubrics["fine_max"] = fine["fine_max"]

    # Khoản xử phạt BỔ SUNG (tịch thu / trừ điểm / khắc phục hậu quả) không có
    # mức phạt tiền theo thiết kế — không phải rubric hỏng. Đánh dấu để tiêu chí
    # nghiệm thu bên dưới không loại nhầm.
    rubrics["is_supplementary_clause"] = is_supplementary(intro)
    if rubrics["is_supplementary_clause"]:
        rubrics.setdefault("fine_min", None)
        rubrics.setdefault("fine_max", None)

    # ---- trừ điểm / tước GPLX: bù từ nội dung điểm luật ----
    point = point_by_id.get(point_id)
    if point:
        extra = parse_point_penalty(point["content"])
        if rubrics.get("license_points_deduction") is None:
            rubrics["license_points_deduction"] = extra["license_points"]
        if rubrics.get("license_revocation") is None:
            rubrics["license_revocation"] = extra["license_revocation"]

    if "tịch thu" in (intro or "").lower():
        rubrics["confiscation"] = True

    # additional_penalties rỗng ở toàn bộ 602 mẫu -> bỏ field
    rubrics.pop("additional_penalties", None)

    if question_type == "insufficient":
        # Đáp án đúng là "chưa đủ thông tin", KHÔNG phải một mức phạt cụ thể.
        # Giữ mức phạt lại nhưng đổi tên để không bị nhầm là ground truth.
        rubrics["expected_requires_clarification"] = True
        rubrics["expected_penalized"] = None
        for src_key, dst_key in (("fine_min", "fine_if_resolved_min"),
                                 ("fine_max", "fine_if_resolved_max")):
            if src_key in rubrics:
                rubrics[dst_key] = rubrics.pop(src_key)
        ok = bool(rubrics.get("missing_info"))
    else:
        rubrics["expected_requires_clarification"] = False
        rubrics["expected_penalized"] = True
        # Hợp lệ khi có mức phạt tiền, HOẶC là khoản bổ sung mà ta xác định
        # được ít nhất một hình phạt (trừ điểm / tước GPLX / tịch thu).
        has_fine = (rubrics.get("fine_min") is not None
                    and rubrics.get("fine_max") is not None)
        has_supp = (rubrics.get("license_points_deduction") is not None
                    or rubrics.get("license_revocation") is not None
                    or rubrics.get("confiscation") is not None)
        ok = has_fine or has_supp

    sample["rubric_status"] = "ok" if ok else "incomplete"
    return sample


def main(input_file, output_file, question_type):
    dataset = load_json(input_file)
    _, _, clause_by_id, point_by_id = load_law_db()

    before_missing = sum(
        1 for s in dataset if (s.get("rubrics") or {}).get("fine_min") is None
    )

    stats = Counter()
    for sample in dataset:
        try:
            fix_sample(sample, clause_by_id, point_by_id, question_type)
            stats[sample["rubric_status"]] += 1
        except Exception as e:
            print(f"[ERROR] sample {sample.get('id')}: {type(e).__name__}: {e}")
            sample["rubric_status"] = "error"
            stats["error"] += 1

    save_json(dataset, output_file)

    print(f"Đã xử lý {len(dataset)} mẫu {question_type}")
    print(f"  thiếu mức phạt trước khi vá : {before_missing}")
    print(f"  ok         : {stats['ok']}")
    print(f"  incomplete : {stats['incomplete']}  (sẽ bị loại khỏi tập đánh giá)")
    print(f"  error      : {stats['error']}")
    print(f"Output: {output_file}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Vá rubric cho simple / insufficient")
    p.add_argument("--input", default=str(OUTPUT_GENERATE / "simple.json"))
    p.add_argument("--output", default=str(OUTPUT_GENERATE / "simple_fixed.json"))
    p.add_argument("--type", default="simple", choices=["simple", "insufficient"])
    a = p.parse_args()
    main(a.input, a.output, a.type)
