# -*- coding: utf-8 -*-
"""
Pipeline LLM-as-a-Judge cho benchmark câu hỏi luật giao thông VN.

Mỗi sample (đã có `model_answer`) được chấm bởi một LLM judge dựa trên
rubric chuẩn của loại câu hỏi tương ứng. Kết quả được ghi THÊM các field
vào chính sample trong file gốc:

    judge_vendor     -> provider thực tế đã gọi (groq / openrouter / ...)
    judge_model      -> model id chính xác đã dùng để judge
    judge_score      -> điểm tổng (float, thang 0-10)
    judge_rationale  -> lý luận chấm điểm
    judge_detail     -> (optional) chi tiết từng tiêu chí

Hỗ trợ 4 loại:
    - simple:      rubric dict {fine_min, fine_max, license_points_deduction,
                                license_revocation, additional_penalties}
    - exception:   rubric gồm normal_action + exception (hành vi + ngoại lệ)
    - multihop:    rubric list [R1, R2, R3=combined_conclusion]
    - insufficient:rubric dict {requires_clarification, missing_info, note}

Tương tự generate_answer.py: ghi đè file gốc sau MỖI sample (resume-aware).
"""
import argparse
import json
import time
from pathlib import Path

from llm import llm_chat

SLEEP_SECONDS = 2

# llm_chat() chỉ trả về provider, không trả model id -> judge_model luôn None.
# Map lại theo model đang cấu hình trong llm.py.
MODEL_BY_PROVIDER = {
    "groq": "openai/gpt-oss-120b",
    "openrouter": "openai/gpt-oss-120b",
}


# ============================================================
# IO
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
# SYSTEM PROMPT (dùng chung, yêu cầu trả JSON thuần)
# ============================================================

JUDGE_SYSTEM_PROMPT = """\
Bạn là một giám khảo (judge) chuyên chấm điểm câu trả lời của một mô hình AI \
về xử phạt vi phạm hành chính giao thông đường bộ Việt Nam (Nghị định 168/2024/NĐ-CP).

Bạn nhận được: một câu hỏi tình huống, rubric đáp án chuẩn, và câu trả lời của mô hình.
Hãy chấm điểm câu trả lời theo rubric một cách khách quan, công bằng, nghiêm khắc.

THANG ĐIỂM: điểm số tổng trong khoảng 0 đến 10, dùng số thập phân nếu cần.

NGUYÊN TẮC CHẤM:
- Câu trả lời đúng đầy đủ, khớp mọi yếu tố quan trọng của rubric: 9-10 điểm.
- Đúng hướng nhưng thiếu một chi tiết hình phạt hoặc diễn đạt không chính xác: 6-8 điểm.
- Trả lời có phần đúng nhưng sai lệch mức phạt / bỏ sót hình phạt chính: 3-5 điểm.
- Sai cơ bản hoặc trả lời không liên quan: 0-2 điểm.
- Nếu rubric yêu cầu làm rõ thông tin (insufficient) nhưng mô hình trả lời khẳng định
  chắc chắn, đây là lỗi nghiêm trọng, chấm thấp.
- Không được phóng đại điểm vì mô hình viết dài; chỉ dựa vào tính đúng/sai của nội dung.

CHỈ XUẤT RA MỘT ĐỐI TƯỢNG JSON HỢP LỆ, DẠNG:
{
  "score": <số từ 0 đến 10>,
  "rationale": "lý luận ngắn gọn, nêu ưu khuyết điểm, bằng tiếng Việt",
  "detail": {
    "tiêu_chí_1": "đánh giá ngắn",
    "tiêu_chí_2": "đánh giá ngắn"
  },
  "verdict": "pass"  | "fail" | "partial"
}
KHÔNG thêm bất kỳ văn bản nào ngoài JSON. KHÔNG dùng markdown fence.
"""


# ============================================================
# Prompt builder theo loại câu hỏi
# ============================================================

def _fmt_penalty(rubric):
    parts = []

    fine = rubric.get("fine_min")
    fine_max = rubric.get("fine_max")
    if fine is not None or fine_max is not None:
        if fine is not None and fine_max is not None and fine == fine_max:
            parts.append(f"- Phạt tiền: {fine:,.0f} đồng".replace(",", "."))
        elif fine is not None and fine_max is not None:
            parts.append(
                f"- Phạt tiền: {fine:,.0f} - {fine_max:,.0f} đồng".replace(",", ".")
            )
        elif fine is not None:
            parts.append(f"- Phạt tiền: {fine:,.0f} đồng".replace(",", "."))
        else:
            parts.append(f"- Phạt tiền: lên đến {fine_max:,.0f} đồng".replace(",", "."))

    pts = rubric.get("license_points_deduction")
    if pts is not None:
        parts.append(f"- Trừ điểm GPLX: {pts} điểm")

    rev = rubric.get("license_revocation")
    if isinstance(rev, dict):
        if rev.get("min") or rev.get("max"):
            if rev.get("min") and rev.get("max") and rev["min"] == rev["max"]:
                parts.append(f"- Tước GPLX: {rev['min']} tháng")
            else:
                parts.append(
                    f"- Tước GPLX: {rev.get('min')}–{rev.get('max')} tháng"
                    if rev.get("min")
                    else f"- Tước GPLX: tối đa {rev.get('max')} tháng"
                )
    elif rev:
        parts.append(f"- Tước GPLX: {rev}")

    add = rubric.get("additional_penalties")
    if isinstance(add, list) and add:
        parts.append(f"- Xử phạt bổ sung: {', '.join(str(p) for p in add)}")
    elif isinstance(add, str) and add:
        parts.append(f"- Xử phạt bổ sung: {add}")

    if not parts:
        return "(rubric không có hình phạt tiền/trừ điểm/tước bằng nào đáng kể)"

    return "\n".join(parts)


def build_judge_message(item):
    qtype = item.get("question_type")
    question = item.get("question", "")
    answer = item.get("model_answer", "")

    if qtype == "simple":
        rubric = _fmt_penalty(item.get("rubrics") or item)
        rubric_block = f"CÁC TIÊU CHÍ RUBRIC:\n{rubric}"

    elif qtype == "exception":
        rubrics = item.get("rubrics")
        if isinstance(rubrics, dict):
            normal = rubrics.get("normal_action", item.get("normal_action", ""))
            exc = rubrics.get("exception", item.get("exception", ""))
        else:
            normal = item.get("normal_action", "")
            exc = item.get("exception", "")
        rubric_block = (
            f"CÁC TIÊU CHÍ RUBRIC:\n"
            f"- Hành vi vi phạm chuẩn: {normal}\n"
            f"- Trường hợp ngoại lệ/loại trừ: {exc}"
        )

    elif qtype == "multihop":
        rubrics = item.get("rubrics", [])
        rows = []
        for r in rubrics:
            if isinstance(r, dict):
                rid = r.get("rule_id", "?")
                action = r.get("action", "")
                if r.get("fine_min") or r.get("fine_max"):
                    action = f"{action} [phạt: {r.get('fine_min')}-{r.get('fine_max')}]"
                rows.append(f"- {rid}: {action}")
        rubric_block = (
            "CÁC TIÊU CHÍ RUBRIC (câu hỏi kết hợp nhiều hành vi, đánh giá từng "
            "rubric R1, R2 rồi R3/combined_conclusion):\n"
            + "\n".join(rows)
        )

    elif qtype == "insufficient":
        rubrics = item.get("rubrics") or {}
        rubric_block = (
            f"CÁC TIÊU CHÍ RUBRIC:\n"
            f"- requires_clarification: {rubrics.get('requires_clarification')}\n"
            f"- missing_info: {rubrics.get('missing_info', '')}\n"
            f"- note: {rubrics.get('note', '')}\n"
            f"\nLƯU Ý: Đây là câu hỏi thiếu thông tin. Một câu trả lời ĐÚNG phải nhận "
            f"ra thông tin chưa đủ để kết luận và nêu rõ cần làm rõ điều gì, "
            f"thay vì khẳng định một mức phạt cụ thể."
        )

    else:
        rubric_block = f"CÁC TIÊU CHÍ RUBRIC:\n{json.dumps(item.get('rubrics'), ensure_ascii=False)}"

    user_prompt = (
        "=== CÂU HỎI ===\n"
        f"{question}\n\n"
        f"{rubric_block}\n\n"
        "=== CÂU TRẢ LỜI CỦA MÔ HÌNH ===\n"
        f"{answer}\n\n"
        "Hãy chấm điểm theo các tiêu chí rubric nêu trên và trả về JSON như quy định."
    )

    return [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def parse_llm_json(text):
    """Bóc JSON thuần từ output LLM (bỏ markdown fence nếu có)."""
    text = text.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    return json.loads(text)


# ============================================================
# Judge một sample
# ============================================================

def judge_item(item, provider_name=None):
    messages = build_judge_message(item)

    # llm_chat() nhận `provider` (tên nhà cung cấp), KHÔNG nhận `model`.
    # Trước đây truyền model= gây TypeError -> cờ --model hoàn toàn không dùng được.
    kwargs = {}
    if provider_name:
        kwargs["provider"] = provider_name

    result = llm_chat(messages, **kwargs)

    provider = result.get("provider")
    model_used = result.get("model") or MODEL_BY_PROVIDER.get(provider)

    try:
        verdict = parse_llm_json(result["content"])
    except json.JSONDecodeError as e:
        verdict = {"score": 0, "rationale": f"LLM judge trả về JSON không hợp lệ: {e}"}

    score = verdict.get("score", 0)

    item["judge_vendor"] = provider
    item["judge_model"] = model_used
    item["judge_score"] = score
    item["judge_rationale"] = verdict.get("rationale", "")
    if "detail" in verdict:
        item["judge_detail"] = verdict["detail"]
    if "verdict" in verdict:
        item["judge_verdict"] = verdict["verdict"]

    return provider, model_used, score


# ============================================================
# Driver
# ============================================================

def judge_dataset(input_file, start_index=1, end_index=None, provider_name=None,
                  force=False):
    input_path = Path(input_file)
    dataset = load_json(input_path)

    total = len(dataset)
    start = max(0, start_index - 1)
    end = total if end_index is None else min(total, end_index)

    print(f"Input: {input_path}")
    print(f"Total samples in file: {total}")
    print(f"Range: {start_index} - {end if end_index else total}")
    print(f"Judge provider (requested): {provider_name or 'auto-failover'}")

    judged_count = 0

    for i in range(start, end):
        item = dataset[i]

        if "question" not in item:
            print(f"[SKIP] No 'question' field at index {i}")
            continue

        if not force and item.get("judge_score") is not None:
            print(f"[SKIP] Already judged at index {i}")
            continue

        print("\n" + "=" * 70)
        print(f"[Item {i+1}/{total}] type={item.get('question_type', 'unknown')}")
        print(f"Question: {item['question'][:100]}...")

        try:
            vendor, model_used, score = judge_item(item, provider_name=provider_name)
            save_json(dataset, input_path)
            judged_count += 1

            print(f"[JUDGE] vendor={vendor} model={model_used} score={score}")
            print(f"[JUDGE] rationale: {item['judge_rationale'][:200]}")

        except Exception as e:
            print(f"[ERROR] {type(e).__name__}: {e}")

        if i < end - 1:
            print(f"Sleeping {SLEEP_SECONDS}s...")
            time.sleep(SLEEP_SECONDS)

    print("\n" + "=" * 70)
    print(f"DONE. Judged {judged_count} samples this run")
    print(f"Total samples in file: {total}")
    print(f"Judge model (final, khi có data): xem field judge_model từng sample")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="LLM-as-a-judge: chấm model_answer theo rubric, ghi field vào file gốc."
    )
    parser.add_argument("input_file", type=str,
                        help="Path tới file câu hỏi, vd simple.json / exception_questions.json "
                             "/ multihop_questions.json / insufficient.json")
    parser.add_argument("--start", type=int, default=1,
                        help="Start index (1-based, inclusive). Default: 1")
    parser.add_argument("--end", type=int, default=None,
                        help="End index (1-based, inclusive). Default: all")
    parser.add_argument("--provider", type=str, default=None,
                        help="Ép một provider cụ thể (groq / openrouter). "
                             "Default: dùng failover mặc định của llm_chat()")
    parser.add_argument("--force", action="store_true",
                        help="Judge lại cả sample đã có judge_score")
    args = parser.parse_args()

    judge_dataset(
        args.input_file, args.start, args.end, args.provider, args.force,
    )