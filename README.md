p(a,1). p(b,1). p(c,2).
q(N) :- N = #count{A,X : p(A,X)}.
r(N) :- N = #count{A : p(A,X)}.
s(N) :- N = #count{X : p(A,X)}.

1. Question: Câu hỏi có yếu tố suy luận 
2. Rubric: Các tiêu chí chấm điểm 
3. Reference answer: Câu trả lời mẫu 
4. Candidate answer: Câu trả lời của LLM
5. Human verdict: Kết luận của con người
6. ASP facts: Các fact được encode từ câu trả lời candidate answer. 
7. ASP rules: Các luật liên quan, rubric được mã hoá thành ASP rule. 
8. Clingo encoding: 
9. ASP output, gồm satisfied rules, violated rules, final verdict, reasoning trace
10. Baseline LLM judge output nếu có

---

## Ánh xạ thiết kế 10 mục ở trên sang code đã triển khai

| # | Mục trong thiết kế | Nằm ở đâu |
|---|---|---|
| 1 | Question | `output_generate/*_fixed.json` → field `question` |
| 2 | Rubric | field `rubrics` (+ `expected` cho multihop), dựng lại bởi `fix_rubrics/` |
| 3 | Reference answer | `perturb.py` biến thể `correct` — sinh thẳng từ rubric |
| 4 | Candidate answer | field `model_answer` (`generate_answer.py` sinh bản thật; `perturb.py` sinh bản có nhãn) |
| 5 | Human verdict | field `gold_verdict` — thay vì gán tay, dùng **tiêm lỗi có kiểm soát** nên nhãn biết trước |
| 6 | ASP facts | field `asp_facts` — `asp_judge/extract.py` trích từ câu trả lời |
| 7 | ASP rules | `asp_judge/judge.lp` |
| 8 | Clingo encoding | `asp_judge/encode.py` (`rubric_facts` + `answer_facts` → chương trình ASP) |
| 9 | ASP output | `asp_verdict` + `asp_violations` (chính là violated rules / reasoning trace) |
| 10 | Baseline LLM judge | `llm_judge.py` → `judge_score`, `judge_verdict`, `judge_rationale` |

So sánh cuối cùng: `compare_judges.py` → `eval_results/comparison.md`.

**Giới hạn cần nêu trong luận văn**: `gold_verdict` đến từ lỗi tiêm nhân tạo,
không phải lỗi tự nhiên của mô hình. Vì câu trả lời được dựng theo mẫu nên bộ
trích facts bằng regex khớp gần như hoàn hảo — con số đáng tin là kết quả khi
chạy `asp_judge/run.py` với tầng trích bằng LLM (mặc định), và nên báo cáo thêm
kết quả trên tập câu trả lời LLM thật (`output_generate/*.json`, field
`model_answer`) để chứng minh tính thực tế.
