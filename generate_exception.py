import json
import time
from pathlib import Path

from llm import llm_chat


# ============================================================
# CONFIG
# ============================================================

POINTS_FILE = Path(
    "law_db/points.json"
)

OUTPUT_FILE = Path(
    "output_generate/exception_questions.json"
)

TARGET_SAMPLES = 100

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


# ============================================================
# SAVE JSON
# ============================================================

def save_json(
    data,
    path
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # Ghi file tạm trước để tránh
    # file JSON bị corrupt nếu chương trình lỗi
    temp_file = path.with_suffix(
        ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(path)


# ============================================================
# LOAD EXISTING DATASET
# ============================================================

def load_existing_dataset():

    if not OUTPUT_FILE.exists():

        return []

    try:

        data = load_json(
            OUTPUT_FILE
        )

        print(
            f"Loaded existing samples: "
            f"{len(data)}"
        )

        return data

    except Exception as e:

        print(
            f"Cannot load existing dataset: {e}"
        )

        return []


# ============================================================
# GET ARTICLE ID
# ============================================================

def get_article_id(point):

    """
    Ví dụ:

    point_id = 6.3.h

    => article_id = 6
    """

    return int(
        point["point_id"]
        .split(".")[0]
    )


# ============================================================
# FILTER CANDIDATE POINTS
# ============================================================

def get_exception_candidates(points):

    """
    Chỉ lấy những point có từ "trừ".

    Đây chỉ là bước filter sơ bộ.
    LLM sẽ quyết định xem "trừ" có thực sự
    biểu diễn một exception hay chỉ là
    cross-reference.
    """

    candidates = []

    for point in points:

        content = point.get(
            "content",
            ""
        )

        if "trừ" in content.lower():

            candidates.append(
                point
            )

    return candidates


# ============================================================
# SYSTEM PROMPT
# ============================================================

EXCEPTION_SYSTEM_PROMPT = """

Bạn là chuyên gia pháp luật giao thông Việt Nam.

Nhiệm vụ:

Cho trước MỘT quy định pháp luật.

Hãy xác định xem quy định này có chứa một
NGOẠI LỆ thực sự hay không.

Nếu có ngoại lệ thực sự, hãy sinh một câu hỏi
pháp luật dạng EXCEPTION.

==================================================
1. NGOẠI LỆ HỢP LỆ
==================================================

Chỉ coi là exception nếu phần sau "trừ"
mô tả một:

- hành vi cụ thể
- điều kiện cụ thể
- tình huống cụ thể
- trường hợp cụ thể

Ví dụ:

"Điều khiển xe đi trên vỉa hè, trừ trường hợp
điều khiển xe đi qua vỉa hè để vào nhà, cơ quan."

Đây là exception hợp lệ.

Normal action:

"Điều khiển xe đi trên vỉa hè"

Exception:

"Điều khiển xe đi qua vỉa hè để vào nhà, cơ quan."

==================================================
2. KHÔNG COI LÀ EXCEPTION
==================================================

Nếu "trừ" chỉ dùng để dẫn chiếu đến một
quy định pháp luật khác thì KHÔNG phải
exception để sinh câu hỏi.

Ví dụ:

"Không chấp hành hiệu lệnh của biển báo,
trừ hành vi vi phạm quy định tại điểm a
khoản 4 Điều này."

Không sinh.

Ví dụ:

"..., trừ các hành vi vi phạm quy định
tại điểm a, điểm b khoản 3 Điều này."

Không sinh.

Ví dụ:

"..., trừ hành vi quy định tại khoản 3
Điều này."

Không sinh.

Đây chỉ là CROSS-REFERENCE.

==================================================
3. CÁCH SINH QUESTION
==================================================

Nếu có exception:

Câu hỏi phải mô tả tình huống trong đó
người thực hiện hành vi nằm trong trường hợp
ngoại lệ.

Câu hỏi cuối phải hỏi về hậu quả pháp lý,
ví dụ:

"Theo quy định pháp luật, trường hợp này
có bị xử phạt không? Nếu có thì bị xử phạt
như thế nào?"

Không thêm thông tin pháp lý ngoài input.

Không tự suy đoán mức phạt.

Không tự thêm điều kiện.

==================================================
4. OUTPUT
==================================================

Nếu KHÔNG có exception:

{
    "is_exception": false
}

Nếu CÓ exception:

{
    "is_exception": true,
    "question": "...",
    "normal_action": "...",
    "exception": "..."
}

Chỉ trả về JSON.

Không markdown.

Không explanation.
"""


# ============================================================
# GENERATE EXCEPTION QUESTION
# ============================================================

def generate_exception_question(
    point
):

    article_id = get_article_id(
        point
    )

    clause_id = point.get(
        "clause_id"
    )

    point_id = point.get(
        "point_id"
    )

    label = point.get(
        "label"
    )

    content = point.get(
        "content",
        ""
    )

    user_prompt = f"""
ĐIỀU: {article_id}

KHOẢN: {clause_id}

ĐIỂM: {point_id}

LABEL: {label}

NỘI DUNG QUY ĐỊNH:

{content}

Hãy kiểm tra quy định trên.

Đặc biệt chú ý từ "trừ".

Nếu phần sau "trừ" mô tả một hành vi,
điều kiện hoặc tình huống cụ thể,
hãy xác định đây là EXCEPTION và sinh
một câu hỏi.

Nếu phần sau "trừ" chỉ dẫn chiếu tới
điểm/khoản/Điều khác thì:

"is_exception": false

Chỉ trả về JSON.
"""

    messages = [

        {
            "role": "system",
            "content": EXCEPTION_SYSTEM_PROMPT
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

    # ==========================================
    # Remove markdown fence
    # ==========================================

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
# VALIDATE OUTPUT
# ============================================================

def validate_exception_output(
    result
):

    if not isinstance(
        result,
        dict
    ):

        return False

    if "is_exception" not in result:

        return False

    # ----------------------------------------
    # Không phải exception
    # ----------------------------------------

    if result["is_exception"] is False:

        return True

    # ----------------------------------------
    # Exception
    # ----------------------------------------

    required_fields = [

        "question",

        "normal_action",

        "exception"

    ]

    for field in required_fields:

        if not result.get(field):

            return False

    return True


# ============================================================
# BUILD FINAL SAMPLE
# ============================================================

def build_sample(
    point,
    generated
):

    article_id = get_article_id(
        point
    )

    return {

        "question_type": "exception",

        "question": generated[
            "question"
        ],

        "normal_action": generated[
            "normal_action"
        ],

        "exception": generated[
            "exception"
        ],

        "source": {

            "article_id": article_id,

            "clause_id": point.get(
                "clause_id"
            ),

            "point_id": point.get(
                "point_id"
            ),

            "label": point.get(
                "label"
            ),

            "content": point.get(
                "content"
            )

        }

    }


# ============================================================
# GENERATE DATASET
# ============================================================

def generate_dataset(
    points
):

    # ==========================================
    # Load existing samples
    # ==========================================

    dataset = load_existing_dataset()

    if len(dataset) >= TARGET_SAMPLES:

        print(
            f"Dataset already has "
            f"{len(dataset)} samples."
        )

        return dataset[
            :TARGET_SAMPLES
        ]

    # ==========================================
    # Candidate points
    # ==========================================

    candidates = get_exception_candidates(
        points
    )

    print(
        f"Total points: {len(points)}"
    )

    print(
        f"Points containing 'trừ': "
        f"{len(candidates)}"
    )

    # ==========================================
    # Existing point IDs
    #
    # Không sinh lại point đã có
    # ==========================================

    existing_point_ids = set()

    for sample in dataset:

        source = sample.get(
            "source",
            {}
        )

        point_id = source.get(
            "point_id"
        )

        if point_id:

            existing_point_ids.add(
                point_id
            )

    # ==========================================
    # Filter
    # ==========================================

    candidates = [

        point

        for point in candidates

        if point.get(
            "point_id"
        )
        not in existing_point_ids

    ]

    print(
        f"New candidates: "
        f"{len(candidates)}"
    )

    # ==========================================
    # Process
    # ==========================================

    for point in candidates:

        if len(dataset) >= TARGET_SAMPLES:

            break

        point_id = point.get(
            "point_id"
        )

        print(
            "\n"
            + "=" * 70
        )

        print(
            f"Current dataset: "
            f"{len(dataset)}/{TARGET_SAMPLES}"
        )

        print(
            f"Processing: {point_id}"
        )

        print(
            f"Content: "
            f"{point.get('content')}"
        )

        try:

            # ==================================
            # CALL LLM
            # ==================================

            generated = (
                generate_exception_question(
                    point
                )
            )

            # ==================================
            # VALIDATE
            # ==================================

            if not validate_exception_output(
                generated
            ):

                print(
                    "[INVALID OUTPUT]"
                )

                continue

            # ==================================
            # NO EXCEPTION
            # ==================================

            if generated[
                "is_exception"
            ] is False:

                print(
                    "[SKIP] "
                    "Cross-reference / "
                    "no concrete exception."
                )

                continue

            # ==================================
            # BUILD SAMPLE
            # ==================================

            sample = build_sample(
                point,
                generated
            )

            sample[
                "sample_id"
            ] = len(dataset) + 1

            # ==================================
            # APPEND
            # ==================================

            dataset.append(
                sample
            )

            # ==================================
            # SAVE IMMEDIATELY
            # ==================================

            save_json(
                dataset,
                OUTPUT_FILE
            )

            print(
                "\n[SAVED]"
            )

            print(
                json.dumps(
                    sample,
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

        # ======================================
        # SLEEP
        # ======================================

        if len(dataset) < TARGET_SAMPLES:

            print(
                f"\nSleeping "
                f"{SLEEP_SECONDS}s..."
            )

            time.sleep(
                SLEEP_SECONDS
            )

    # ==========================================
    # FINAL
    # ==========================================

    save_json(
        dataset,
        OUTPUT_FILE
    )

    return dataset


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 70
    )

    print(
        "EXCEPTION QUESTION GENERATOR"
    )

    print(
        "=" * 70
    )

    # ==========================================
    # Load points
    # ==========================================

    points = load_json(
        POINTS_FILE
    )

    print(
        f"Loaded {len(points)} points."
    )

    # ==========================================
    # Generate
    # ==========================================

    dataset = generate_dataset(
        points
    )

    print(
        "\n"
        + "=" * 70
    )

    print(
        f"DONE"
    )

    print(
        f"Generated: "
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