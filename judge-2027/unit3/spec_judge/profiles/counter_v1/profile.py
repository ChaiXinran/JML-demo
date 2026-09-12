"""Minimal scalar-state profile used to verify cross-class extensibility."""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping, Sequence

from core.profile import EvaluationContext, ProfileError, Scenario, SymbolSignature


@dataclasses.dataclass(frozen=True)
class CounterState:
    value: int


class CounterV1Profile:
    name = "counter_v1"
    allowed_calls = frozenset({"getValue"})
    symbols = {"getValue": (SymbolSignature((), "int"),)}
    stateful_calls = frozenset({"getValue"})
    smt_type_aliases = {}
    smt_identity_calls = {}
    smt_axioms = ()
    contract_shape = {"requires": 1, "ensures": 1, "signals": 0}
    grading = {"applicability": 20, "postcondition": 70, "exceptions": 0, "locked": 10}
    diagnostics = {}

    def parameter_types(self, method_name: str) -> Mapping[str, str]:
        if method_name != "checkNonNegative":
            raise ProfileError(f"counter_v1 尚未配置方法 {method_name}")
        return {}

    def evaluate_call(
        self, name: str, values: Sequence[Any], context: EvaluationContext
    ) -> Any:
        if name == "getValue" and not values and isinstance(context.current, CounterState):
            return context.current.value
        raise ProfileError(f"函数 {name} 的参数或状态不符合 counter_v1")

    def state_from_data(
        self, data: Mapping[str, Any], base: CounterState | None = None
    ) -> CounterState:
        unknown = set(data) - {"use", "copy", "value", "set"}
        if unknown:
            raise ProfileError(f"counter_v1 不支持状态字段 {sorted(unknown)}")
        value = base.value if base is not None else 0
        if "value" in data:
            value = int(data["value"])
        if "set" in data:
            changes = data["set"]
            if not isinstance(changes, Mapping) or set(changes) - {"value"}:
                raise ProfileError("counter_v1 的 set 只支持 value")
            value = int(changes.get("value", value))
        return CounterState(value)

    def state_data_from_smt_calls(
        self, calls: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        for call in calls:
            if call["name"] == "getValue":
                return {"value": int(call["result"])}
        return {"value": 0}

    def post_variants(
        self, rule: str, pre: CounterState, arguments: Mapping[str, Any]
    ) -> Mapping[str, CounterState]:
        if rule != "neighbor_values":
            raise ProfileError(f"counter_v1 不支持后态变异规则 {rule}")
        if not isinstance(pre, CounterState) or arguments:
            raise ProfileError("neighbor_values 需要无参数 CounterState 前态")
        return {
            "unchanged": pre,
            "above": CounterState(pre.value + 1),
            "below": CounterState(pre.value - 1),
        }

    def pre_scenarios(self, method_name: str) -> list[Scenario]:
        raise ProfileError("counter_v1 请通过 suite 提供测试点")

    def post_scenarios(self, method_name: str) -> list[Scenario]:
        raise ProfileError("counter_v1 请通过 suite 提供测试点")


DEFAULT_PROFILE = CounterV1Profile()
