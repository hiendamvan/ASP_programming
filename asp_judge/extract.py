# -*- coding: utf-8 -*-
"""
Tầng 1 của ASP judge: chuyển câu trả lời văn xuôi -> facts có cấu trúc.

RANH GIỚI QUAN TRỌNG (luận điểm cốt lõi của luận văn):
LLM ở đây CHỈ làm nhiệm vụ đọc hiểu — trích ra con số và trạng thái có mặt
trong câu trả lời. Nó KHÔNG được biết rubric, KHÔNG được biết đáp án đúng,
KHÔNG được phán xét đúng/sai. Toàn bộ việc quyết định pass/fail do Clingo
đảm nhiệm ở tầng 2 (judge.lp).

Nhờ vậy, khi so sánh với LLM-as-a-judge ta cô lập được đúng biến số cần đo:
cả hai đều đọc cùng một câu trả lời bằng cùng một LLM, chỉ khác nhau ở chỗ
AI QUYẾT ĐỊNH — mô hình ngôn ngữ hay bộ suy diễn hình thức.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm import llm_chat  # noqa: E402


EXTRACT_SYSTEM_PROMPT = """\
Bạn là bộ trích xuất thông tin. Nhiệm vụ DUY NHẤT của bạn là đọc một câu trả lời \
về xử phạt vi phạm giao thông và trích ra các con số, trạng thái được NÊU TRONG \
CÂU TRẢ LỜI ĐÓ.

TUYỆT ĐỐI KHÔNG:
- Không đánh giá câu trả lời đúng hay sai.
- Không sửa lại, không bổ sung thông tin từ kiến thức của bạn.
- Không suy đoán con số không xuất hiện trong văn bản.

Chỉ ghi lại đúng những gì văn bản nói. Nếu văn bản không nêu một mục nào thì để null.

CHỈ XUẤT RA MỘT ĐỐI TƯỢNG JSON HỢP LỆ, DẠNG:
{
  "fine_min": <số nguyên VNĐ hoặc null>,
  "fine_max": <số nguyên VNĐ hoặc null>,
  "points_deduction": <số điểm GPLX bị trừ, hoặc null>,
  "revocation_min_months": <số tháng tước GPLX tối thiểu, hoặc null>,
  "revocation_max_months": <số tháng tước GPLX tối đa, hoặc null>,
  "penalized": <true nếu câu trả lời kết luận CÓ bị xử phạt, false nếu kết luận KHÔNG bị xử phạt>,
  "requires_clarification": <true nếu câu trả lời nói rằng thông tin chưa đủ / cần làm rõ thêm>
}

Quy ước:
- "phạt tiền từ 150.000 đồng đến 250.000 đồng" -> fine_min=150000, fine_max=250000
- "phạt tiền 300.000 đồng" (một mức duy nhất) -> fine_min=300000, fine_max=300000
- "trừ 02 điểm giấy phép lái xe" -> points_deduction=2
- Câu trả lời nói "không bị xử phạt" -> penalized=false, fine_min=null, fine_max=null
- Câu trả lời nói "chưa đủ thông tin để kết luận" -> requires_clarification=true

KHÔNG thêm bất kỳ văn bản nào ngoài JSON. KHÔNG dùng markdown fence.
"""


# ============================================================
# Fallback bằng regex — dùng khi LLM lỗi hoặc chạy chế độ --no-llm
# ============================================================

_RE_FINE_RANGE = re.compile(
    r"t[ừu]\s+([\d.]+)\s*đ[ồo]ng\s+đ[ếe]n\s+([\d.]+)\s*đ[ồo]ng", re.IGNORECASE
)
_RE_FINE_SINGLE = re.compile(r"ph[ạa]t\s+ti[ềe]n\s+([\d.]+)\s*đ[ồo]ng", re.IGNORECASE)
_RE_POINTS = re.compile(r"tr[ừu]\s+(\d+)\s*đi[ểe]m", re.IGNORECASE)
_RE_REVOCATION = re.compile(
    r"t[ưu][ớo]c[^.]{0,60}?t[ừu]\s+(\d+)\s*th[áa]ng\s+đ[ếe]n\s+(\d+)\s*th[áa]ng",
    re.IGNORECASE,
)
_RE_NOT_PENALIZED = re.compile(
    r"(kh[ôo]ng\s+b[ị]\s+x[ửu]\s+ph[ạa]t|kh[ôo]ng\s+áp\s+d[ụu]ng\s+h[ìi]nh\s+ph[ạa]t"
    r"|đ[ưu][ợo]c\s+lo[ạa]i\s+tr[ừu]|thu[ộo]c\s+tr[ưườ]{0,3}ng\s+h[ợo]p\s+lo[ạa]i\s+tr[ừu])",
    re.IGNORECASE,
)
_RE_CLARIFY = re.compile(
    r"(ch[ưu]a\s+đ[ủu]|kh[ôo]ng\s+đ[ủu]\s+th[ôo]ng\s+tin|c[ầa]n\s+l[àa]m\s+r[õo]"
    r"|c[ầa]n\s+b[ổo]\s+sung|thi[ếe]u\s+th[ôo]ng\s+tin)",
    re.IGNORECASE,
)

# Phủ định: "KHÔNG cần bổ sung thêm thông tin" phải bị loại, nếu không sẽ bị
# hiểu ngược thành "có yêu cầu làm rõ".
_RE_CLARIFY_NEGATED = re.compile(
    r"kh[ôo]ng\s+(c[ầa]n|ph[ải]i)\s+(b[ổo]\s+sung|l[àa]m\s+r[õo]|x[áa]c\s+đ[ịi]nh)",
    re.IGNORECASE,
)


def _num(s):
    return int(s.replace(".", "").replace(",", ""))


def extract_by_regex(answer):
    """Trích facts thuần bằng luật lệ — không gọi API."""
    text = answer or ""

    fine_min = fine_max = None
    m = _RE_FINE_RANGE.search(text)
    if m:
        fine_min, fine_max = _num(m.group(1)), _num(m.group(2))
    else:
        m = _RE_FINE_SINGLE.search(text)
        if m:
            fine_min = fine_max = _num(m.group(1))

    pts = None
    m = _RE_POINTS.search(text)
    if m:
        pts = int(m.group(1))

    rev_min = rev_max = None
    m = _RE_REVOCATION.search(text)
    if m:
        rev_min, rev_max = int(m.group(1)), int(m.group(2))

    requires_clarification = (
        bool(_RE_CLARIFY.search(text)) and not _RE_CLARIFY_NEGATED.search(text)
    )
    not_penalized = bool(_RE_NOT_PENALIZED.search(text))

    if not_penalized:
        penalized = False
    elif fine_min is not None or pts or rev_min:
        penalized = True
    else:
        penalized = not requires_clarification

    return {
        "fine_min": fine_min,
        "fine_max": fine_max,
        "points_deduction": pts,
        "revocation_min_months": rev_min,
        "revocation_max_months": rev_max,
        "penalized": penalized,
        "requires_clarification": requires_clarification,
    }


# ============================================================
# Trích bằng LLM
# ============================================================

def parse_llm_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return json.loads(text)


REQUIRED_KEYS = (
    "fine_min", "fine_max", "points_deduction",
    "revocation_min_months", "revocation_max_months",
    "penalized", "requires_clarification",
)


def extract_facts(answer, provider=None, use_llm=True):
    """Trả về (facts, method). method = 'llm' | 'regex' | 'regex-fallback'."""
    if not use_llm:
        return extract_by_regex(answer), "regex"

    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": f"=== CÂU TRẢ LỜI CẦN TRÍCH ===\n{answer}"},
    ]

    kwargs = {"provider": provider} if provider else {}

    try:
        result = llm_chat(messages, **kwargs)
        facts = parse_llm_json(result["content"])
        # Chuẩn hoá: thiếu key nào thì để None
        facts = {k: facts.get(k) for k in REQUIRED_KEYS}
        return facts, "llm"
    except Exception as e:
        print(f"  [extract] LLM lỗi ({type(e).__name__}: {e}) -> dùng regex")
        return extract_by_regex(answer), "regex-fallback"
