"""Domain-independent semantic projections for parsed JML contracts."""

from __future__ import annotations

import dataclasses

from .array_frame import Frame, frame_allows_transition, frame_locations
from .contracts import Behavior, MethodContract
from .errors import SpecError
from .expressions import evaluate
from .profile import EvaluationBudget, EvaluationProfile, ProfileError, Scenario


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
    if getattr(profile, "extended_jml", False):
        return _normal_available(_active_behaviors(contract, scenario, profile))
    return any(_all(behavior.requires, scenario, profile, pre=True) for behavior in contract.normal_behaviors)


def accepts_normal_transition(
    contract: MethodContract, scenario: Scenario, profile: EvaluationProfile
) -> bool:
    """Every applicable normal behavior contributes its postconditions."""
    if getattr(profile, "extended_jml", False):
        return _array_observation(contract, scenario, profile, post=True)
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


def _active_behaviors(contract, scenario, profile):
    return [behavior for behavior in contract.behaviors if _behavior_applies(behavior, scenario, profile)]


def _normal_available(active: list[Behavior]) -> bool:
    return bool(active) and all(behavior.kind != "exceptional" for behavior in active)


def _array_exceptions(active, context, profile):
    if any(behavior.kind == "normal" for behavior in active):
        return frozenset()
    outcomes = []
    for behavior in active:
        signals = [(name.removeprefix("java.lang."), condition) for name, condition in behavior.signals]
        if behavior.signals_only is not None:
            allowed = {name.removeprefix("java.lang.") for name in behavior.signals_only}
        elif signals:
            allowed = {name for name, _ in signals}
        elif behavior.kind == "exceptional":
            allowed = {"<unspecified>"}
        else:
            continue
        for name, condition in signals:
            if name in allowed and not evaluate(condition, context, profile):
                allowed.remove(name)
        outcomes.append(allowed)
    return frozenset(set.intersection(*outcomes)) if outcomes else frozenset()


def _array_frame(active, context, profile) -> Frame:
    result: Frame = None
    for behavior in active:
        for clause in behavior.assignables:
            result = _intersect_frames(result, frame_locations(clause, context, profile))
    return result


def _array_observation(contract, scenario, profile, *, post=False):
    active = _active_behaviors(contract, scenario, profile)
    applicable = _normal_available(active)
    if post and not applicable:
        return False
    context = scenario.context().pre_state()
    frame = _array_frame(active, context, profile)
    if post:
        return frame_allows_transition(frame, scenario, profile) and all(
            _all(behavior.ensures, scenario, profile) for behavior in active
        )
    return applicable, _array_exceptions(active, context, profile), frame


def _array_projections(contract, pre_points, post_points, profile, *, reference=False):
    budget = EvaluationBudget()
    try:
        pre = {
            point.id: _array_observation(contract, dataclasses.replace(point, budget=budget), profile)
            for point in pre_points
        }
        post = {}
        for point in post_points:
            accepts = _array_observation(contract, dataclasses.replace(point, budget=budget), profile, post=True)
            if reference and point.reference_accepts is not None and accepts != point.reference_accepts:
                raise ProfileError(f"参考合同与观察点 {point.id} 的自检判定不一致")
            post[point.id] = accepts
        return pre, post
    except SpecError as error:
        if reference:
            raise ProfileError(f"参考合同求值失败：{error}") from error
        raise


def _summarize(availability, postconditions, exceptions, frames, output_matches) -> ContractComparison:
    applicability_passed, applicability_total, applicability_fraction = availability
    postcondition_passed, postcondition_total, postcondition_fraction = postconditions
    exceptions_passed, exceptions_total, exceptions_fraction = exceptions
    frame_passed, frame_total, frame_fraction = frames
    locked_passed = frame_passed + (1.0 if output_matches else 0.0)
    locked_total = frame_total + 1.0
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
        locked_fraction=locked_passed / locked_total,
        locked_passed=locked_passed,
        locked_total=locked_total,
    )


def compare_contracts(
    reference: MethodContract,
    candidate: MethodContract,
    pre_points: list[Scenario],
    post_points: list[Scenario],
    profile: EvaluationProfile,
) -> ContractComparison:
    if getattr(profile, "extended_jml", False):
        ref_pre, ref_post = _array_projections(reference, pre_points, post_points, profile, reference=True)
        cand_pre, cand_post = _array_projections(candidate, pre_points, post_points, profile)
        return _summarize(
            _coverage(pre_points, lambda point: ref_pre[point.id][0] == cand_pre[point.id][0]),
            _coverage(post_points, lambda point: ref_post[point.id] == cand_post[point.id]),
            _coverage(pre_points, lambda point: ref_pre[point.id][1] == cand_pre[point.id][1]),
            _coverage(pre_points, lambda point: ref_pre[point.id][2] == cand_pre[point.id][2]),
            True,
        )
    applicability = _coverage(pre_points, lambda point:
        normal_applicable(reference, point, profile)
        == normal_applicable(candidate, point, profile)
    )
    postcondition = _coverage(post_points, lambda point:
        accepts_normal_transition(reference, point, profile)
        == accepts_normal_transition(candidate, point, profile)
    )
    exceptions = _coverage(pre_points, lambda point:
        exception_outcomes(reference, point, profile)
        == exception_outcomes(candidate, point, profile)
    )
    frames = _coverage(pre_points, lambda point:
        effective_frame(reference, point, profile)
        == effective_frame(candidate, point, profile)
    )
    output_matches = sorted(reference.output_ensures) == sorted(candidate.output_ensures)
    return _summarize(applicability, postcondition, exceptions, frames, output_matches)
