import json
from pathlib import Path


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_penalties(
    penalty_db,
    article_id,
    clause_id,
    point_id
):
    """
    Tìm tất cả hình phạt bổ sung áp dụng cho một point.

    Ưu tiên:
    1. penalty gắn trực tiếp với point
    2. penalty áp dụng cho toàn bộ clause
    """

    point_penalties = []
    clause_penalties = []

    for penalty in penalty_db:

        if penalty["article_id"] != article_id:
            continue

        if str(penalty["clause_id"]) != str(clause_id):
            continue

        penalty_point = penalty.get("point_id")

        # Penalty áp dụng trực tiếp cho point
        if penalty_point == point_id:
            point_penalties.append(penalty)

        # Penalty áp dụng cho toàn bộ clause
        elif penalty_point is None:
            clause_penalties.append(penalty)

    # Nếu có penalty cụ thể cho point thì lấy chúng.
    # Đồng thời vẫn lấy penalty cấp clause.
    return point_penalties + clause_penalties

def enrich_simple_sample(sample, penalty_db):

    source = sample["source"]

    article_id = source["article_id"]
    clause_id = source["clause_id"]
    point_id = source["point_id"]

    penalties = get_penalties(
        penalty_db=penalty_db,
        article_id=article_id,
        clause_id=clause_id,
        point_id=point_id
    )

    # Đảm bảo các field tồn tại
    rubrics = sample.setdefault("rubrics", {})

    rubrics.setdefault(
        "license_points_deduction",
        None
    )

    rubrics.setdefault(
        "license_revocation",
        None
    )

    rubrics.setdefault(
        "additional_penalties",
        []
    )

    for penalty in penalties:

        penalty_type = penalty["penalty_type"]

        # ==========================================
        # TRỪ ĐIỂM GPLX
        # ==========================================

        if penalty_type == "license_points":

            rubrics["license_points_deduction"] = \
                penalty["value"]

        # ==========================================
        # TƯỚC GPLX
        # ==========================================

        elif penalty_type == "license_revocation":

            rubrics["license_revocation"] = {
                "value_min": penalty.get("value_min"),
                "value_max": penalty.get("value_max"),
                "unit": penalty.get("unit")
            }

        # ==========================================
        # CÁC HÌNH PHẠT KHÁC
        # ==========================================

        else:

            rubrics["additional_penalties"].append({
                "penalty_type": penalty_type,
                "value": penalty.get("value"),
                "value_min": penalty.get("value_min"),
                "value_max": penalty.get("value_max"),
                "unit": penalty.get("unit")
            })

    return sample

def enrich_dataset(
    input_path,
    penalty_path,
    output_path
):

    dataset = load_json(input_path)
    penalty_db = load_json(penalty_path)

    enriched_dataset = []

    for sample in dataset:

        try:
            sample = enrich_simple_sample(
                sample,
                penalty_db
            )

            enriched_dataset.append(sample)

        except Exception as e:

            print(
                f"Error sample {sample.get('id')}: {e}"
            )

            # vẫn giữ sample gốc
            enriched_dataset.append(sample)

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            enriched_dataset,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"Saved {len(enriched_dataset)} samples "
        f"to {output_path}"
    )
    
if __name__ == "__main__":

    enrich_dataset(
        input_path="../output_generate/simple_dataset2.json",
        penalty_path="../law_db/penalty_db.json",
        output_path="../output_generate/simple_questions_enriched.json"
    )