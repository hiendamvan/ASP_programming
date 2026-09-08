# -*- coding: utf-8 -*-
"""
Giai đoạn 1b — thêm rubric máy đọc được cho exception_questions.json.

Vấn đề: 0/52 mẫu có field `rubrics`. Chỉ có `normal_action` / `exception` dạng
text, nên LLM judge phải tự suy diễn còn ASP judge thì không có gì để kiểm tra.

Cách sửa: dựng rubric từ source.content + clauses.json (KHÔNG gọi LLM). Nhãn
then chốt là `expected_penalized: false` — câu hỏi exception mô tả đúng tình
huống rơi vào vế "trừ ..." nên đáp án đúng là KHÔNG bị xử phạt.
"""
import argparse
from collections import Counter

from law_lookup import (
    load_json, save_json, load_law_db, extract_fine,
    parse_point_penalty, clause_id_of, OUTPUT_GENERATE,
)


def fix_sample(sample, clause_by_id, point_by_id):
    src = sample.get("source") or {}

    point_id = src.get("point_id")
    if point_id and point_id.count(".") < 2:
        point_id = f"{clause_id_of(src['article_id'], src['clause_id'])}.{point_id}"

    point = point_by_id.get(point_id)
    content = src.get("content") or (point["content"] if point else "")

    clause_id = clause_id_of(src["article_id"], src.get("clause_id"))
    clause = clause_by_id.get(clause_id)
    intro = clause["intro"] if clause else ""

    fine = extract_fine(intro) or {}
    extra = parse_point_penalty(content)

    sample["rubrics"] = {
        # Đáp án đúng: tình huống rơi vào ngoại lệ -> KHÔNG bị xử phạt.
        "expected_penalized": False,
        "is_exception_case": True,
        "normal_action": sample.get("normal_action", ""),
        "exception": sample.get("exception", ""),
        # Mức phạt sẽ áp dụng NẾU không rơi vào ngoại lệ — dùng để bắt lỗi
        # loại `exception_ignored` (model đọc sót chữ "trừ" và vẫn áp phạt).
        "fine_if_penalized_min": fine.get("fine_min"),
        "fine_if_penalized_max": fine.get("fine_max"),
        "license_points_if_penalized": extra["license_points"],
        "point_id": point_id,
        "point_content": content,
    }

    has_exception = bool(sample.get("exception"))
    has_fine = fine.get("fine_min") is not None
    sample["rubric_status"] = "ok" if (has_exception and has_fine) else "incomplete"

    return sample


def main(input_file, output_file):
    dataset = load_json(input_file)
    _, _, clause_by_id, point_by_id = load_law_db()

    stats = Counter()
    for sample in dataset:
        try:
            fix_sample(sample, clause_by_id, point_by_id)
            stats[sample["rubric_status"]] += 1
        except Exception as e:
            print(f"[ERROR] sample {sample.get('sample_id')}: {type(e).__name__}: {e}")
            sample["rubric_status"] = "error"
            stats["error"] += 1

    save_json(dataset, output_file)

    print(f"Đã xử lý {len(dataset)} mẫu exception")
    print(f"  ok         : {stats['ok']}")
    print(f"  incomplete : {stats['incomplete']}")
    print(f"  error      : {stats['error']}")
    print(f"Output: {output_file}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Thêm rubric cho exception questions")
    p.add_argument("--input", default=str(OUTPUT_GENERATE / "exception_questions.json"))
    p.add_argument("--output", default=str(OUTPUT_GENERATE / "exception_fixed.json"))
    a = p.parse_args()
    main(a.input, a.output)
