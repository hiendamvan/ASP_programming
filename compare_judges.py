# -*- coding: utf-8 -*-
"""
Giai đoạn 4 — so sánh LLM-as-a-Judge với ASP-as-a-Judge.

Đọc file eval đã được cả hai judge chấm (có gold_verdict, judge_score/judge_verdict,
asp_verdict) và xuất:

  1. Accuracy / Precision / Recall / F1 so với nhãn vàng, TÁCH THEO LOẠI LỖI
     -> bảng kết quả chính của luận văn.
  2. Ma trận nhầm lẫn, nhấn mạnh false accept (chấm pass cho câu sai).
  3. Tính tất định: chạy nhiều lần trên cùng đầu vào, đo tỉ lệ đổi kết quả.
  4. Chi phí & độ trễ: số lời gọi API, giây/mẫu.
  5. Chất lượng giải thích: đếm số lần judge_rationale nêu con số KHÔNG hề
     xuất hiện trong model_answer (lỗi bịa số liệu).

Quy ước: "phát hiện lỗi" là lớp dương (positive = gold_verdict == "fail"),
vì việc ta quan tâm là judge có bắt được câu trả lời sai hay không.
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

PASS_THRESHOLD = 7.0  # điểm >= ngưỡng này thì coi LLM judge kết luận "pass"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# Chuẩn hoá phán quyết
# ============================================================

def llm_verdict(item):
    """LLM judge trả cả `verdict` (chuỗi) lẫn `score` (0-10). Ưu tiên score
    vì nó có ngưỡng rõ ràng; `partial` là trạng thái mập mờ nên quy về score."""
    score = item.get("judge_score")
    if score is not None:
        try:
            return "pass" if float(score) >= PASS_THRESHOLD else "fail"
        except (TypeError, ValueError):
            pass

    v = (item.get("judge_verdict") or "").lower()
    if v == "pass":
        return "pass"
    if v in ("fail", "partial"):
        return "fail"
    return None


def asp_verdict(item):
    return item.get("asp_verdict")


# ============================================================
# Chỉ số
# ============================================================

def prf(items, get_verdict):
    """positive = gold "fail" (câu trả lời sai cần bị bắt)."""
    tp = fp = tn = fn = 0
    skipped = 0

    for it in items:
        gold = it.get("gold_verdict")
        pred = get_verdict(it)
        if pred is None or gold is None:
            skipped += 1
            continue
        if gold == "fail" and pred == "fail":
            tp += 1
        elif gold == "pass" and pred == "fail":
            fp += 1
        elif gold == "pass" and pred == "pass":
            tn += 1
        else:
            fn += 1

    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / total if total else 0.0

    return {
        "n": total, "skipped": skipped,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "accuracy": accuracy, "precision": precision, "recall": recall, "f1": f1,
        # false accept: chấm PASS cho câu SAI — lỗi nguy hiểm nhất của một judge
        "false_accept_rate": fn / (tp + fn) if (tp + fn) else 0.0,
    }


def per_group_recall(items, get_verdict, key):
    """Tỉ lệ bắt đúng theo từng nhóm (loại lỗi hoặc loại câu hỏi)."""
    hit = Counter()
    tot = Counter()
    for it in items:
        gold = it.get("gold_verdict")
        pred = get_verdict(it)
        if pred is None or gold is None:
            continue
        g = it.get(key)
        tot[g] += 1
        if pred == gold:
            hit[g] += 1
    return {g: (hit[g], tot[g]) for g in sorted(tot)}


# ============================================================
# Chất lượng giải thích: phát hiện judge bịa số liệu
# ============================================================

_RE_MONEY = re.compile(r"\b\d{1,3}(?:[.,]\d{3})+\b")


def _numbers_in(text):
    return {m.group(0).replace(",", ".") for m in _RE_MONEY.finditer(text or "")}


def hallucinated_figures(items):
    """Đếm số lần judge_rationale nhắc một số tiền không có trong câu trả lời.

    Đây chính là lỗi đã bắt được ở mẫu simple #1 trong dataset gốc: judge chấm
    4/10 với lý do "câu trả lời đưa ra 200.000-500.000đ", trong khi câu trả lời
    ghi 150.000-250.000đ. ASP judge không thể mắc lỗi này vì mọi con số nó dùng
    đều được trích trực tiếp từ văn bản.
    """
    flagged = []
    checked = 0

    for it in items:
        rationale = it.get("judge_rationale")
        if not rationale:
            continue
        checked += 1

        in_answer = _numbers_in(it.get("model_answer", ""))
        in_rubric = _numbers_in(json.dumps(it.get("rubrics"), ensure_ascii=False))
        in_rationale = _numbers_in(rationale)

        invented = in_rationale - in_answer - in_rubric
        if invented:
            flagged.append({
                "eval_id": it.get("eval_id"),
                "invented": sorted(invented),
                "rationale": rationale[:200],
            })

    return checked, flagged


# ============================================================
# Tính tất định
# ============================================================

def determinism(items, runs_field_prefix):
    """So các lần chạy lặp (vd asp_verdict_run1..3 / judge_verdict_run1..3)."""
    changed = 0
    checked = 0
    for it in items:
        runs = [it[k] for k in sorted(it) if k.startswith(runs_field_prefix)]
        if len(runs) < 2:
            continue
        checked += 1
        if len(set(runs)) > 1:
            changed += 1
    if not checked:
        return None
    return {"n": checked, "changed": changed, "rate": changed / checked}


# ============================================================
# Xuất báo cáo
# ============================================================

def fmt_pct(x):
    return f"{100 * x:5.1f}%"


def md_table(rows, headers):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def main(input_file, output_json, output_md):
    items = load_json(input_file)

    has_llm = any(llm_verdict(it) is not None for it in items)
    has_asp = any(asp_verdict(it) is not None for it in items)

    if not has_asp:
        print("[CẢNH BÁO] chưa có asp_verdict — chạy asp_judge/run.py trước")
    if not has_llm:
        print("[CẢNH BÁO] chưa có judge_score — chạy llm_judge.py trước")

    report = {"input": str(input_file), "n_samples": len(items)}
    lines = ["# So sánh LLM-as-a-Judge và ASP-as-a-Judge", ""]
    lines.append(f"Tập đánh giá: `{input_file}` — {len(items)} mẫu, "
                 f"nhãn vàng sinh bằng tiêm lỗi có kiểm soát.")
    lines.append("")

    # ---- 1. chỉ số tổng ----
    overall = {}
    if has_llm:
        overall["llm"] = prf(items, llm_verdict)
    if has_asp:
        overall["asp"] = prf(items, asp_verdict)
    report["overall"] = overall

    lines.append("## 1. Chỉ số tổng (lớp dương = câu trả lời SAI)")
    lines.append("")
    rows = []
    for name, key in (("LLM judge", "llm"), ("ASP judge", "asp")):
        if key not in overall:
            continue
        m = overall[key]
        rows.append([name, m["n"], fmt_pct(m["accuracy"]), fmt_pct(m["precision"]),
                     fmt_pct(m["recall"]), fmt_pct(m["f1"]),
                     fmt_pct(m["false_accept_rate"])])
    lines.append(md_table(rows, ["Judge", "N", "Accuracy", "Precision", "Recall",
                                 "F1", "Bỏ lọt câu sai"]))
    lines.append("")

    # ---- 2. tách theo loại lỗi ----
    lines.append("## 2. Độ chính xác theo từng loại lỗi tiêm vào")
    lines.append("")
    groups = sorted({it.get("perturbation_type") for it in items if it.get("perturbation_type")})
    llm_g = per_group_recall(items, llm_verdict, "perturbation_type") if has_llm else {}
    asp_g = per_group_recall(items, asp_verdict, "perturbation_type") if has_asp else {}

    rows = []
    for g in groups:
        lh, lt = llm_g.get(g, (0, 0))
        ah, at = asp_g.get(g, (0, 0))
        rows.append([
            g,
            f"{lh}/{lt}" + (f" ({fmt_pct(lh / lt).strip()})" if lt else ""),
            f"{ah}/{at}" + (f" ({fmt_pct(ah / at).strip()})" if at else ""),
        ])
    lines.append(md_table(rows, ["Loại lỗi", "LLM judge đúng", "ASP judge đúng"]))
    lines.append("")
    report["per_perturbation"] = {"llm": llm_g, "asp": asp_g}

    # ---- 3. tách theo loại câu hỏi ----
    lines.append("## 3. Độ chính xác theo loại câu hỏi")
    lines.append("")
    llm_q = per_group_recall(items, llm_verdict, "question_type") if has_llm else {}
    asp_q = per_group_recall(items, asp_verdict, "question_type") if has_asp else {}
    rows = []
    for g in sorted({it.get("question_type") for it in items}):
        lh, lt = llm_q.get(g, (0, 0))
        ah, at = asp_q.get(g, (0, 0))
        rows.append([
            g,
            f"{lh}/{lt}" + (f" ({fmt_pct(lh / lt).strip()})" if lt else ""),
            f"{ah}/{at}" + (f" ({fmt_pct(ah / at).strip()})" if at else ""),
        ])
    lines.append(md_table(rows, ["Loại câu hỏi", "LLM judge đúng", "ASP judge đúng"]))
    lines.append("")
    report["per_question_type"] = {"llm": llm_q, "asp": asp_q}

    # ---- 4. bịa số liệu ----
    checked, flagged = hallucinated_figures(items)
    report["hallucinated_figures"] = {"checked": checked, "flagged": len(flagged),
                                      "examples": flagged[:10]}
    lines.append("## 4. LLM judge bịa số liệu trong phần giải thích")
    lines.append("")
    if checked:
        lines.append(f"Đã kiểm tra {checked} phần `judge_rationale`; "
                     f"**{len(flagged)}** trong số đó nhắc tới một số tiền "
                     f"không hề xuất hiện trong câu trả lời lẫn rubric "
                     f"({fmt_pct(len(flagged) / checked).strip()}).")
        lines.append("")
        lines.append("ASP judge không thể mắc lỗi này: mọi con số nó dùng đều "
                     "được trích trực tiếp từ văn bản và ghi lại trong `asp_facts`.")
        for f in flagged[:5]:
            lines.append(f"- `{f['eval_id']}`: bịa {f['invented']} — "
                         f"\"{f['rationale'][:120]}...\"")
    else:
        lines.append("_Chưa có judge_rationale nào để kiểm tra._")
    lines.append("")

    # ---- 5. tất định ----
    lines.append("## 5. Tính tất định (chạy lặp trên cùng đầu vào)")
    lines.append("")
    det_llm = determinism(items, "judge_verdict_run")
    det_asp = determinism(items, "asp_verdict_run")
    report["determinism"] = {"llm": det_llm, "asp": det_asp}
    if det_llm or det_asp:
        rows = []
        if det_llm:
            rows.append(["LLM judge", det_llm["n"], det_llm["changed"],
                         fmt_pct(det_llm["rate"])])
        if det_asp:
            rows.append(["ASP judge", det_asp["n"], det_asp["changed"],
                         fmt_pct(det_asp["rate"])])
        lines.append(md_table(rows, ["Judge", "Mẫu", "Đổi kết quả", "Tỉ lệ"]))
    else:
        lines.append("_Chưa chạy lặp. Đo bằng:_ "
                     "`python determinism_check.py eval_set/judged.json --samples 30 --runs 3`")
        lines.append("")
        lines.append("ASP judge tất định theo thiết kế: Clingo cho cùng một mô hình "
                     "ổn định với cùng tập fact, nên tỉ lệ này luôn bằng 0%.")
    lines.append("")

    # ---- 6. chi phí ----
    lines.append("## 6. Chi phí và độ trễ")
    lines.append("")
    asp_lat = [it["asp_latency"] for it in items if it.get("asp_latency") is not None]
    extract_by = Counter(it.get("asp_extract_by") for it in items if it.get("asp_extract_by"))
    n_llm_judged = sum(1 for it in items if it.get("judge_score") is not None)
    # Chỉ đếm lần trích BẰNG LLM thành công. 'regex-fallback' là lúc API lỗi
    # và đã rơi về regex -> không tính là một lời gọi hữu ích.
    n_asp_api = extract_by.get("llm", 0)

    report["cost"] = {
        "llm_judge_api_calls": n_llm_judged,
        "asp_extract_api_calls": n_asp_api,
        "asp_solve_seconds_total": sum(asp_lat),
        "asp_extract_method": dict(extract_by),
    }
    rows = [
        ["LLM judge", n_llm_judged, "—",
         "mỗi mẫu 1 lời gọi, toàn bộ phán quyết do LLM quyết"],
        [f"ASP judge (trích: {dict(extract_by)})", n_asp_api,
         f"{sum(asp_lat) * 1000 / max(len(asp_lat), 1):.2f} ms/mẫu",
         "LLM chỉ trích facts; phán quyết do Clingo, chi phí 0 đồng"],
    ]
    lines.append(md_table(rows, ["Judge", "Lời gọi API", "Thời gian suy diễn",
                                 "Ghi chú"]))
    lines.append("")

    # ---- 7. bất đồng ----
    disagree = [it for it in items
                if has_llm and has_asp and llm_verdict(it) != asp_verdict(it)]
    report["disagreements"] = len(disagree)
    lines.append("## 7. Các mẫu hai judge bất đồng")
    lines.append("")
    lines.append(f"Tổng cộng **{len(disagree)}** mẫu. Trong đó, số mẫu ASP đúng "
                 f"còn LLM sai: **{sum(1 for it in disagree if asp_verdict(it) == it.get('gold_verdict'))}**; "
                 f"ngược lại: **{sum(1 for it in disagree if llm_verdict(it) == it.get('gold_verdict'))}**.")
    lines.append("")
    for it in disagree[:10]:
        lines.append(f"- `{it.get('eval_id')}` (vàng={it.get('gold_verdict')}): "
                     f"LLM={llm_verdict(it)}, ASP={asp_verdict(it)} "
                     f"{it.get('asp_violations') or ''}")
    lines.append("")

    save_json(report, output_json)
    Path(output_md).parent.mkdir(parents=True, exist_ok=True)
    Path(output_md).write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\nĐã lưu: {output_json}\nĐã lưu: {output_md}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="So sánh LLM judge và ASP judge")
    p.add_argument("input_file", help="File eval đã được cả hai judge chấm")
    p.add_argument("--out-json", default="eval_results/comparison.json")
    p.add_argument("--out-md", default="eval_results/comparison.md")
    a = p.parse_args()
    main(a.input_file, a.out_json, a.out_md)
