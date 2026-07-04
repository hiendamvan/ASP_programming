import clingo

def solve_asp(facts, rules):
    ctl = clingo.Control()
    ctl.add("base", [], facts)
    ctl.add("base", [], rules)
    ctl.ground([("base", [])])

    print("--- Đang giải ---")
    with ctl.solve(yield_=True) as handle:
        for model in handle:
            print("Answer Set:", model.symbols(shown=True))

# Facts (rỗng)
llm_extracted_facts = ""

# ASP Rules (đã sửa)
asp_rules = """
p(a,1). p(b,1). p(c,2).
q(N) :- N = #count{A,X : p(A,X)}.
r(N) :- N = #count{A : p(A,X)}.
s(N) :- N = #count{X : p(A,X)}.
"""

# Chạy
solve_asp(llm_extracted_facts, asp_rules)
