"""Protocols shared by the generic evaluator and domain profiles."""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping, Protocol, Sequence


class ProfileError(ValueError):
    """A profile cannot interpret a call or provide the requested method."""


@dataclasses.dataclass(frozen=True)
class SymbolSignature:
    parameters: tuple[str, ...]
    returns: str


@dataclasses.dataclass(frozen=True)
class EvaluationContext:
    pre: Any
    post: Any
    arguments: dict[str, Any]
    current: Any

    def pre_state(self) -> "EvaluationContext":
        return dataclasses.replace(self, current=self.pre)


@dataclasses.dataclass(frozen=True)
class Scenario:
    pre: Any
    post: Any
    arguments: dict[str, Any]
    id: str = ""
    weight: float = 1.0
    public: bool = False
    tags: tuple[str, ...] = ()

    def context(self) -> EvaluationContext:
        return EvaluationContext(self.pre, self.post, self.arguments, self.post)


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
