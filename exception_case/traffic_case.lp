%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Facts
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

type(emergency_vehicle).

action(use_horn).

condition(night_time).

condition(on_emergency_duty).

conclusion(penalized).


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Rules
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

% Exception rule
exception(emergency_vehicle_on_duty) :-
    type(emergency_vehicle),
    condition(on_emergency_duty).


% Rubric checking

satisfied(r1) :-
    type(emergency_vehicle).


satisfied(r2) :-
    action(use_horn).


satisfied(r3) :-
    condition(night_time).


satisfied(r4) :-
    exception(emergency_vehicle_on_duty).


% Expected conclusion
satisfied(r5) :-
    conclusion(not_penalized).


% Violation

violated(R) :-
    rubric(R),
    not satisfied(R).


% Verdict

verdict(perfect) :-
    not violated(_).

verdict(failed) :-
    violated(_).


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Rubric definition
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

rubric(r1).
rubric(r2).
rubric(r3).
rubric(r4).
rubric(r5).


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Output
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

#show satisfied/1.
#show violated/1.
#show verdict/1.