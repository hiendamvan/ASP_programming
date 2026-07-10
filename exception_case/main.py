import clingo


ctl = clingo.Control()

ctl.load("traffic_case.lp")

ctl.ground(
    [("base", [])]
)


models = []

with ctl.solve(yield_=True) as handle:
    for model in handle:
        print(model.symbols(shown=True))