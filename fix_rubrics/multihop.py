# -*- coding: utf-8 -*-
"""
Giai đoạn 1a — sửa ground truth cho multihop_questions.json.

Vấn đề: cả 502/502 mẫu có rubric fine_min = fine_max = 0, tức là ground truth
mức phạt rỗng hoàn toàn. Đây lại chính là loại câu hỏi ASP judge có lợi thế nhất
(cộng dồn nhiều điều luật).

Cách sửa: dựng lại rubric từ law_db (KHÔNG gọi LLM) bằng hàm build_rubric() đã
có trong post_process/multihop.py, rồi bổ sung khối `expected` tổng hợp để ASP
judge kiểm tra được.

Lưu ý quan trọng: khoản không có mức phạt tiền (khoản trừ điểm / xử phạt bổ sung
/ biện pháp khắc phục, vd 7.13, 13.13, 32.18) ghi fine = null, KHÔNG phải 0 —
cần phân biệt "không có mức phạt" với "phạt 0 đồng".
"""
import argparse
from collections import Counter

from law_lookup import (
    load_json, save_json, load_law_db, build_rubric,
    full_point_id, parse_point_penalty, OUTPUT_GENERATE,
)


def build_expected(rubrics):
    """Tổng hợp các rubric con thành ground truth cấp câu hỏi."""
    total_min = total_max = 0
    has_fine = False
    total_points = 0
    has_points = False
    revocations = []
    per_rule = []

    for r in rubrics:
        if r.get("type") == "combined_conclusion":
            continue

        fmin, fmax = r.get("fine_min"), r.get("fine_max")
        if fmin is not None and fmax is not None:
            total_min += fmin
            total_max += fmax
            has_fine = True

        pts = r.get("license_points_deduction")
        if pts:
            total_points += pts
            has_points = True

        rev = r.get("license_revocation")
        if rev:
            revocations.append(rev)

        per_rule.append({
            "rule_id": r["rule_id"],
            "point_id": r.get("point_id"),
            "fine_min": fmin,
            "fine_max": fmax,
            "license_points_deduction": pts,
            "license_revocation": rev,
        })

    return {
        "total_fine_min": total_min if has_fine else None,
        "total_fine_max": total_max if has_fine else None,
        "total_points_deduction": total_points if has_points else None,
        "license_revocations": revocations,
        "expected_penalized": True,
        "per_rule": per_rule,
    }


def fix_sample(sample, clause_index, penalty_index, point_by_id):
    sources = sample.get("sources", []) or []

    rubrics = []
    for idx, src in enumerate(sources, start=1):
        rubric = build_rubric(
            source=src,
            clause_index=clause_index,
            penalty_index=penalty_index,
            rule_id=f"R{idx}",
        )
        # build_rubric() không gắn point_id — thêm vào để ASP truy vết được
        pid = full_point_id(
            src["article_id"], src["clause_id"], src.get("point_id")
        )
        rubric["point_id"] = pid

        # penalty_db.json bỏ sót nhiều điểm -> bù bằng cách parse chính
        # nội dung điểm luật (vd 7.13.a nêu rõ "trừ điểm ... 02 điểm").
        point = point_by_id.get(pid)
        if point:
            extra = parse_point_penalty(point["content"])
            if rubric.get("license_points_deduction") is None:
                rubric["license_points_deduction"] = extra["license_points"]
            if rubric.get("license_revocation") is None:
                rubric["license_revocation"] = extra["license_revocation"]

        rubrics.append(rubric)

    rubrics.append({
        "rule_id": f"R{len(sources) + 1}",
        "type": "combined_conclusion",
    })

    sample["rubrics"] = rubrics
    sample["expected"] = build_expected(rubrics)

    exp = sample["expected"]
    if exp["total_fine_min"] is None and exp["total_points_deduction"] is None:
        sample["rubric_status"] = "incomplete"
    else:
        sample["rubric_status"] = "ok"

    return sample


def main(input_file, output_file):
    dataset = load_json(input_file)
    clause_index, penalty_index, _, point_by_id = load_law_db()

    stats = Counter()
    for sample in dataset:
        try:
            fix_sample(sample, clause_index, penalty_index, point_by_id)
            stats[sample["rubric_status"]] += 1
        except Exception as e:
            print(f"[ERROR] sample {sample.get('sample_id')}: {type(e).__name__}: {e}")
            sample["rubric_status"] = "error"
            stats["error"] += 1

    save_json(dataset, output_file)

    print(f"Đã xử lý {len(dataset)} mẫu multihop")
    print(f"  ok         : {stats['ok']}")
    print(f"  incomplete : {stats['incomplete']}")
    print(f"  error      : {stats['error']}")
    print(f"Output: {output_file}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Sinh lại rubric multihop từ law_db")
    p.add_argument("--input", default=str(OUTPUT_GENERATE / "multihop_questions.json"))
    p.add_argument("--output", default=str(OUTPUT_GENERATE / "multihop_fixed.json"))
    a = p.parse_args()
    main(a.input, a.output)
