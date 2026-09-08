# -*- coding: utf-8 -*-
"""
Lớp tra cứu luật dùng chung cho các script sửa rubric.

KHÔNG viết lại logic parse — tái sử dụng trực tiếp các hàm đã có trong
`post_process/multihop.py` (extract_fine, build_clause_index,
build_penalty_index, get_clause_fine, get_penalties, build_rubric).
Module này chỉ lo phần import path và các helper còn thiếu.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "post_process"))

# Tái sử dụng nguyên vẹn từ post_process/multihop.py
from multihop import (            # noqa: E402
    extract_fine,
    normalize_clause_id,
    build_clause_index,
    build_penalty_index,
    get_clause_fine,
    get_penalties,
    build_rubric,
)

LAW_DB = ROOT / "law_db"
OUTPUT_GENERATE = ROOT / "output_generate"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_law_db():
    """Trả về (clause_index, penalty_index, clause_by_id, point_by_id)."""
    clauses = load_json(LAW_DB / "clauses.json")
    penalties = load_json(LAW_DB / "penalty_db.json")
    points = load_json(LAW_DB / "points.json")

    return (
        build_clause_index(clauses),
        build_penalty_index(penalties),
        {c["clause_id"]: c for c in clauses},
        {p["point_id"]: p for p in points},
    )


def clause_id_of(article_id, clause_id):
    """'7' + '1' -> '7.1';  '7' + '7.1' -> '7.1'."""
    return f"{int(article_id)}.{normalize_clause_id(clause_id)}"


def full_point_id(article_id, clause_id, point_label):
    return f"{clause_id_of(article_id, clause_id)}.{point_label}"


# ============================================================
# Fallback: trích hình phạt bổ sung từ CHÍNH nội dung điểm luật
# ============================================================
# penalty_db.json chỉ có 149 entry và bỏ sót nhiều điểm (vd 7.13.a).
# Nhưng nội dung điểm thường tự nêu rõ: "... bị trừ điểm giấy phép lái xe
# 02 điểm". Parse trực tiếp để bù coverage.

import re  # noqa: E402

_RE_POINTS = re.compile(
    r"tr[ừu]\s+đi[ểe]m\s+gi[ấa]y\s+ph[ée]p\s+l[áa]i\s+xe\s+(\d+)\s*đi[ểe]m",
    re.IGNORECASE,
)

_RE_REVOCATION = re.compile(
    r"t[ưu][ớo]c\s+quy[ềe]n\s+s[ửu]\s+d[ụu]ng\s+gi[ấa]y\s+ph[ée]p\s+l[áa]i\s+xe"
    r"\s+t[ừu]\s+(\d+)\s*th[áa]ng\s+đ[ếe]n\s+(\d+)\s*th[áa]ng",
    re.IGNORECASE,
)


def parse_point_penalty(content):
    """Trả về {'license_points': int|None, 'license_revocation': dict|None}."""
    if not content:
        return {"license_points": None, "license_revocation": None}

    pts = None
    m = _RE_POINTS.search(content)
    if m:
        pts = int(m.group(1))

    rev = None
    m = _RE_REVOCATION.search(content)
    if m:
        rev = {
            "value_min": int(m.group(1)),
            "value_max": int(m.group(2)),
            "unit": "month",
        }

    return {"license_points": pts, "license_revocation": rev}
