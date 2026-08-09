import json
import re
from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

MULTIHOP_FILE = Path(
    "../output_generate/multihop_questions.json"
)

CLAUSES_FILE = Path(
    "../law_db/clauses.json"
)

PENALTY_FILE = Path(
    "../law_db/penalty_db.json"
)

OUTPUT_FILE = Path(
    "../output_generate/multihop_enriched.json"
)


# ============================================================
# LOAD JSON
# ============================================================

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# NORMALIZE CLAUSE ID
# ============================================================

def normalize_clause_id(clause_id):
    """
    Convert:

        7.1  -> 1
        7.13 -> 13
        1    -> 1

    để match với sources trong multihop.json.
    """

    clause_id = str(clause_id)

    return clause_id.split(".")[-1]


# ============================================================
# BUILD CLAUSE INDEX
# ============================================================

def build_clause_index(clauses):
    """
    Tạo index:

        (article_id, clause_number)
            ->
        clause metadata
    """

    index = {}

    for clause in clauses:

        article_id = int(clause["article_id"])

        clause_number = normalize_clause_id(
            clause["clause_id"]
        )

        key = (
            article_id,
            clause_number
        )

        index[key] = clause

    return index


# ============================================================
# EXTRACT FINE FROM CLAUSE INTRO
# ============================================================

def extract_fine(intro):
    """
    Extract mức phạt từ intro.

    Ví dụ:

    Phạt tiền từ 200.000 đồng đến 400.000 đồng ...

    =>
        {
            "fine_min": 200000,
            "fine_max": 400000
        }

    Nếu không tìm thấy => None
    """

    if not intro:
        return None

    # Pattern:

    # Phạt tiền từ 200.000 đồng đến 400.000 đồng
    pattern_range = re.compile(
        r"phạt\s+tiền\s+từ\s+"
        r"([\d\.,]+)\s*đồng"
        r"\s+đến\s+"
        r"([\d\.,]+)\s*đồng",
        re.IGNORECASE
    )

    match = pattern_range.search(intro)

    if match:

        fine_min = int(
            match.group(1).replace(".", "")
        )

        fine_max = int(
            match.group(2).replace(".", "")
        )

        return {
            "fine_min": fine_min,
            "fine_max": fine_max
        }

    # --------------------------------------------------------
    # Trường hợp chỉ có một mức tiền
    # --------------------------------------------------------

    pattern_single = re.compile(
        r"phạt\s+tiền\s+"
        r"([\d\.,]+)\s*đồng",
        re.IGNORECASE
    )

    match = pattern_single.search(intro)

    if match:

        value = int(
            match.group(1).replace(".", "")
        )

        return {
            "fine_min": value,
            "fine_max": value
        }

    return None


# ============================================================
# GET CLAUSE FINE
# ============================================================

def get_clause_fine(
    clause_index,
    article_id,
    clause_id
):
    """
    Lấy mức phạt tiền từ intro của clause.
    """

    key = (
        int(article_id),
        normalize_clause_id(clause_id)
    )

    clause = clause_index.get(key)

    if clause is None:
        return None

    intro = clause.get("intro", "")

    return extract_fine(intro)


# ============================================================
# BUILD PENALTY INDEX
# ============================================================

def build_penalty_index(penalties):
    """
    Index penalty theo:

        (article_id, clause_id, point_id)

    """

    index = {}

    for penalty in penalties:

        article_id = int(
            penalty["article_id"]
        )

        clause_id = normalize_clause_id(
            penalty["clause_id"]
        )

        point_id = penalty.get("point_id")

        key = (
            article_id,
            clause_id,
            point_id
        )

        index.setdefault(
            key,
            []
        ).append(penalty)

    return index


# ============================================================
# GET PENALTIES
# ============================================================

def get_penalties(
    penalty_index,
    article_id,
    clause_id,
    point_id
):
    """
    Tìm hình phạt bổ sung.

    Ưu tiên:

    1. penalty cho point cụ thể
    2. penalty cho toàn bộ clause

    """

    article_id = int(article_id)

    clause_id = normalize_clause_id(
        clause_id
    )

    results = []

    # --------------------------------------------------------
    # Point-specific penalty
    # --------------------------------------------------------

    point_key = (
        article_id,
        clause_id,
        point_id
    )

    results.extend(
        penalty_index.get(
            point_key,
            []
        )
    )

    # --------------------------------------------------------
    # Clause-level penalty
    # --------------------------------------------------------

    clause_key = (
        article_id,
        clause_id,
        None
    )

    results.extend(
        penalty_index.get(
            clause_key,
            []
        )
    )

    return results


# ============================================================
# BUILD RUBRIC
# ============================================================

def build_rubric(
    source,
    clause_index,
    penalty_index,
    rule_id
):
    """
    Tạo rubric hoàn chỉnh cho một source.
    """

    article_id = source["article_id"]

    clause_id = source["clause_id"]

    point_id = source.get(
        "point_id"
    )

    # --------------------------------------------------------
    # Fine
    # --------------------------------------------------------

    fine = get_clause_fine(
        clause_index=clause_index,
        article_id=article_id,
        clause_id=clause_id
    )

    if fine:

        fine_min = fine["fine_min"]
        fine_max = fine["fine_max"]

    else:

        fine_min = None
        fine_max = None

    # --------------------------------------------------------
    # Supplementary penalties
    # --------------------------------------------------------

    penalties = get_penalties(
        penalty_index=penalty_index,
        article_id=article_id,
        clause_id=clause_id,
        point_id=point_id
    )

    # --------------------------------------------------------
    # Default fields
    # --------------------------------------------------------

    license_points = None

    license_revocation = None

    additional_penalties = []

    # --------------------------------------------------------
    # Parse penalties
    # --------------------------------------------------------

    for penalty in penalties:

        penalty_type = penalty[
            "penalty_type"
        ]

        # ================================================
        # LICENSE POINTS
        # ================================================

        if penalty_type == "license_points":

            license_points = penalty.get(
                "value"
            )

        # ================================================
        # LICENSE REVOCATION
        # ================================================

        elif penalty_type == "license_revocation":

            license_revocation = {
                "value_min": penalty.get(
                    "value_min"
                ),
                "value_max": penalty.get(
                    "value_max"
                ),
                "unit": penalty.get(
                    "unit"
                )
            }

        # ================================================
        # OTHER PENALTIES
        # ================================================

        else:

            additional_penalties.append({
                "penalty_type": penalty_type,
                "value": penalty.get(
                    "value"
                ),
                "value_min": penalty.get(
                    "value_min"
                ),
                "value_max": penalty.get(
                    "value_max"
                ),
                "unit": penalty.get(
                    "unit"
                )
            })

    # --------------------------------------------------------
    # Final rubric
    # --------------------------------------------------------

    return {
        "rule_id": rule_id,

        "fine_min": fine_min,

        "fine_max": fine_max,

        "license_points_deduction":
            license_points,

        "license_revocation":
            license_revocation,

        "additional_penalties":
            additional_penalties
    }


# ============================================================
# ENRICH SAMPLE
# ============================================================

def enrich_sample(
    sample,
    clause_index,
    penalty_index
):
    """
    Convert:

        rubrics hiện tại
            +
        sources
            +
        clauses.json
            +
        penalty.json

    thành rubric hoàn chỉnh.
    """

    sources = sample.get(
        "sources",
        []
    )

    new_rubrics = []

    for idx, source in enumerate(
        sources,
        start=1
    ):

        rubric = build_rubric(
            source=source,
            clause_index=clause_index,
            penalty_index=penalty_index,
            rule_id=f"R{idx}"
        )

        new_rubrics.append(
            rubric
        )

    # --------------------------------------------------------
    # Combined conclusion
    # --------------------------------------------------------

    new_rubrics.append({
        "rule_id": f"R{len(sources) + 1}",
        "type": "combined_conclusion"
    })

    sample["rubrics"] = new_rubrics

    # --------------------------------------------------------
    # Keep supplementary_penalties
    # for backward compatibility
    # --------------------------------------------------------

    supplementary = []

    for rubric in new_rubrics:

        if "license_revocation" in rubric:

            if rubric[
                "license_revocation"
            ] is not None:

                supplementary.append(
                    rubric[
                        "license_revocation"
                    ]
                )

        supplementary.extend(
            rubric.get(
                "additional_penalties",
                []
            )
        )

    sample[
        "supplementary_penalties"
    ] = supplementary

    return sample


# ============================================================
# MAIN
# ============================================================

def main():

    print("Loading data...")

    multihop = load_json(
        MULTIHOP_FILE
    )

    clauses = load_json(
        CLAUSES_FILE
    )

    penalties = load_json(
        PENALTY_FILE
    )

    print(
        f"Loaded {len(multihop)} multihop samples"
    )

    print(
        f"Loaded {len(clauses)} clauses"
    )

    print(
        f"Loaded {len(penalties)} penalties"
    )

    # --------------------------------------------------------
    # Build indexes
    # --------------------------------------------------------

    clause_index = build_clause_index(
        clauses
    )

    penalty_index = build_penalty_index(
        penalties
    )

    # --------------------------------------------------------
    # Enrich
    # --------------------------------------------------------

    enriched = []

    for sample in multihop:

        try:

            sample = enrich_sample(
                sample,
                clause_index,
                penalty_index
            )

            enriched.append(
                sample
            )

        except Exception as e:

            print(
                f"ERROR sample "
                f"{sample.get('sample_id')}: "
                f"{e}"
            )

            enriched.append(
                sample
            )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            enriched,
            f,
            ensure_ascii=False,
            indent=2
        )

    print()
    print(
        f"Done."
    )

    print(
        f"Saved to: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()