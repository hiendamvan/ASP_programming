p(a,1). p(b,1). p(c,2).
q(N) :- N = #count{A,X : p(A,X)}.
r(N) :- N = #count{A : p(A,X)}.
s(N) :- N = #count{X : p(A,X)}.