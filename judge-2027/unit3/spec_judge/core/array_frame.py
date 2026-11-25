"""Concretize the supported array frame clauses on a point's pre-state."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re

from .errors import SpecError
from .expressions import Expr, ExpressionParser, Variable, evaluate, infer_type, validate_calls
from .profile import ArrayValue, EvaluationContext, EvaluationProfile, Scenario


@dataclass(frozen=True)
class StoreRef:
    name: str
    elements: bool = False
    lower: Expr | None = None
    upper: Expr | None = None


Frame = frozenset[tuple[str, str, int]] | None


def _references(source: str):
    start = depth = 0
    for index, char in enumerate(source):
        if char == "[" or char == "(":
            depth += 1
        elif char == "]" or char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            yield source[start:index].strip()
            start = index + 1
    yield source[start:].strip()


@lru_cache(maxsize=128)
def parse_frame(source: str) -> tuple[StoreRef, ...]:
    refs = []
    for value in _references(source):
        if value in {r"\nothing", r"\everything"}:
            refs.append(StoreRef(value))
            continue
        match = re.fullmatch(r"(?:(this)\s*\.\s*)?([A-Za-z_]\w*)\s*(?:\[(.+)\])?", value)
        if match is None:
            raise SpecError("assignable 只支持字段、数组元素、[*]、[起点 .. 终点] 和标准 frame 常量")
        receiver, name, subscript = match.groups()
        name = f"this.{name}" if receiver else name
        if subscript is None:
            refs.append(StoreRef(name))
        elif subscript.strip() == "*":
            refs.append(StoreRef(name, elements=True))
        else:
            lower, separator, upper = subscript.partition("..")
            index = ExpressionParser(lower.strip()).parse()
            end = ExpressionParser(upper.strip()).parse() if separator else index
            refs.append(StoreRef(name, elements=True, lower=index, upper=end))
    if len(refs) > 1 and any(ref.name.startswith("\\") for ref in refs):
        raise SpecError("assignable 的 frame 常量必须独立书写")
    return tuple(refs)


def validate_frame(source: str, profile: EvaluationProfile, parameters) -> None:
    variables = {**profile.state_variables, **parameters}
    for ref in parse_frame(source):
        if ref.name.startswith("\\"):
            continue
        name = ref.name.removeprefix("this.")
        if ref.name.startswith("this.") and name not in profile.state_variables:
            raise SpecError(f"assignable 未知字段：{name}")
        if ref.elements:
            if variables.get(name) not in {"int[]", "bool[]"}:
                raise SpecError(f"assignable 未知数组：{name}")
        elif name not in profile.state_variables:
            raise SpecError(f"assignable 未知字段：{name}")
        for index in (ref.lower, ref.upper):
            if index is not None:
                validate_calls(index, profile)
                if infer_type(index, profile, variables) != "int":
                    raise SpecError("assignable 的数组下标必须是 int")


def frame_locations(source: str, context: EvaluationContext, profile: EvaluationProfile) -> Frame:
    locations = set()
    for ref in parse_frame(source):
        if ref.name == r"\everything":
            return None
        if ref.name == r"\nothing":
            continue
        name = ref.name.removeprefix("this.")
        if not ref.elements:
            locations.add(("field", name, 0))
            continue
        array = evaluate(Variable(name), context, profile)
        if not isinstance(array, ArrayValue):
            raise SpecError("assignable 无法使用 null 数组")
        size = len(array.values)
        start = evaluate(ref.lower, context, profile) if ref.lower is not None else 0
        end = evaluate(ref.upper, context, profile) if ref.upper is not None else size - 1
        if start > end:
            continue
        if start < 0 or end >= size:
            raise SpecError("assignable 的数组区间越界")
        locations.update(("element", array.identity, index) for index in range(start, end + 1))
    return frozenset(locations)


def frame_allows_transition(frame: Frame, scenario: Scenario, profile: EvaluationProfile) -> bool:
    if frame is None:
        return True
    for name in profile.state_variables:
        before = profile.state_name(name, scenario.pre)
        after = profile.state_name(name, scenario.post)
        if before.identity != after.identity:
            if ("field", name, 0) not in frame:
                return False
        elif any(
            old != new and ("element", before.identity, index) not in frame
            for index, (old, new) in enumerate(zip(before.values, after.values))
        ):
            return False
    return True
