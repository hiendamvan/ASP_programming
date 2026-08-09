import json
import re
from pathlib import Path


ARTICLE_RE = re.compile(
    r"\*\*Điều\s+(\d+)\\?\.\s*(.*?)\*\*"
)

CLAUSE_RE = re.compile(
    r"^(\d+)\\?\.\s*(.+)$"
)

POINT_RE = re.compile(
    r"^([a-zđ])\\?\)\s*(.+)$"
)


def parse_file(filepath):

    text = Path(filepath).read_text(
        encoding="utf-8"
    )

    article = ARTICLE_RE.search(text)

    if article is None:
        return [], [], [], []

    article_id = int(article.group(1))
    article_title = article.group(2).strip()

    articles = [
        {
            "article_id": article_id,
            "title": article_title,
        }
    ]

    clauses = []

    points = []

    law_index = []

    current_clause = None
    clause_intro = None

    current_point = None
    point_lines = []

    def save_point():

        nonlocal current_point
        nonlocal point_lines

        if current_point is None:
            return

        point_id = f"{article_id}.{current_clause}.{current_point}"

        content = " ".join(point_lines).strip()

        points.append(
            {
                "point_id": point_id,
                "clause_id": f"{article_id}.{current_clause}",
                "label": current_point,
                "content": content,
            }
        )

        law_index.append(
            {
                "point_id": point_id,
                "article_id": article_id,
                "clause_id": f"{article_id}.{current_clause}",

                # metadata để sau này dùng LLM fill
                "action": None,
                "type": None,
                "has_exception": False,

                "can_generate_simple": True,
                "can_generate_multihop": True,
                "can_generate_exception": False,
                "can_generate_missing": True,
            }
        )

    for raw in text.splitlines():

        line = raw.strip()

        if line == "":
            continue

        clause = CLAUSE_RE.match(line)

        if clause:

            save_point()

            current_point = None
            point_lines = []

            current_clause = int(clause.group(1))
            clause_intro = clause.group(2).strip()

            clauses.append(
                {
                    "clause_id": f"{article_id}.{current_clause}",
                    "article_id": article_id,
                    "number": current_clause,
                    "intro": clause_intro,
                }
            )

            continue

        point = POINT_RE.match(line)

        if point:

            save_point()

            current_point = point.group(1)

            point_lines = [
                point.group(2).strip()
            ]

            continue

        if current_point:

            point_lines.append(line)

    save_point()

    return (
        articles,
        clauses,
        points,
        law_index,
    )


def build_database(folder):

    articles = {}
    clauses = {}
    points = []
    index = []

    folder = Path(folder)

    for md in sorted(folder.glob("*.md")):

        a, c, p, idx = parse_file(md)

        for x in a:
            articles[x["article_id"]] = x

        for x in c:
            clauses[x["clause_id"]] = x

        points.extend(p)
        index.extend(idx)

    output = Path("law_db")

    output.mkdir(exist_ok=True)

    with open(
        output / "articles.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            list(articles.values()),
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open(
        output / "clauses.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            list(clauses.values()),
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open(
        output / "points.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            points,
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open(
        output / "law_index.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            index,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("Done.")
    print(f"Articles : {len(articles)}")
    print(f"Clauses  : {len(clauses)}")
    print(f"Points   : {len(points)}")


if __name__ == "__main__":

    build_database("./source_data/dieus/")