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
