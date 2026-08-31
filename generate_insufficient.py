import argparse
import json
import re
import time
from pathlib import Path

from llm import llm_chat


# ============================================================
# CONFIG
# ============================================================

POINTS_FILE = Path("law_db/points.json")
CLAUSES_FILE = Path("law_db/clauses.json")
ARTICLES_FILE = Path("law_db/articles.json")
PENALTY_FILE = Path("law_db/penalty_db.json")

OUTPUT_DIR = Path("output_generate")

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
# BUILD INDEXES
# ============================================================

def build_clause_index(clauses):
    return {c["clause_id"]: c for c in clauses}


def build_article_index(articles):
    return {a["article_id"]: a for a in articles}


def build_penalty_index(penalties):
    index = {}

    for p in penalties:
        article_id = p["article_id"]
        clause_id = str(p["clause_id"])
        point_id = p.get("point_id")

        key = (article_id, clause_id, point_id)
        index.setdefault(key, []).append(p)

    return index


# ============================================================
# EXTRACT FINE FROM CLAUSE INTRO
# ============================================================

def extract_fine(intro):
    if not intro:
        return None, None

    pattern = re.compile(
        r"phạt\s+tiền\s+từ\s+"
        r"([\d\.,]+)\s*đồng"
        r"\s+đến\s+"
        r"([\d\.,]+)\s*đồng",
        re.IGNORECASE,
    )

    match = pattern.search(intro)

    if match:
        fine_min = int(match.group(1).replace(".", ""))
        fine_max = int(match.group(2).replace(".", ""))
        return fine_min, fine_max

    pattern_single = re.compile(
        r"phạt\s+tiền\s+([\d\.,]+)\s*đồng",
        re.IGNORECASE,
    )

    match = pattern_single.search(intro)

    if match:
        value = int(match.group(1).replace(".", ""))
        return value, value

    return None, None


# ============================================================
# GET PENALTIES FOR A POINT
# ============================================================

def get_penalties(penalty_index, article_id, clause_number, point_label):
    results = []

    point_key = (article_id, str(clause_number), point_label)
    results.extend(penalty_index.get(point_key, []))

    clause_key = (article_id, str(clause_number), None)
    results.extend(penalty_index.get(clause_key, []))

    return results


# ============================================================
# BUILD RUBRIC FROM DB
# ============================================================

def build_rubric(clause, penalty_index, article_id, clause_number,
                  point_label, missing_info):
    fine_min, fine_max = extract_fine(clause.get("intro", ""))

    penalties = get_penalties(
        penalty_index, article_id, clause_number, point_label
    )

    license_points_deduction = None
    license_revocation = None
    additional_penalties = []

    for p in penalties:
        if p["penalty_type"] == "license_points":
            license_points_deduction = p["value"]

        elif p["penalty_type"] == "license_revocation":
            license_revocation = {
                "value_min": p.get("value_min"),
                "value_max": p.get("value_max"),
                "unit": p.get("unit"),
            }

        else:
            additional_penalties.append({
                "penalty_type": p["penalty_type"],
                "value": p.get("value"),
                "value_min": p.get("value_min"),
                "value_max": p.get("value_max"),
                "unit": p.get("unit"),
            })

    return {
        "fine_min": fine_min,
        "fine_max": fine_max,
        "license_points_deduction": license_points_deduction,
        "license_revocation": license_revocation,
        "additional_penalties": additional_penalties,
        "requires_clarification": True,
        "missing_info": missing_info,
        "note": (
            "Câu trả lời đúng cần chỉ ra rằng thông tin hiện tại chưa đủ "
            "để kết luận chính xác mức xử phạt, và cần làm rõ thêm: "
            f"{missing_info}"
        ),
    }


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
Bạn là chuyên gia pháp luật giao thông Việt Nam và chuyên xây dựng
dataset benchmark cho bài toán đánh giá câu trả lời pháp luật.

Nhiệm vụ:
Dựa trên MỘT điểm luật (Point) được cung cấp, hãy sinh ra
một câu hỏi dạng INSUFFICIENT INFO (thiếu thông tin) có tính tình huống.

Câu hỏi dạng này mô tả một tình huống liên quan đến hành vi vi phạm
trong Point, nhưng CỐ Ý bỏ qua một chi tiết định lượng hoặc điều kiện
then chốt của Point, khiến người trả lời KHÔNG THỂ kết luận chính xác
mức xử phạt nếu chỉ dựa vào thông tin đã cho trong câu hỏi.

==================================================
I. QUY TẮC SINH CÂU HỎI
==================================================

1. Chỉ sử dụng thông tin có trong ARTICLE, CLAUSE và POINT.

2. Không được thêm bất kỳ quy định pháp luật, mức phạt hoặc
   số điểm GPLX nào không xuất hiện trong input.

3. Trước tiên, xác định trong nội dung Point một chi tiết định lượng
   hoặc điều kiện then chốt (ví dụ: tốc độ vượt quá bao nhiêu km/h,
   nồng độ cồn, khoảng cách, thời gian, số lần vi phạm, loại giấy tờ
   cụ thể, mức độ thương tích...) mà nếu không biết chi tiết đó thì
   KHÔNG THỂ xác định chính xác mức xử phạt áp dụng.

4. Xây dựng một tình huống thực tế có chủ thể, phương tiện và bối cảnh
   phù hợp với hành vi trong Point, nhưng KHÔNG đề cập đến chi tiết
   định lượng/điều kiện then chốt đã xác định ở bước 3.

5. Không biến câu hỏi thành Multihop hoặc Exception.
   Câu hỏi vẫn chỉ xoay quanh MỘT hành vi vi phạm chính được quy định
   tại Point, chỉ khác là thiếu dữ kiện cần thiết để kết luận. Không
   Lấy các trường hợp loại trừ theo điểm không rõ ràng (ví dụ trừ điểm 
   B, trừ hành vi tại điểm a khoản 2 Điều này.)

6. Không được đưa mức phạt, số điểm GPLX, chi tiết định lượng còn thiếu,
   hoặc bất kỳ kết luận pháp lý nào vào phần câu hỏi.

7. Câu hỏi phải kết thúc bằng yêu cầu xác định mức xử phạt theo quy định
   pháp luật, giống như câu hỏi thông thường, để người trả lời buộc phải
   tự nhận ra rằng thông tin chưa đủ để trả lời chính xác.

==================================================
II. ĐỘ PHỨC TẠP
==================================================

Câu hỏi phải đủ tự nhiên để không lộ rõ ngay là "thiếu thông tin",
nhưng khi phân tích kỹ thì chi tiết định lượng/điều kiện then chốt
của Point rõ ràng không xuất hiện.

Ví dụ không tốt (lộ rõ và không có tình huống):

"Vượt quá tốc độ quy định thì bị phạt bao nhiêu?"

Ví dụ tốt:

"Anh B điều khiển xe ô tô lưu thông trên đường và bị lực lượng chức
năng phát hiện đang chạy với tốc độ nhanh hơn tốc độ tối đa cho phép
trên đoạn đường đó. Theo quy định pháp luật hiện hành, hành vi của
anh B bị xử phạt như thế nào?"

(Ở đây, mức tốc độ vượt quá cụ thể — yếu tố quyết định để xác định
đúng mức phạt — đã không được nêu ra.)

Câu hỏi tốt cần:
- có một tình huống;
- xác định rõ chủ thể;
- xác định loại phương tiện;
- mô tả hành vi vi phạm nhưng thiếu đúng MỘT chi tiết then chốt;
- cuối cùng yêu cầu xác định mức xử phạt.

==================================================
III. OUTPUT
==================================================

Chỉ trả về JSON hợp lệ.

Schema:

{
    "question": "...",
    "missing_info": "..."
}

Trong đó:
- "question": câu hỏi tình huống thiếu thông tin.
- "missing_info": mô tả ngắn gọn (1 câu) chi tiết định lượng/điều kiện
  còn thiếu, cần được làm rõ để xác định chính xác mức xử phạt.

Không thêm field khác.
Không giải thích.
Không sử dụng Markdown.
"""


# ============================================================
# GENERATE QUESTION VIA LLM
# ============================================================

def generate_question(point, clause, article):
    user_prompt = f"""
Hãy sinh một câu hỏi INSUFFICIENT INFO từ quy định sau.

ARTICLE:
Điều {article['article_id']}. {article['title']}

CLAUSE:
Khoản {clause['number']}. {clause['intro']}

POINT:
Điểm {point['label']}. {point['content']}

Chỉ trả về JSON theo đúng schema.
"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    result = llm_chat(messages)

    content = result["content"].strip()

    if content.startswith("```"):
        content = content.replace("```json", "")
        content = content.replace("```", "")
        content = content.strip()

    data = json.loads(content)

    return data["question"], data["missing_info"], result.get("provider")


# ============================================================
# GENERATE DATASET
# ============================================================

def generate_dataset(start_index, end_index):
    points = load_json(POINTS_FILE)
    clauses = load_json(CLAUSES_FILE)
    articles = load_json(ARTICLES_FILE)
    penalties = load_json(PENALTY_FILE)

    clause_index = build_clause_index(clauses)
    article_index = build_article_index(articles)
    penalty_index = build_penalty_index(penalties)

    output_file = OUTPUT_DIR / f"insufficient_{start_index}_{end_index}.json"

    if output_file.exists():
        try:
            dataset = load_json(output_file)
        except Exception:
            dataset = []
    else:
        dataset = []

    existing_ids = {
        s["source"]["point_id"]
        for s in dataset
        if "source" in s
    }

    total_points = len(points)
    start = max(0, start_index - 1)
    end = min(total_points, end_index)
    selected_points = points[start:end]

    print(f"Total points in DB: {total_points}")
    print(f"Range: {start_index} - {end_index} ({len(selected_points)} points)")
    print(f"Output: {output_file}")
    print(f"Existing samples in file: {len(dataset)}")

    generated_count = 0

    for i, point in enumerate(selected_points):

        point_id = point["point_id"]

        if point_id in existing_ids:
            print(f"[SKIP] Already exists: {point_id}")
            continue

        clause_id = point["clause_id"]
        article_id = int(point_id.split(".")[0])
        clause_number = clause_id.split(".")[-1]

        clause = clause_index.get(clause_id)
        article = article_index.get(article_id)

        if clause is None or article is None:
            print(f"[SKIP] Missing clause/article for {point_id}")
            continue

        print("\n" + "=" * 70)
        print(f"[Point {start + i + 1}/{total_points}] {point_id}")
        print(f"Content: {point['content'][:80]}...")

        try:
            question, missing_info, provider = generate_question(
                point, clause, article
            )

            rubric = build_rubric(
                clause, penalty_index,
                article_id, clause_number, point["label"],
                missing_info,
            )

            sample = {
                "id": len(dataset) + 1,
                "source": {
                    "point_id": point_id,
                    "clause_id": clause_id,
                    "article_id": article_id,
                },
                "question_type": "insufficient",
                "question": question,
                "rubrics": rubric,
                "provider": provider,
            }

            dataset.append(sample)
            existing_ids.add(point_id)
            save_json(dataset, output_file)
            generated_count += 1

            print(f"Provider: {provider}")
            print(f"Question: {question}")
            print(f"Missing info: {missing_info}")
            print(f"Rubric: {json.dumps(rubric, ensure_ascii=False)}")

        except Exception as e:
            print(f"[ERROR] {type(e).__name__}: {e}")

        if i < len(selected_points) - 1:
            print(f"Sleeping {SLEEP_SECONDS}s...")
            time.sleep(SLEEP_SECONDS)

    print("\n" + "=" * 70)
    print(f"DONE. Generated {generated_count} new samples this run")
    print(f"Total samples in file: {len(dataset)}")
    print(f"Output: {output_file}")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate insufficient-info questions from points.json"
    )
    parser.add_argument(
        "start", type=int,
        help="Start index (1-based, inclusive)",
    )
    parser.add_argument(
        "end", type=int,
        help="End index (1-based, inclusive)",
    )
    args = parser.parse_args()

    generate_dataset(args.start, args.end)