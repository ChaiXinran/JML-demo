"""Protocols shared by the generic evaluator and domain profiles."""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence

from .errors import SpecError


class ProfileError(ValueError):
    """A profile cannot interpret a call or provide the requested method."""


@dataclasses.dataclass(frozen=True)
class SymbolSignature:
    parameters: tuple[str, ...]
    returns: str


class _Missing(Enum):
    RESULT = "missing"


NO_RESULT = _Missing.RESULT


@dataclasses.dataclass(frozen=True)
class ArrayValue:
    """An array snapshot with an identity shared by its pre and post views."""

    values: tuple[Any, ...]
    identity: str


def typed_point_value(value: Any, type_name: str, identity: str) -> Any:
    """Decode the JSON values used by the array suites."""
    if type_name == "int" and type(value) is int and -(1 << 31) <= value < (1 << 31):
        return value
    if type_name == "bool" and type(value) is bool:
        return value
    if type_name in {"int[]", "bool[]"}:
        if value is None:
            return None
        if isinstance(value, list) and len(value) <= 64:
            return ArrayValue(
                tuple(typed_point_value(item, type_name[:-2], identity) for item in value),
                identity,
            )
    raise ProfileError(f"观察值不符合 {type_name} 类型或超出观察点数组长度上限 64")


@dataclasses.dataclass
class EvaluationBudget:
    remaining: int = 2_000_000

    def consume(self, amount: int = 1) -> None:
        self.remaining -= amount
        if self.remaining < 0:
            raise SpecError("规格求值超过运算预算，请缩小量词范围或简化表达式")


@dataclasses.dataclass(frozen=True)
class EvaluationContext:
    pre: Any
    post: Any
    arguments: dict[str, Any]
    current: Any
    result: Any = NO_RESULT
    budget: EvaluationBudget | None = None

    def pre_state(self) -> "EvaluationContext":
        return dataclasses.replace(self, current=self.pre, result=NO_RESULT)


@dataclasses.dataclass(frozen=True)
class Scenario:
    pre: Any
    post: Any
    arguments: dict[str, Any]
    id: str = ""
    weight: float = 1.0
    public: bool = False
    tags: tuple[str, ...] = ()
    result: Any = NO_RESULT
    reference_accepts: bool | None = None
    budget: EvaluationBudget | None = dataclasses.field(default=None, repr=False, compare=False)

    def context(self) -> EvaluationContext:
        return EvaluationContext(
            self.pre, self.post, self.arguments, self.post, self.result, self.budget,
        )


class EvaluationProfile(Protocol):
    """The only domain-specific surface used by the expression evaluator."""

    name: str
    allowed_calls: frozenset[str]
    symbols: Mapping[str, tuple[SymbolSignature, ...]]
    grading: Mapping[str, int]
    diagnostics: Mapping[str, Any]
    stateful_calls: frozenset[str]
    smt_type_aliases: Mapping[str, str]
    smt_identity_calls: Mapping[str, int]
    smt_axioms: Sequence[str]

    def state_data_from_smt_calls(
        self, calls: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Any]: ...

    def evaluate_call(
        self, name: str, values: Sequence[Any], context: EvaluationContext
    ) -> Any: ...

    def pre_scenarios(self, method_name: str) -> list[Scenario]: ...

    def post_scenarios(self, method_name: str) -> list[Scenario]: ...

    def state_from_data(self, data: Mapping[str, Any], base: Any | None = None) -> Any: ...

    def post_variants(
        self, rule: str, pre: Any, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...

    def parameter_types(self, method_name: str) -> Mapping[str, str]: ...
