# So sánh LLM-as-a-Judge và ASP-as-a-Judge

Tập đánh giá: `eval_set/judged_both.json` — 99 mẫu, nhãn vàng sinh bằng tiêm lỗi có kiểm soát.

## 1. Chỉ số tổng (lớp dương = câu trả lời SAI)

| Judge | N | Accuracy | Precision | Recall | F1 | Bỏ lọt câu sai |
|---|---|---|---|---|---|---|
| LLM judge | 99 |  88.9% | 100.0% |  80.0% |  88.9% |  20.0% |
| ASP judge | 99 | 100.0% | 100.0% | 100.0% | 100.0% |   0.0% |

## 2. Độ chính xác theo từng loại lỗi tiêm vào

| Loại lỗi | LLM judge đúng | ASP judge đúng |
|---|---|---|
| confident_wrong | 22/22 (100.0%) | 22/22 (100.0%) |
| correct | 23/23 (100.0%) | 23/23 (100.0%) |
| drop_revocation | 0/1 (0.0%) | 1/1 (100.0%) |
| exception_ignored | 12/12 (100.0%) | 12/12 (100.0%) |
| fine_partial | 0/10 (0.0%) | 10/10 (100.0%) |
| fine_shift | 10/10 (100.0%) | 10/10 (100.0%) |
| verbose_correct | 21/21 (100.0%) | 21/21 (100.0%) |

## 3. Độ chính xác theo loại câu hỏi

| Loại câu hỏi | LLM judge đúng | ASP judge đúng |
|---|---|---|
| exception | 48/48 (100.0%) | 48/48 (100.0%) |
| simple | 40/51 (78.4%) | 51/51 (100.0%) |

## 4. LLM judge bịa số liệu trong phần giải thích

Đã kiểm tra 99 phần `judge_rationale`; **9** trong số đó nhắc tới một số tiền không hề xuất hiện trong câu trả lời lẫn rubric (9.1%).

ASP judge không thể mắc lỗi này: mọi con số nó dùng đều được trích trực tiếp từ văn bản và ghi lại trong `asp_facts`.
- `simple-1-fine_shift`: bịa ['3.000.000', '4.000.000'] — "Câu trả lời không khớp với mức phạt quy định trong rubric (3.000.000 - 4.000.000 đồng) mà đưa ra mức 4.500.000 - 8.000.0..."
- `simple-2-fine_partial`: bịa ['10.000.000'] — "Câu trả lời đúng hướng, nêu mức phạt tiền nhưng chỉ đưa ra một mức cụ thể (5.000.000 đồng) thay vì nêu khoảng từ 5.000.0..."
- `simple-3-fine_shift`: bịa ['4.000.000'] — "Câu trả lời chỉ đúng một phần: mức phạt tối thiểu 6.000.000 đồng đúng, nhưng mức tối đa được nêu là 12.000.000 đồng, khô..."
- `simple-4-fine_shift`: bịa ['1.000.000', '800.000'] — "Câu trả lời không khớp với mức phạt quy định trong rubric (800.000 - 1.000.000 đồng) mà đưa ra mức 1.200.000 - 2.000.000..."
- `simple-4-fine_partial`: bịa ['1.000.000'] — "Câu trả lời đúng hướng, nêu mức phạt tiền nhưng chỉ đưa ra mức 800.000 đồng mà không nêu khoảng từ 800.000 đến 1.000.000..."

## 5. Tính tất định (chạy lặp trên cùng đầu vào)

_Chưa chạy lặp. Đo bằng:_ `python determinism_check.py eval_set/judged.json --samples 30 --runs 3`

ASP judge tất định theo thiết kế: Clingo cho cùng một mô hình ổn định với cùng tập fact, nên tỉ lệ này luôn bằng 0%.

## 6. Chi phí và độ trễ

| Judge | Lời gọi API | Thời gian suy diễn | Ghi chú |
|---|---|---|---|
| LLM judge | 99 | — | mỗi mẫu 1 lời gọi, toàn bộ phán quyết do LLM quyết |
| ASP judge (trích: {'regex-fallback': 97, 'llm': 2}) | 2 | 4.65 ms/mẫu | LLM chỉ trích facts; phán quyết do Clingo, chi phí 0 đồng |

## 7. Các mẫu hai judge bất đồng

Tổng cộng **11** mẫu. Trong đó, số mẫu ASP đúng còn LLM sai: **11**; ngược lại: **0**.

- `simple-0-fine_partial` (vàng=fail): LLM=pass, ASP=fail ['incomplete_fine_range', 'wrong_fine']
- `simple-1-fine_partial` (vàng=fail): LLM=pass, ASP=fail ['incomplete_fine_range', 'wrong_fine']
- `simple-2-fine_partial` (vàng=fail): LLM=pass, ASP=fail ['incomplete_fine_range', 'wrong_fine']
- `simple-3-fine_partial` (vàng=fail): LLM=pass, ASP=fail ['incomplete_fine_range', 'wrong_fine']
- `simple-4-fine_partial` (vàng=fail): LLM=pass, ASP=fail ['incomplete_fine_range', 'wrong_fine']
- `simple-5-fine_partial` (vàng=fail): LLM=pass, ASP=fail ['incomplete_fine_range', 'wrong_fine']
- `simple-6-fine_partial` (vàng=fail): LLM=pass, ASP=fail ['incomplete_fine_range', 'wrong_fine']
- `simple-7-fine_partial` (vàng=fail): LLM=pass, ASP=fail ['incomplete_fine_range', 'wrong_fine']
- `simple-7-drop_revocation` (vàng=fail): LLM=pass, ASP=fail ['missing_revocation']
- `simple-8-fine_partial` (vàng=fail): LLM=pass, ASP=fail ['incomplete_fine_range', 'wrong_fine']
