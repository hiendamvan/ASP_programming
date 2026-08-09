import json
import re
import time
from pathlib import Path

from llm import llm_chat


# ============================================================
# CONFIG
# ============================================================

INPUT_DIR = Path("source_data/deduction")
OUTPUT_FILE = Path("penalty_db.json")

SLEEP_SECONDS = 10


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
Bạn là chuyên gia xây dựng cơ sở dữ liệu pháp luật Việt Nam.

Nhiệm vụ:
Đọc phần văn bản pháp luật được cung cấp và trích xuất các
quy định về HÌNH THỨC XỬ PHẠT BỔ SUNG liên quan đến:

1. Tước quyền sử dụng giấy phép lái xe
2. Trừ điểm giấy phép lái xe

Mục tiêu là tạo ra database mapping:

HÀNH VI VI PHẠM
        ↓
HÌNH THỨC XỬ PHẠT

==================================================
QUY TẮC
==================================================

1. Chỉ trích xuất thông tin có trong văn bản.

2. Không suy diễn hoặc bổ sung thông tin pháp luật.

3. Phải giữ nguyên reference đến hành vi vi phạm.

Ví dụ:

"điểm h, điểm i khoản 3"

phải được tách thành:

- clause_id = "3", point_id = "h"
- clause_id = "3", point_id = "i"

Ví dụ:

"điểm a, điểm b, điểm c khoản 4"

phải được tách thành:

- 4.a
- 4.b
- 4.c

Ví dụ:

" khoản 6 "

phải tạo:

- clause_id = "6"
- point_id = null

4. Nếu văn bản nói:

"điểm a khoản 9, khoản 10, điểm đ khoản 11"

phải tạo 3 reference riêng:

- 9.a
- 10
- 11.đ

5. Chỉ xử lý hai loại penalty:

license_points
license_revocation

6. Đối với license_points:

Lưu số điểm bị trừ vào trường "value".

Ví dụ:

"bị trừ điểm giấy phép lái xe 04 điểm"

→

"penalty_type": "license_points",
"value": 4,
"unit": "point"

7. Đối với license_revocation:

Nếu văn bản quy định khoảng thời gian:

"từ 10 tháng đến 12 tháng"

→

"value_min": 10,
"value_max": 12,
"unit": "month"

8. Không đưa các hình thức xử phạt khác như:
- tịch thu thiết bị
- phạt tiền
- cảnh cáo

vào output.

9. Mỗi hành vi vi phạm phải là MỘT record.

10. Nếu một nhóm hành vi cùng chịu một mức phạt,
hãy tạo nhiều record, mỗi record tương ứng với một hành vi.

==================================================
OUTPUT
==================================================

Chỉ trả về JSON array.

Schema:

[
  {
    "article_id": 6,
    "clause_id": "5",
    "point_id": "h",
    "penalty_type": "license_points",
    "value": 4,
    "unit": "point"
  }
]

Đối với tước GPLX:

[
  {
    "article_id": 6,
    "clause_id": "12",
    "point_id": null,
    "penalty_type": "license_revocation",
    "value_min": 10,
    "value_max": 12,
    "unit": "month"
  }
]

Không thêm explanation.
Không thêm markdown.
Không thêm field ngoài schema cần thiết.
"""


# ============================================================
# PARSE JSON
# ============================================================

def parse_json(content: str):

    content = content.strip()

    # Model đôi khi trả ```json ... ```
    if content.startswith("```"):
        content = re.sub(r"^```json\s*", "", content)
        content = re.sub(r"^```\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

    return json.loads(content)


# ============================================================
# EXTRACT ARTICLE ID
# ============================================================

def extract_article_id(filename: str):

    """
    dieu6.md -> 6
    dieu11.md -> 11
    """

    match = re.search(
        r"dieu[_\s-]*(\d+)",
        filename.lower()
    )

    if not match:
        raise ValueError(
            f"Cannot extract article id from {filename}"
        )

    return int(match.group(1))


# ============================================================
# CALL LLM
# ============================================================

def convert_penalty(article_id, law_text):

    user_prompt = f"""
Hãy trích xuất toàn bộ quy định về:

- trừ điểm giấy phép lái xe
- tước quyền sử dụng giấy phép lái xe

trong Điều {article_id} dưới đây.

ARTICLE_ID:
{article_id}

LAW_TEXT:
{law_text}

Hãy tách từng hành vi thành một record riêng.

Chỉ trả về JSON array.
"""

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },
        {
            "role": "user",
            "content": user_prompt
        }
    ]

    result = llm_chat(messages)

    data = parse_json(
        result["content"]
    )

    return data, result.get("provider")


# ============================================================
# VALIDATE
# ============================================================

def validate_records(records, article_id):

    valid_types = {
        "license_points",
        "license_revocation"
    }

    for record in records:

        # Article phải đúng
        record["article_id"] = article_id

        if record["penalty_type"] not in valid_types:
            raise ValueError(
                f"Invalid penalty type: "
                f"{record['penalty_type']}"
            )

        if "clause_id" not in record:
            raise ValueError(
                "Missing clause_id"
            )

        if "point_id" not in record:
            raise ValueError(
                "Missing point_id"
            )

        if record["penalty_type"] == "license_points":

            if "value" not in record:
                raise ValueError(
                    "license_points missing value"
                )

            if record["unit"] != "point":
                raise ValueError(
                    "Invalid unit for license_points"
                )

        elif record["penalty_type"] == "license_revocation":

            if "value_min" not in record:
                raise ValueError(
                    "license_revocation missing value_min"
                )

            if "value_max" not in record:
                raise ValueError(
                    "license_revocation missing value_max"
                )

            if record["unit"] != "month":
                raise ValueError(
                    "Invalid unit for license_revocation"
                )

    return records


# ============================================================
# LOAD EXISTING DB
# ============================================================

def load_existing_db():

    if not OUTPUT_FILE.exists():
        return []

    with open(
        OUTPUT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


def save_db(records):

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            records,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# MAIN
# ============================================================

def main():

    md_files = sorted(
        INPUT_DIR.glob("dieu*.md")
    )

    print(
        f"Found {len(md_files)} article files."
    )

    all_records = load_existing_db()

    processed_articles = {
        r["article_id"]
        for r in all_records
    }

    for idx, file_path in enumerate(md_files):

        article_id = extract_article_id(
            file_path.name
        )

        # Nếu đã chạy trước đó thì bỏ qua
        if article_id in processed_articles:

            print(
                f"[SKIP] Điều {article_id}"
            )

            continue

        print("=" * 70)

        print(
            f"[{idx + 1}/{len(md_files)}] "
            f"Processing Điều {article_id}"
        )

        law_text = file_path.read_text(
            encoding="utf-8"
        )

        try:

            records, provider = convert_penalty(
                article_id,
                law_text
            )

            records = validate_records(
                records,
                article_id
            )

            all_records.extend(
                records
            )

            save_db(
                all_records
            )

            print(
                f"Provider: {provider}"
            )

            print(
                f"Extracted: {len(records)} records"
            )

            print(
                json.dumps(
                    records,
                    ensure_ascii=False,
                    indent=2
                )
            )

        except Exception as e:

            print(
                f"[ERROR] Điều {article_id}: {e}"
            )

        # tránh rate limit
        print(
            f"Sleeping {SLEEP_SECONDS}s..."
        )

        time.sleep(
            SLEEP_SECONDS
        )

    print("=" * 70)

    print(
        f"Done. Total records: "
        f"{len(all_records)}"
    )

    print(
        f"Saved to: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()