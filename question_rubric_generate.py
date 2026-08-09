import json
import time
from pathlib import Path

from llm import llm_chat


# ============================================================
# 1. Load database
# ============================================================

def load_json(path):

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_law_database(
    points_path="law_db/points.json",
    clauses_path="law_db/clauses.json",
    articles_path="law_db/articles.json"
):

    points = load_json(points_path)
    clauses = load_json(clauses_path)
    articles = load_json(articles_path)

    points_dict = {
        x["point_id"]: x
        for x in points
    }

    clauses_dict = {
        x["clause_id"]: x
        for x in clauses
    }

    articles_dict = {
        x["article_id"]: x
        for x in articles
    }

    return points_dict, clauses_dict, articles_dict


# ============================================================
# 2. Build context cho LLM
# ============================================================

def build_point_context(
    point_id,
    points,
    clauses,
    articles
):

    point = points[point_id]

    clause_id = point["clause_id"]

    clause = clauses[clause_id]

    article_id = clause["article_id"]

    article = articles[article_id]

    return {
        "point_id": point_id,

        "article": {
            "article_id": article["article_id"],
            "title": article["title"]
        },

        "clause": {
            "clause_id": clause["clause_id"],
            "number": clause["number"],
            "intro": clause["intro"]
        },

        "point": {
            "label": point["label"],
            "content": point["content"]
        }
    }


# ============================================================
# 3. Prompt
# ============================================================

with open("prompt/system_prompt.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read().strip()
    print("Loaded system prompt:", SYSTEM_PROMPT[:50], "...")

def generate_simple_question(context):

    article = context["article"]

    clause = context["clause"]

    point = context["point"]

    user_prompt = f"""
Hãy sinh một câu hỏi SIMPLE và rubric từ quy định sau.

ARTICLE:
Điều {article['article_id']}. {article['title']}

CLAUSE:
Khoản {clause['number']}. {clause['intro']}

POINT:
Điểm {point['label']}. {point['content']}

Chỉ trả về JSON theo đúng schema.
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

    content = result["content"].strip()

    # Xử lý trường hợp model trả markdown
    if content.startswith("```"):
        content = content.replace("```json", "")
        content = content.replace("```", "")
        content = content.strip()

    data = json.loads(content)

    return data, result.get("provider")


# ============================================================
# 4. Generate dataset
# ============================================================

def generate_dataset(
    n_samples=100,
    sleep_seconds=10
):

    points, clauses, articles = load_law_database()

    point_ids = list(points.keys())

    # lấy tối đa n samples
    point_ids = point_ids[:n_samples]

    results = []

    output_path = Path("simple_dataset2.json")

    for i, point_id in enumerate(point_ids):

        print("=" * 70)
        print(f"Sample {i + 1}/{len(point_ids)}")
        print(f"Point: {point_id}")

        try:

            context = build_point_context(
                point_id,
                points,
                clauses,
                articles
            )

            data, provider = generate_simple_question(
                context
            )

            sample = {
                "id": i + 1,

                "source": {
                    "point_id": point_id,
                    "clause_id": context["clause"]["clause_id"],
                    "article_id": context["article"]["article_id"]
                },

                "question_type": "simple",

                "question": data["question"],

                "rubrics": data["rubrics"],

                "provider": provider
            }

            results.append(sample)

            # save ngay sau mỗi sample
            with open(
                output_path,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    results,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            print("Question:")
            print(data["question"])

            print("Rubrics:")
            print(json.dumps(
                data["rubrics"],
                ensure_ascii=False,
                indent=2
            ))

        except Exception as e:

            print(f"ERROR: {e}")

        # nghỉ 10 giây
        if i < len(point_ids) - 1:

            print(
                f"Sleeping {sleep_seconds} seconds..."
            )

            time.sleep(sleep_seconds)

    print("=" * 70)
    print(f"Generated: {len(results)} samples")
    print(f"Saved to: {output_path}")


if __name__ == "__main__":

    generate_dataset(
        n_samples=100,
        sleep_seconds=10
    )