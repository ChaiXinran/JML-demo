"""Optional SMT equivalence checks for the supported expression AST.

Z3 objects are confined to this adapter.  The parser, AST, profiles, and
fixed-point evaluator remain usable without the optional dependency.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Mapping

from .contracts import Behavior, MethodContract
from .expressions import (
    Binary, Call, Expr, ExpressionParser, Literal, Old, Unary, Variable,
    infer_type, validate_calls,
)
from .profile import EvaluationProfile, SymbolSignature


class SmtStatus(str, Enum):
    SAT = "SAT"
    UNSAT = "UNSAT"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


@dataclasses.dataclass(frozen=True)
class SmtRegionResult:
    status: SmtStatus
    reason: str = ""
    witness: Mapping[str, Any] | None = None


@dataclasses.dataclass(frozen=True)
class SmtComparison:
    applicability: SmtRegionResult
    postcondition: SmtRegionResult
    exceptions: SmtRegionResult

    def to_dict(self) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for name in ("applicability", "postcondition", "exceptions"):
            item = getattr(self, name)
            result[name] = {"status": item.status.value}
            if item.reason:
                result[name]["reason"] = item.reason
        return result


class SmtBackendUnavailable(RuntimeError):
    pass


class Z3Backend:
    """Translate supported expressions to Z3 without modifying core AST nodes."""

    def __init__(self, profile: EvaluationProfile, method_name: str, timeout_ms: int):
        try:
            import z3  # type: ignore[import-not-found]
        except ImportError as error:
            raise SmtBackendUnavailable("未安装 z3-solver") from error
        self.z3 = z3
        self.profile = profile
        self.method_name = method_name
        self.timeout_ms = timeout_ms
        self.variable_types = dict(profile.parameter_types(method_name))
        self.type_aliases = dict(getattr(profile, "smt_type_aliases", {}))
        self.stateful_calls = frozenset(getattr(profile, "stateful_calls", profile.allowed_calls))
        self.identity_calls = dict(getattr(profile, "smt_identity_calls", {}))
        self.sorts: dict[str, Any] = {}
        self.variables = {
            name: z3.Const(name, self._sort(type_name))
            for name, type_name in self.variable_types.items()
        }
        self.functions: dict[tuple[str, str, tuple[str, ...], str], Any] = {}
        self.applications: list[tuple[str, str, list[Any], Any]] = []
        self.axiom_expressions: list[Expr] = []
        for source in getattr(profile, "smt_axioms", ()):
            expression = ExpressionParser(source).parse()
            validate_calls(expression, profile)
            if infer_type(expression, profile, self.variable_types) != "bool":
                raise ValueError("SMT 合法状态公理必须是 bool")
            self.axiom_expressions.append(expression)

    def _canonical_type(self, type_name: str) -> str:
        seen: set[str] = set()
        while type_name in self.type_aliases:
            if type_name in seen:
                raise ValueError(f"SMT 类型别名出现循环：{type_name}")
            seen.add(type_name)
            type_name = self.type_aliases[type_name]
        return type_name

    def _sort(self, type_name: str):
        canonical = self._canonical_type(type_name)
        if canonical == "bool":
            return self.z3.BoolSort()
        if canonical == "int":
            return self.z3.IntSort()
        if canonical == "string":
            return self.z3.StringSort()
        if canonical not in self.sorts:
            self.sorts[canonical] = self.z3.DeclareSort(canonical)
        return self.sorts[canonical]

    def _signature(self, expression: Call) -> SymbolSignature:
        argument_types = tuple(
            infer_type(argument, self.profile, self.variable_types)
            for argument in expression.args
        )
        for signature in self.profile.symbols.get(expression.name, ()):
            if signature.parameters == argument_types:
                return signature
        raise ValueError(f"找不到函数 {expression.name} 的 SMT 签名")

    def expression(self, expression: Expr, phase: str):
        z3 = self.z3
        if isinstance(expression, Literal):
            return z3.BoolVal(expression.value) if isinstance(expression.value, bool) else z3.IntVal(expression.value)
        if isinstance(expression, Variable):
            return self.variables[expression.name]
        if isinstance(expression, Old):
            return self.expression(expression.expression, "pre")
        if isinstance(expression, Unary):
            return z3.Not(self.expression(expression.operand, phase))
        if isinstance(expression, Binary):
            left = self.expression(expression.left, phase)
            right = self.expression(expression.right, phase)
            return {
                "&&": lambda: z3.And(left, right),
                "||": lambda: z3.Or(left, right),
                "==": lambda: left == right,
                "!=": lambda: left != right,
                "<": lambda: left < right,
                "<=": lambda: left <= right,
                ">": lambda: left > right,
                ">=": lambda: left >= right,
            }[expression.operator]()
        if isinstance(expression, Call):
            signature = self._signature(expression)
            arguments = [self.expression(argument, phase) for argument in expression.args]
            if expression.name in self.identity_calls:
                index = self.identity_calls[expression.name]
                return arguments[index]
            call_phase = phase if expression.name in self.stateful_calls else "stable"
            key = (expression.name, call_phase, signature.parameters, signature.returns)
            if key not in self.functions:
                suffix = "_".join((*signature.parameters, signature.returns)).replace("[]", "Array")
                name = f"{expression.name}__{call_phase}__{suffix}"
                self.functions[key] = z3.Function(
                    name,
                    *(self._sort(item) for item in signature.parameters),
                    self._sort(signature.returns),
                )
            application = self.functions[key](*arguments)
            if expression.name in self.stateful_calls:
                self.applications.append((phase, expression.name, arguments, application))
            return application
        raise ValueError(f"SMT 不支持表达式节点 {type(expression).__name__}")

    def _all(self, expressions: tuple[Expr, ...], phase: str):
        return self.z3.And(*(self.expression(item, phase) for item in expressions))

    def _requires(self, behavior: Behavior):
        return self._all(behavior.requires, "pre")

    def normal_applicability(self, contract: MethodContract):
        return self.z3.Or(*(self._requires(item) for item in contract.normal_behaviors))

    def normal_transition(self, contract: MethodContract):
        return self.z3.And(*(
            self.z3.Implies(self._requires(item), self._all(item.ensures, "post"))
            for item in contract.normal_behaviors
        ))

    def exception_counts(self, contract: MethodContract) -> Mapping[str, Any]:
        exception_types = {name for behavior in contract.behaviors for name, _ in behavior.signals}
        return {
            exception: self.z3.Sum(*(
                self.z3.If(
                    self.z3.And(self._requires(behavior), self.expression(condition, "pre")),
                    1,
                    0,
                )
                for behavior in contract.behaviors
                for name, condition in behavior.signals
                if name == exception
            ))
            for exception in exception_types
        }

    def check_difference(self, reference, candidate) -> SmtRegionResult:
        solver = self.z3.Solver()
        solver.set(timeout=self.timeout_ms)
        for expression in self.axiom_expressions:
            solver.add(self.expression(expression, "pre"))
            solver.add(self.expression(expression, "post"))
        solver.add(self.z3.Xor(reference, candidate))
        result = solver.check()
        if result == self.z3.sat:
            return SmtRegionResult(SmtStatus.SAT, witness=self._witness(solver.model()))
        if result == self.z3.unsat:
            return SmtRegionResult(SmtStatus.UNSAT)
        return SmtRegionResult(SmtStatus.UNKNOWN, solver.reason_unknown())

    def _value(self, value):
        simplified = self.z3.simplify(value)
        if self.z3.is_true(simplified):
            return True
        if self.z3.is_false(simplified):
            return False
        if self.z3.is_int_value(simplified):
            return simplified.as_long()
        if self.z3.is_string_value(simplified):
            return simplified.as_string()
        return str(simplified)

    def _witness(self, model) -> dict[str, Any]:
        result: dict[str, Any] = {
            "arguments": {
                name: self._value(model.eval(value, model_completion=True))
                for name, value in self.variables.items()
            },
            "pre_calls": [],
            "post_calls": [],
        }
        seen: set[tuple[str, str, tuple[Any, ...]]] = set()
        for phase, name, arguments, application in self.applications:
            values = tuple(
                self._value(model.eval(argument, model_completion=True))
                for argument in arguments
            )
            key = (phase, name, values)
            if key in seen:
                continue
            seen.add(key)
            result[f"{phase}_calls"].append({
                "name": name,
                "args": list(values),
                "result": self._value(model.eval(application, model_completion=True)),
            })
        return result


def compare_contracts_smt(
    reference: MethodContract,
    candidate: MethodContract,
    method_name: str,
    profile: EvaluationProfile,
    timeout_ms: int = 1000,
) -> SmtComparison:
    backend = Z3Backend(profile, method_name, timeout_ms)
    applicability = backend.check_difference(
        backend.normal_applicability(reference), backend.normal_applicability(candidate)
    )
    postcondition = backend.check_difference(
        backend.normal_transition(reference), backend.normal_transition(candidate)
    )
    reference_exceptions = backend.exception_counts(reference)
    candidate_exceptions = backend.exception_counts(candidate)
    exception_types = set(reference_exceptions) | set(candidate_exceptions)
    exception_equal = backend.z3.And(*(
        reference_exceptions.get(name, backend.z3.IntVal(0))
        == candidate_exceptions.get(name, backend.z3.IntVal(0))
        for name in sorted(exception_types)
    ))
    exceptions = backend.check_difference(backend.z3.BoolVal(True), exception_equal)
    return SmtComparison(applicability, postcondition, exceptions)
