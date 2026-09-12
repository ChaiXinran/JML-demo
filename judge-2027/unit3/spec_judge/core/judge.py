"""Domain-independent semantic projections for parsed JML contracts."""

from __future__ import annotations

import dataclasses

from .contracts import Behavior, MethodContract
from .expressions import evaluate
from .profile import EvaluationProfile, Scenario


@dataclasses.dataclass(frozen=True)
class ContractComparison:
    applicability_matches: bool
    postcondition_matches: bool
    exceptions_match: bool
    locked_text_matches: bool
    applicability_fraction: float
    postcondition_fraction: float
    exceptions_fraction: float
    applicability_passed: float
    applicability_total: float
    postcondition_passed: float
    postcondition_total: float
    exceptions_passed: float
    exceptions_total: float
    locked_fraction: float
    locked_passed: float
    locked_total: float


def _coverage(points: list[Scenario], predicate) -> tuple[float, float, float]:
    total = sum(point.weight for point in points)
    if total == 0:
        return 0.0, 0.0, 1.0
    passed = sum(point.weight for point in points if predicate(point))
    return passed, total, passed / total


def _all(
    expressions, scenario: Scenario, profile: EvaluationProfile, *, pre: bool = False
) -> bool:
    context = scenario.context()
    if pre:
        context = context.pre_state()
    return all(bool(evaluate(item, context, profile)) for item in expressions)


def normal_applicable(
    contract: MethodContract, scenario: Scenario, profile: EvaluationProfile
) -> bool:
    return any(_all(behavior.requires, scenario, profile, pre=True) for behavior in contract.normal_behaviors)


def accepts_normal_transition(
    contract: MethodContract, scenario: Scenario, profile: EvaluationProfile
) -> bool:
    """Every applicable normal behavior contributes its postconditions."""
    return all(
        not _all(behavior.requires, scenario, profile, pre=True)
        or _all(behavior.ensures, scenario, profile)
        for behavior in contract.normal_behaviors
    )


def _behavior_applies(
    behavior: Behavior, scenario: Scenario, profile: EvaluationProfile
) -> bool:
    return _all(behavior.requires, scenario, profile, pre=True)


def exception_outcomes(
    contract: MethodContract, scenario: Scenario, profile: EvaluationProfile
) -> tuple[str, ...]:
    """Return the observable exception labels selected by this abstract point."""
    return tuple(sorted(
        exception
        for behavior in contract.behaviors
        if _behavior_applies(behavior, scenario, profile)
        for exception, condition in behavior.signals
        if bool(evaluate(condition, scenario.context().pre_state(), profile))
    ))


def _split_store_references(clause: str) -> frozenset[str] | None:
    """Normalize the supported assignable store-ref list; None means all."""
    values: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(clause):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            values.append(clause[start:index])
            start = index + 1
    values.append(clause[start:])
    normalized = {"".join(value.split()) for value in values if value.strip()}
    if "\\everything" in normalized:
        return None
    normalized.discard("\\nothing")
    return frozenset(normalized)


def _intersect_frames(
    left: frozenset[str] | None, right: frozenset[str] | None
) -> frozenset[str] | None:
    if left is None:
        return right
    if right is None:
        return left
    return left & right


def _behavior_frame(behavior: Behavior) -> frozenset[str] | None:
    result: frozenset[str] | None = None
    for clause in behavior.assignables:
        result = _intersect_frames(result, _split_store_references(clause))
    return result


def _frame_behavior_applies(
    behavior: Behavior, scenario: Scenario, profile: EvaluationProfile
) -> bool:
    if not _behavior_applies(behavior, scenario, profile):
        return False
    if behavior.kind != "exceptional":
        return True
    # In the supported teaching subset, signals conditions select exceptional
    # branches.  An exceptional frame therefore applies when at least one of
    # its declared exception conditions is selected at this point.
    return any(
        bool(evaluate(condition, scenario.context().pre_state(), profile))
        for _, condition in behavior.signals
    )


def effective_frame(
    contract: MethodContract, scenario: Scenario, profile: EvaluationProfile
) -> frozenset[str] | None:
    result: frozenset[str] | None = None
    for behavior in contract.behaviors:
        if _frame_behavior_applies(behavior, scenario, profile):
            result = _intersect_frames(result, _behavior_frame(behavior))
    return result


def compare_contracts(
    reference: MethodContract,
    candidate: MethodContract,
    pre_points: list[Scenario],
    post_points: list[Scenario],
    profile: EvaluationProfile,
) -> ContractComparison:
    applicability_passed, applicability_total, applicability_fraction = _coverage(pre_points, lambda point:
        normal_applicable(reference, point, profile)
        == normal_applicable(candidate, point, profile)
    )
    postcondition_passed, postcondition_total, postcondition_fraction = _coverage(post_points, lambda point:
        accepts_normal_transition(reference, point, profile)
        == accepts_normal_transition(candidate, point, profile)
    )
    exceptions_passed, exceptions_total, exceptions_fraction = _coverage(pre_points, lambda point:
        exception_outcomes(reference, point, profile)
        == exception_outcomes(candidate, point, profile)
    )
    frame_passed, frame_total, frame_fraction = _coverage(pre_points, lambda point:
        effective_frame(reference, point, profile)
        == effective_frame(candidate, point, profile)
    )
    output_matches = sorted(reference.output_ensures) == sorted(candidate.output_ensures)
    locked_passed = frame_passed + (1.0 if output_matches else 0.0)
    locked_total = frame_total + 1.0
    locked_fraction = locked_passed / locked_total
    return ContractComparison(
        applicability_matches=applicability_fraction == 1.0,
        postcondition_matches=postcondition_fraction == 1.0,
        exceptions_match=exceptions_fraction == 1.0,
        locked_text_matches=frame_fraction == 1.0 and output_matches,
        applicability_fraction=applicability_fraction,
        postcondition_fraction=postcondition_fraction,
        exceptions_fraction=exceptions_fraction,
        applicability_passed=applicability_passed,
        applicability_total=applicability_total,
        postcondition_passed=postcondition_passed,
        postcondition_total=postcondition_total,
        exceptions_passed=exceptions_passed,
        exceptions_total=exceptions_total,
        locked_fraction=locked_fraction,
        locked_passed=locked_passed,
        locked_total=locked_total,
    )
