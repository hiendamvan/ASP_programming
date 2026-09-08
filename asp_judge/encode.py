# -*- coding: utf-8 -*-
"""
Tầng 2 của ASP judge: rubric + facts đã trích -> ASP facts, rồi gọi Clingo.

Đây là nơi việc PHÁN QUYẾT diễn ra, và nó hoàn toàn tất định: cùng đầu vào
luôn cho cùng kết quả, không phụ thuộc nhiệt độ lấy mẫu hay cách diễn đạt.
"""
from pathlib import Path

import clingo

JUDGE_LP = Path(__file__).resolve().parent / "judge.lp"

# clingo.Control.load() không mở được đường dẫn chứa ký tự ngoài ASCII
# (đường dẫn dự án có "KÌ 8 KLTN"), nên đọc sẵn nội dung rồi dùng add().
_JUDGE_RULES = JUDGE_LP.read_text(encoding="utf-8")


# ============================================================
# rubric (theo từng loại câu hỏi) -> ASP facts
# ============================================================

def rubric_facts(item):
    qtype = item.get("question_type")
    # multihop lưu rubrics dạng list các rule -> chỉ dùng khối `expected`.
    r = item.get("rubrics")
    if not isinstance(r, dict):
        r = {}
    facts = [f"question_type({qtype})."]

    if qtype == "multihop":
        exp = item.get("expected") or {}
        fmin, fmax = exp.get("total_fine_min"), exp.get("total_fine_max")
        pts = exp.get("total_points_deduction")
        revs = exp.get("license_revocations") or []
        penalized = exp.get("expected_penalized", True)

        if revs:
            lo = min(v["value_min"] for v in revs if v.get("value_min"))
            hi = max(v["value_max"] for v in revs if v.get("value_max"))
        else:
            lo = hi = None

    elif qtype == "exception":
        # Câu hỏi ngoại lệ: đáp án đúng là KHÔNG bị xử phạt, nên rubric
        # không có mức phạt nào cả (mức phạt "nếu bị phạt" chỉ để tham chiếu).
        fmin = fmax = pts = lo = hi = None
        penalized = r.get("expected_penalized", False)

    elif qtype == "insufficient":
        # Đáp án đúng là yêu cầu làm rõ, không phải một mức phạt cụ thể.
        fmin = fmax = pts = lo = hi = None
        penalized = None

    else:  # simple
        fmin, fmax = r.get("fine_min"), r.get("fine_max")
        pts = r.get("license_points_deduction")
        rev = r.get("license_revocation") or {}
        lo, hi = rev.get("value_min"), rev.get("value_max")
        penalized = r.get("expected_penalized", True)

    if fmin is not None:
        facts.append(f"rubric_fine(min,{int(fmin)}).")
    if fmax is not None:
        facts.append(f"rubric_fine(max,{int(fmax)}).")
    if pts:
        facts.append(f"rubric_points({int(pts)}).")
    if lo is not None:
        facts.append(f"rubric_revocation(min,{int(lo)}).")
    if hi is not None:
        facts.append(f"rubric_revocation(max,{int(hi)}).")
    if penalized is not None:
        facts.append(f"rubric_penalized({'true' if penalized else 'false'}).")
    if r.get("expected_requires_clarification"):
        facts.append("rubric_requires_clarification.")

    return facts


# ============================================================
# facts đã trích từ câu trả lời -> ASP facts
# ============================================================

def answer_facts(facts):
    out = []

    fmin, fmax = facts.get("fine_min"), facts.get("fine_max")
    if fmin is not None:
        out.append(f"answer_fine(min,{int(fmin)}).")
    if fmax is not None:
        out.append(f"answer_fine(max,{int(fmax)}).")

    pts = facts.get("points_deduction")
    if pts:
        out.append(f"answer_points({int(pts)}).")

    lo, hi = facts.get("revocation_min_months"), facts.get("revocation_max_months")
    if lo is not None:
        out.append(f"answer_revocation(min,{int(lo)}).")
    if hi is not None:
        out.append(f"answer_revocation(max,{int(hi)}).")

    if facts.get("penalized") is not None:
        out.append(f"answer_penalized({'true' if facts['penalized'] else 'false'}).")

    if facts.get("requires_clarification"):
        out.append("answer_requires_clarification.")

    return out


# ============================================================
# Chạy Clingo
# ============================================================

def solve(item, extracted):
    """Trả về (verdict, violations, program) — verdict là 'pass' hoặc 'fail'."""
    program = "\n".join(rubric_facts(item) + answer_facts(extracted))

    ctl = clingo.Control(["--warn=none"])
    ctl.add("base", [], _JUDGE_RULES)
    ctl.add("base", [], program)
    ctl.ground([("base", [])])

    verdict = None
    violations = []

    def on_model(model):
        nonlocal verdict
        for sym in model.symbols(shown=True):
            if sym.name == "verdict":
                verdict = str(sym.arguments[0])
            elif sym.name == "violation":
                violations.append(str(sym.arguments[0]))

    ctl.solve(on_model=on_model)

    return verdict or "pass", sorted(set(violations)), program
