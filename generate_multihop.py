import json
import time
import random
from pathlib import Path

from llm import llm_chat


# ============================================================
# CONFIG
# ============================================================

POINTS_FILE = Path("law_db/points.json")
CLAUSES_FILE = Path("law_db/clauses.json")
ARTICLES_FILE = Path("law_db/articles.json")
PENALTY_DB_FILE = Path("law_db/penalty_db.json")

OUTPUT_FILE = Path(
    "output_generate/multihop_questions.json"
)

TARGET_SAMPLES = 600
SLEEP_SECONDS = 10


# ============================================================
# LOAD JSON
# ============================================================

def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


points = load_json(POINTS_FILE)
clauses = load_json(CLAUSES_FILE)
articles = load_json(ARTICLES_FILE)
penalty_db = load_json(PENALTY_DB_FILE)


# ============================================================
# GENERIC INDEX
# ============================================================

def build_index(data, possible_keys):

    """
    Tạo index theo key có trong object.

    Ví dụ:
        article_id
        id
        clause_id
    """

    index = {}

    for item in data:

        for key in possible_keys:

            if key in item:

                value = item[key]

                if value is not None:

                    index[str(value)] = item

                    break

    return index


# ============================================================
# BUILD ARTICLE / CLAUSE INDEX
# ============================================================

article_index = build_index(
    articles,
    [
        "article_id",
        "id"
    ]
)

clause_index = build_index(
    clauses,
    [
        "clause_id",
        "id"
    ]
)


# ============================================================
# GET ARTICLE ID
# ============================================================

def get_article_id(point):

    """
    point_id:

        6.3.h

    => article_id = 6
    """

    return int(
        point["point_id"]
        .split(".")[0]
    )


# ============================================================
# GET ARTICLE METADATA
# ============================================================

def get_article_metadata(
    article_id
):

    article = article_index.get(
        str(article_id)
    )

    if article is None:

        return {
            "article_id": article_id,
            "name": "",
            "content": ""
        }

    return article


# ============================================================
# GET CLAUSE METADATA
# ============================================================

def get_clause_metadata(
    point
):

    clause_id = str(
        point["clause_id"]
    )

    # --------------------------------------------------------
    # Thử match trực tiếp
    # --------------------------------------------------------

    clause = clause_index.get(
        clause_id
    )

    if clause:

        return clause

    # --------------------------------------------------------
    # Một số DB có thể lưu:
    #
    # 6.3
    #
    # trong khi point có:
    #
    # 6.3
    # --------------------------------------------------------

    return {
        "clause_id": clause_id,
        "name": "",
        "content": ""
    }


# ============================================================
# BUILD FULL LAW CONTEXT
# ============================================================

def build_point_context(point):

    article_id = get_article_id(
        point
    )

    article = get_article_metadata(
        article_id
    )

    clause = get_clause_metadata(
        point
    )

    return {

        "article": {

            "article_id": article_id,

            "name": (
                article.get("name")
                or article.get("title")
                or article.get("content")
                or ""
            )

        },

        "clause": {

            "clause_id": point.get(
                "clause_id"
            ),

            "name": (
                clause.get("name")
                or clause.get("title")
                or ""
            ),

            "content": clause.get(
                "content",
                ""
            )

        },

        "point": {

            "point_id": point.get(
                "point_id"
            ),

            "label": point.get(
                "label"
            ),

            "content": point.get(
                "content",
                ""
            )

        }

    }


# ============================================================
# GROUP POINTS BY ARTICLE
# ============================================================

def group_points_by_article(
    points
):

    grouped = {}

    for point in points:

        try:

            article_id = get_article_id(
                point
            )

        except Exception:

            continue

        if article_id not in grouped:

            grouped[article_id] = []

        grouped[
            article_id
        ].append(point)

    return grouped


# ============================================================
# QUERY SUPPLEMENTARY PENALTIES
# ============================================================

def get_supplementary_penalties(
    article_id,
    clause_id,
    point_id
):

    """
    Query penalty DB.

    Không sử dụng LLM.

    Ưu tiên:
        article + clause + point

    hoặc:
        article + clause + toàn clause
    """

    results = []

    for penalty in penalty_db:

        if penalty.get(
            "article_id"
        ) != article_id:

            continue

        if str(
            penalty.get("clause_id")
        ) != str(clause_id):

            continue

        penalty_point = penalty.get(
            "point_id"
        )

        # Point-specific penalty

        if penalty_point == point_id:

            results.append(
                penalty
            )

        # Clause-level penalty

        elif penalty_point is None:

            results.append(
                penalty
            )

    return results


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT_2 = """
Bạn là chuyên gia pháp luật giao thông Việt Nam.

Nhiệm vụ:

Cho trước HAI quy định pháp luật thuộc CÙNG MỘT ĐIỀU.

Hãy sinh một câu hỏi dạng MULTIHOP.

==================================================
MỤC TIÊU
==================================================

Câu hỏi phải yêu cầu người trả lời kết hợp
thông tin từ HAI quy định để đưa ra câu trả lời.

Không được chỉ đơn giản hỏi:

"X và Y bị phạt bao nhiêu?"

Mà phải tạo một tình huống có hai hành vi
hoặc hai điều kiện liên quan.

Người trả lời phải xác định được:

1. Hành vi thứ nhất.
2. Hành vi thứ hai.
3. Mức xử phạt tương ứng.
4. Kết luận tổng hợp.

==================================================
QUY TẮC
==================================================

1. Hai quy định bắt buộc thuộc CÙNG MỘT ĐIỀU.

2. Chỉ sử dụng thông tin có trong input.

3. Không tự thêm tình tiết pháp lý.

4. Không tự suy đoán hình phạt bổ sung.

5. Mức phạt tiền phải lấy trực tiếp từ
   quy định được cung cấp.

6. Không cộng hai mức phạt thành một
   mức phạt tổng nếu pháp luật không nói như vậy.

7. Mỗi hành vi là một atomic rule.

8. Câu hỏi phải có tính kết hợp:
   người đọc cần xác định cả hai hành vi
   trước khi đưa ra kết luận.

9. Câu hỏi cuối cùng phải yêu cầu:

   "Theo quy định pháp luật, trường hợp này
   bị xử phạt như thế nào?"

10. Không đưa mức phạt vào question.

==================================================
RUBRIC
==================================================

Rubric phải là atomic.

R1:
Kiểm tra câu trả lời có xác định đúng
và xử lý đúng quy định thứ nhất.

R2:
Kiểm tra câu trả lời có xác định đúng
và xử lý đúng quy định thứ hai.

R3:
Kiểm tra câu trả lời có đưa ra kết luận
tổng hợp đầy đủ cho tình huống hay không.

==================================================
OUTPUT
==================================================

Chỉ trả về JSON.

Schema:

{
    "question_type": "multihop",

    "question": "...",

    "rubrics": [

        {
            "rule_id": "R1",

            "action": "...",

            "fine_min": 0,

            "fine_max": 0
        },

        {
            "rule_id": "R2",

            "action": "...",

            "fine_min": 0,

            "fine_max": 0
        },

        {
            "rule_id": "R3",

            "action": "combined_conclusion"
        }

    ]
}

Không thêm explanation.

Không thêm markdown.
"""

SYSTEM_PROMPT_3 = """
Bạn là chuyên gia pháp luật giao thông Việt Nam.

Nhiệm vụ:

Cho trước BA quy định pháp luật thuộc CÙNG MỘT ĐIỀU.

Hãy sinh một câu hỏi dạng MULTIHOP.

==================================================
MỤC TIÊU
==================================================

Câu hỏi phải yêu cầu người trả lời kết hợp
thông tin từ BA quy định để đưa ra câu trả lời.

Không được chỉ đơn giản hỏi:

"X, Y và Z bị phạt bao nhiêu?"

Mà phải tạo một tình huống có ba hành vi
hoặc ba điều kiện liên quan.

Người trả lời phải xác định được:

1. Hành vi thứ nhất.
2. Hành vi thứ hai.
3. Hành vi thứ ba.
4. Mức xử phạt tương ứng cho từng hành vi.
5. Kết luận tổng hợp.

==================================================
QUY TẮC
==================================================

1. Ba quy định bắt buộc thuộc CÙNG MỘT ĐIỀU.

2. Chỉ sử dụng thông tin có trong input.

3. Không tự thêm tình tiết pháp lý.

4. Không tự suy đoán hình phạt bổ sung.

5. Mức phạt tiền phải lấy trực tiếp từ
   quy định được cung cấp.

6. Không cộng các mức phạt thành một
   mức phạt tổng nếu pháp luật không nói như vậy.

7. Mỗi hành vi là một atomic rule.

8. Câu hỏi phải có tính kết hợp:
   người đọc cần xác định cả ba hành vi
   trước khi đưa ra kết luận.

9. Câu hỏi cuối cùng phải yêu cầu:

   "Theo quy định pháp luật, trường hợp này
   bị xử phạt như thế nào?"

10. Không đưa mức phạt vào question.

==================================================
RUBRIC
==================================================

Rubric phải là atomic.

R1:
Kiểm tra câu trả lời có xác định đúng
và xử lý đúng quy định thứ nhất.

R2:
Kiểm tra câu trả lời có xác định đúng
và xử lý đúng quy định thứ hai.

R3:
Kiểm tra câu trả lời có xác định đúng
và xử lý đúng quy định thứ ba.

R4:
Kiểm tra câu trả lời có đưa ra kết luận
tổng hợp đầy đủ cho tình huống hay không.

==================================================
OUTPUT
==================================================

Chỉ trả về JSON.

Schema:

{
    "question_type": "multihop",

    "question": "...",

    "rubrics": [

        {
            "rule_id": "R1",

            "action": "...",

            "fine_min": 0,

            "fine_max": 0
        },

        {
            "rule_id": "R2",

            "action": "...",

            "fine_min": 0,

            "fine_max": 0
        },

        {
            "rule_id": "R3",

            "action": "...",

            "fine_min": 0,

            "fine_max": 0
        },

        {
            "rule_id": "R4",

            "action": "combined_conclusion"
        }

    ]
}

Không thêm explanation.

Không thêm markdown.
"""


# ============================================================
# GENERATE MULTIHOP
# ============================================================

def generate_multihop(
    point_list
):

    num_points = len(point_list)

    if num_points not in (2, 3):

        raise ValueError(
            "Multihop requires 2 or 3 points."
        )

    # --------------------------------------------------------
    # Safety check: all points same article
    # --------------------------------------------------------

    article_ids = [
        get_article_id(p)
        for p in point_list
    ]

    if len(set(article_ids)) != 1:

        raise ValueError(
            "Multihop requires points "
            "from the same article."
        )

    article_id = article_ids[0]

    contexts = [
        build_point_context(p)
        for p in point_list
    ]

    article = get_article_metadata(
        article_id
    )

    # --------------------------------------------------------
    # USER PROMPT
    # --------------------------------------------------------

    quy_dinh_blocks = []

    for i, ctx in enumerate(
        contexts,
        start=1
    ):

        block = f"""
============================================================
QUY ĐỊNH {i}
============================================================

ARTICLE:

{json.dumps(
    ctx["article"],
    ensure_ascii=False,
    indent=2
)}

CLAUSE:

{json.dumps(
    ctx["clause"],
    ensure_ascii=False,
    indent=2
)}

POINT:

{json.dumps(
    ctx["point"],
    ensure_ascii=False,
    indent=2
)}
"""

        quy_dinh_blocks.append(block)

    so_hanh_vi = (
        "hai" if num_points == 2
        else "ba"
    )

    so_quy_dinh = (
        "hai" if num_points == 2
        else "ba"
    )

    user_prompt = f"""
ĐIỀU {article_id}

TÊN ĐIỀU:

{article.get("name", article.get("title", ""))}

{"".join(quy_dinh_blocks)}

============================================================
TASK
============================================================

Hãy tạo MỘT câu hỏi MULTIHOP dựa trên
{so_quy_dinh} quy định trên.

Tạo một tình huống trong đó {so_hanh_vi} hành vi
cùng xảy ra.

Câu hỏi phải kết thúc bằng yêu cầu:

"Theo quy định pháp luật, trường hợp này
bị xử phạt như thế nào?"

Không đưa mức phạt vào câu hỏi.

Chỉ trả về JSON.
"""

    system_prompt = (
        SYSTEM_PROMPT_2
        if num_points == 2
        else SYSTEM_PROMPT_3
    )

    messages = [

        {
            "role": "system",
            "content": system_prompt
        },

        {
            "role": "user",
            "content": user_prompt
        }

    ]

    result = llm_chat(
        messages
    )

    content = result[
        "content"
    ].strip()

    # --------------------------------------------------------
    # Remove markdown fence
    # --------------------------------------------------------

    if content.startswith(
        "```"
    ):

        content = content.replace(
            "```json",
            ""
        )

        content = content.replace(
            "```",
            ""
        )

        content = content.strip()

    data = json.loads(
        content
    )

    return data


# ============================================================
# VALIDATE LLM OUTPUT
# ============================================================

def validate_generated(
    generated,
    num_points
):

    if not isinstance(
        generated,
        dict
    ):

        return False

    if generated.get(
        "question_type"
    ) != "multihop":

        return False

    if not generated.get(
        "question"
    ):

        return False

    rubrics = generated.get(
        "rubrics"
    )

    if not isinstance(
        rubrics,
        list
    ):

        return False

    rule_ids = {

        r.get("rule_id")

        for r in rubrics
    }

    # 2 points: R1, R2, R3
    # 3 points: R1, R2, R3, R4

    required = {
        f"R{i}"
        for i in range(
            1,
            num_points + 2
        )
    }

    if not required.issubset(
        rule_ids
    ):

        return False

    return True


# ============================================================
# ENRICH WITH DATABASE
# ============================================================

def enrich_with_metadata(
    generated,
    point_list
):

    article_id = get_article_id(
        point_list[0]
    )

    sources = []
    supplementary = []

    for point in point_list:

        clause_num = str(
            point["clause_id"]
        ).split(".")[-1]

        point_label = point.get(
            "label"
        )

        sources.append(
            {
                "article_id": article_id,

                "clause_id": clause_num,

                "point_id": point_label
            }
        )

        penalties = (
            get_supplementary_penalties(
                article_id,
                clause_num,
                point_label
            )
        )

        supplementary.extend(
            penalties
        )

    generated["sources"] = sources

    generated[
        "supplementary_penalties"
    ] = supplementary

    return generated


# ============================================================
# SAVE DATASET
# ============================================================

def save_dataset(
    dataset
):

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp_file = (
        OUTPUT_FILE.with_suffix(
            ".tmp"
        )
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            dataset,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(
        OUTPUT_FILE
    )


# ============================================================
# LOAD EXISTING DATASET
# ============================================================

def load_existing_dataset():

    if not OUTPUT_FILE.exists():

        return []

    try:

        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception as e:

        print(
            f"Cannot load existing dataset: {e}"
        )

        return []


# ============================================================
# GET EXISTING PAIRS
# ============================================================

def get_existing_groups(
    dataset
):

    existing = set()

    for sample in dataset:

        sources = sample.get(
            "sources",
            []
        )

        if len(sources) < 2:

            continue

        keys = []

        for source in sources:

            key = (

                source.get(
                    "article_id"
                ),

                str(
                    source.get(
                        "clause_id"
                    )
                ),

                str(
                    source.get(
                        "point_id"
                    )
                )

            )

            keys.append(
                key
            )

        group = tuple(
            sorted(keys)
        )

        existing.add(
            group
        )

    return existing


# ============================================================
# BUILD PAIRS
# ============================================================

def make_point_key(
    article_id,
    point
):

    return (

        article_id,

        str(
            point["clause_id"]
        ).split(".")[-1],

        str(
            point.get("label")
        )

    )


def build_candidate_groups(
    points,
    existing_groups
):

    grouped = (
        group_points_by_article(
            points
        )
    )

    candidates = []

    for article_id, article_points in grouped.items():

        if len(article_points) < 2:

            continue

        n = len(article_points)

        # ----------------------------------------------------
        # All pairs (2-point groups)
        # ----------------------------------------------------

        for i in range(n):

            for j in range(
                i + 1,
                n
            ):

                group_keys = tuple(
                    sorted(
                        [
                            make_point_key(
                                article_id,
                                article_points[i]
                            ),

                            make_point_key(
                                article_id,
                                article_points[j]
                            )
                        ]
                    )
                )

                if group_keys in existing_groups:

                    continue

                candidates.append(
                    [
                        article_points[i],
                        article_points[j]
                    ]
                )

        # ----------------------------------------------------
        # All triples (3-point groups)
        # ----------------------------------------------------

        if n < 3:

            continue

        for i in range(n):

            for j in range(
                i + 1,
                n
            ):

                for k in range(
                    j + 1,
                    n
                ):

                    group_keys = tuple(
                        sorted(
                            [
                                make_point_key(
                                    article_id,
                                    article_points[i]
                                ),

                                make_point_key(
                                    article_id,
                                    article_points[j]
                                ),

                                make_point_key(
                                    article_id,
                                    article_points[k]
                                )
                            ]
                        )
                    )

                    if group_keys in existing_groups:

                        continue

                    candidates.append(
                        [
                            article_points[i],
                            article_points[j],
                            article_points[k]
                        ]
                    )

    return candidates


# ============================================================
# GENERATE DATASET
# ============================================================

def generate_dataset(
    points,
    num_samples=100
):

    # --------------------------------------------------------
    # Load existing
    # --------------------------------------------------------

    dataset = (
        load_existing_dataset()
    )

    print(
        f"Existing samples: "
        f"{len(dataset)}"
    )

    if len(dataset) >= num_samples:

        print(
            "Dataset already completed."
        )

        return dataset[
            :num_samples
        ]

    # --------------------------------------------------------
    # Existing groups
    # --------------------------------------------------------

    existing_groups = (
        get_existing_groups(
            dataset
        )
    )

    print(
        f"Existing groups: "
        f"{len(existing_groups)}"
    )

    # --------------------------------------------------------
    # Candidate groups
    # --------------------------------------------------------

    candidates = build_candidate_groups(
        points,
        existing_groups
    )

    print(
        f"Available new groups: "
        f"{len(candidates)}"
    )

    # --------------------------------------------------------
    # Randomize
    # --------------------------------------------------------

    random.shuffle(
        candidates
    )

    remaining = (
        num_samples
        - len(dataset)
    )

    candidates = candidates[
        :remaining
    ]

    print(
        f"Will generate: "
        f"{len(candidates)} samples"
    )

    # --------------------------------------------------------
    # Generate
    # --------------------------------------------------------

    for idx, point_list in enumerate(
        candidates,
        start=1
    ):

        print(
            "\n"
            + "=" * 80
        )

        print(
            f"Sample "
            f"{len(dataset) + 1}"
            f"/{num_samples}"
        )

        for pi, p in enumerate(
            point_list,
            start=1
        ):

            print(
                f"Point {pi}: "
                f"{p['point_id']}"
            )

        try:

            # ================================================
            # 1. LLM GENERATION
            # ================================================

            generated = (
                generate_multihop(
                    point_list
                )
            )

            # ================================================
            # 2. VALIDATE
            # ================================================

            if not validate_generated(
                generated,
                len(point_list)
            ):

                print(
                    "[INVALID] "
                    "LLM output."
                )

                continue

            # ================================================
            # 3. ENRICH DATABASE INFO
            # ================================================

            generated = (
                enrich_with_metadata(
                    generated,
                    point_list
                )
            )

            # ================================================
            # 4. SAMPLE ID
            # ================================================

            generated[
                "sample_id"
            ] = len(dataset) + 1

            # ================================================
            # 5. APPEND
            # ================================================

            dataset.append(
                generated
            )

            # ================================================
            # 6. SAVE IMMEDIATELY
            # ================================================

            save_dataset(
                dataset
            )

            print(
                "\n[SAVED]"
            )

            print(
                json.dumps(
                    generated,
                    ensure_ascii=False,
                    indent=2
                )
            )

        except Exception as e:

            print(
                "\n[ERROR]"
            )

            print(
                f"{type(e).__name__}: {e}"
            )

        # ----------------------------------------------------
        # Sleep
        # ----------------------------------------------------

        if (
            idx < len(candidates)
            and len(dataset)
            < num_samples
        ):

            print(
                f"\nSleeping "
                f"{SLEEP_SECONDS}s..."
            )

            time.sleep(
                SLEEP_SECONDS
            )

    return dataset


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 80
    )

    print(
        "MULTIHOP QUESTION GENERATOR"
    )

    print(
        "=" * 80
    )

    print(
        f"Articles: "
        f"{len(articles)}"
    )

    print(
        f"Clauses: "
        f"{len(clauses)}"
    )

    print(
        f"Points: "
        f"{len(points)}"
    )

    print(
        f"Penalty DB: "
        f"{len(penalty_db)}"
    )

    dataset = generate_dataset(
        points,
        num_samples=TARGET_SAMPLES
    )

    print(
        "\n"
        + "=" * 80
    )

    print(
        f"FINAL DATASET: "
        f"{len(dataset)} samples"
    )

    print(
        f"Output: "
        f"{OUTPUT_FILE}"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()