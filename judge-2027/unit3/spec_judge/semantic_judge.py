"""Compatibility facade for the generic, profile-driven semantic judge.

Parsing and expression evaluation live in ``core``; domain behavior lives in
an injected profile.  Suite/Profile metadata supplies optional teaching-facing
diagnostic labels while the comparison itself remains domain-independent.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from pathlib import Path
from typing import Any

from core.contracts import (
    Clause, MethodContract, extract_clauses, extract_jml_block,
    parse_contract as parse_generic_contract,
)
from core.errors import SpecError
from core.expressions import (
    Binary, Call, Expr, ExpressionParser, Literal, Old, Token, Unary, Variable,
    evaluate as evaluate_expression, tokenize, validate_calls as validate_expression_calls,
)
from core.judge import compare_contracts
from core.profile import EvaluationContext, EvaluationProfile, ProfileError, Scenario
from core.smt import SmtBackendUnavailable, SmtStatus, compare_contracts_smt
from profiles.network_v1 import DEFAULT_PROFILE, NetworkState, NetworkUserRef


class SemanticDiagnosticCode(str, Enum):
    NORMAL_CONDITION_MISMATCH = "NORMAL_CONDITION_MISMATCH"
    POSTCONDITION_MISMATCH = "POSTCONDITION_MISMATCH"
    EXCEPTION_PARTITION_MISMATCH = "EXCEPTION_PARTITION_MISMATCH"
    LOCKED_CLAUSE_CHANGED = "LOCKED_CLAUSE_CHANGED"
    JML_FORMAT_OR_SYMBOL = "JML_FORMAT_OR_SYMBOL"


# Compatibility exports used by earlier callers and experiments.
State = NetworkState
UserRef = NetworkUserRef
EvalContext = EvaluationContext
ALLOWED_CALLS = set(DEFAULT_PROFILE.allowed_calls)


def validate_calls(expression: Expr, profile: EvaluationProfile = DEFAULT_PROFILE) -> None:
    validate_expression_calls(expression, profile)


def evaluate(
    expression: Expr,
    context: EvaluationContext,
    profile: EvaluationProfile = DEFAULT_PROFILE,
) -> Any:
    return evaluate_expression(expression, context, profile)


def parse_contract(
    java_source: str,
    method_name: str = "followUser",
    profile: EvaluationProfile = DEFAULT_PROFILE,
) -> MethodContract:
    contract = parse_generic_contract(java_source, method_name, profile)
    shape = getattr(profile, "contract_shape", None)
    if shape is not None:
        actual = {
            "requires": len(contract.requires),
            "ensures": len(contract.ensures),
            "signals": len(contract.signals),
        }
        for kind, rule in shape.items():
            minimum = rule.get("min", 0) if isinstance(rule, dict) else rule
            maximum = rule.get("max") if isinstance(rule, dict) else rule
            if actual[kind] < minimum or (maximum is not None and actual[kind] > maximum):
                raise SpecError(
                    f"{method_name} 合同的 {kind} 数量不满足 {rule}，实际得到 {actual[kind]} 个"
                )
    return contract


def pre_state_scenarios() -> list[Scenario]:
    return DEFAULT_PROFILE.pre_scenarios("followUser")


def post_state_scenarios() -> list[Scenario]:
    return DEFAULT_PROFILE.post_scenarios("followUser")


@dataclasses.dataclass(frozen=True)
class Diagnostic:
    code: str
    location: str
    category: str
    observation: str
    guidance: str
    lines: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = dataclasses.asdict(self)
        if not self.lines:
            payload.pop("lines")
        return payload


@dataclasses.dataclass(frozen=True)
class SemanticResult:
    score: int
    passed: bool
    diagnostics: tuple[Diagnostic, ...]
    coverage: dict[str, Any] | None = None
    evaluation: dict[str, Any] | None = None
    solver: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "score": self.score,
            "passed": self.passed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
        if self.coverage is not None:
            payload["coverage"] = self.coverage
        if self.evaluation is not None:
            payload["evaluation"] = self.evaluation
        if self.solver is not None:
            payload["solver"] = self.solver
        return payload


def _mismatch(
    reference: Expr,
    candidate: Expr,
    scenarios: list[Scenario],
    profile: EvaluationProfile,
) -> bool:
    return any(
        bool(evaluate(reference, scenario.context(), profile))
        != bool(evaluate(candidate, scenario.context(), profile))
        for scenario in scenarios
    )


DEFAULT_DIAGNOSTICS = {
    "applicability": {
        "location": "NORMAL_CONDITION",
        "category": "正常行为条件",
        "observation": "存在前态使你的正常行为条件与标准合同的行为分类不一致。",
        "guidance": "检查正常行为的 requires 是否过强或过弱。",
    },
    "postcondition": {
        "location": "POSTCONDITION",
        "category": "后置状态关系",
        "observation": "成功后的整体状态约束与标准合同不一致。",
        "guidance": "检查全部 ensures 是否共同接受和拒绝了正确的状态转换。",
    },
    "exceptions": {
        "location": "EXCEPTION_PARTITION",
        "category": "异常分支与优先级",
        "observation": "整体异常匹配集合与标准合同不一致。",
        "guidance": "检查每类异常的覆盖范围以及重叠状态下的优先级。",
    },
    "locked": {
        "location": "LOCKED_FRAME_OR_OUTPUT",
        "category": "锁定规格被修改",
        "observation": "assignable 或成功输出规格与模板中的锁定内容不一致。",
        "guidance": "仅填写分配给学生的空位，不要修改锁定子句。",
    },
}


def _diagnostic(
    profile: EvaluationProfile,
    region: str,
    code: SemanticDiagnosticCode,
    lines: tuple[int, ...],
    location: str | None = None,
) -> Diagnostic:
    configured = getattr(profile, "diagnostics", {}).get(region, {})
    defaults = DEFAULT_DIAGNOSTICS[region]
    return Diagnostic(
        code.value,
        location or configured.get("location") or defaults["location"],
        configured.get("category") or defaults["category"],
        configured.get("observation") or defaults["observation"],
        configured.get("guidance") or defaults["guidance"],
        lines,
    )


def evaluate_contracts(
    reference: MethodContract,
    candidate: MethodContract,
    method_name: str = "followUser",
    profile: EvaluationProfile = DEFAULT_PROFILE,
) -> SemanticResult:
    diagnostics: list[Diagnostic] = []
    pre_scenarios = profile.pre_scenarios(method_name)
    post_scenarios = profile.post_scenarios(method_name)
    comparison = compare_contracts(
        reference, candidate, pre_scenarios, post_scenarios, profile
    )
    solver_payload: dict[str, Any] | None = None
    solver_statuses: dict[str, SmtStatus] = {}
    solver_config = getattr(profile, "solver", {"mode": "off"})
    solver_mode = solver_config.get("mode", "off")
    enforce_solver = solver_mode == "required"
    if solver_mode != "off":
        try:
            solver_comparison = compare_contracts_smt(
                reference,
                candidate,
                method_name,
                profile,
                solver_config.get("timeout_ms", 1000),
            )
            solver_payload = solver_comparison.to_dict()
            solver_statuses = {
                name: getattr(solver_comparison, name).status
                for name in ("applicability", "postcondition", "exceptions")
            }
        except SmtBackendUnavailable as error:
            if solver_mode == "required":
                raise ProfileError(f"suite 要求 SMT，但后端不可用：{error}") from error
            solver_payload = {
                name: {"status": SmtStatus.UNAVAILABLE.value, "reason": str(error)}
                for name in ("applicability", "postcondition", "exceptions")
            }
        except ValueError as error:
            raise ProfileError(f"SMT Profile 配置或翻译失败：{error}") from error
        if enforce_solver:
            inconclusive = [
                name for name, status in solver_statuses.items()
                if status == SmtStatus.UNKNOWN
            ]
            if inconclusive:
                raise ProfileError(
                    "SMT required 模式未能得出结论：" + ", ".join(inconclusive)
                )

    if not comparison.applicability_matches:
        diagnostics.append(_diagnostic(
            profile, "applicability", SemanticDiagnosticCode.NORMAL_CONDITION_MISMATCH,
            candidate.lines_for("requires", normal_only=True),
        ))
    elif enforce_solver and solver_statuses.get("applicability") == SmtStatus.SAT:
        diagnostics.append(_diagnostic(
            profile, "applicability", SemanticDiagnosticCode.NORMAL_CONDITION_MISMATCH,
            candidate.lines_for("requires", normal_only=True),
        ))

    post_mismatch = not comparison.postcondition_matches
    post_slots = getattr(profile, "diagnostics", {}).get("postcondition", {}).get("slots", [])
    if post_mismatch and len(reference.ensures) == len(candidate.ensures) == len(post_slots):
        post_lines = candidate.lines_for("ensures", normal_only=True)
        for index, label in enumerate(post_slots):
            if not _mismatch(reference.ensures[index], candidate.ensures[index], post_scenarios, profile):
                continue
            diagnostics.append(_diagnostic(
                profile, "postcondition", SemanticDiagnosticCode.POSTCONDITION_MISMATCH,
                post_lines[index:index + 1], label,
            ))
    elif post_mismatch:
        diagnostics.append(_diagnostic(
            profile, "postcondition", SemanticDiagnosticCode.POSTCONDITION_MISMATCH,
            candidate.lines_for("ensures", normal_only=True),
        ))
    elif enforce_solver and solver_statuses.get("postcondition") == SmtStatus.SAT:
        diagnostics.append(_diagnostic(
            profile, "postcondition", SemanticDiagnosticCode.POSTCONDITION_MISMATCH,
            candidate.lines_for("ensures", normal_only=True),
        ))

    exception_mismatch = not comparison.exceptions_match
    exception_slots = getattr(profile, "diagnostics", {}).get("exceptions", {}).get("slots", [])
    if exception_mismatch and len(reference.signals) == len(candidate.signals) == len(exception_slots):
        signal_lines = candidate.lines_for("signals")
        for index, label in enumerate(exception_slots):
            reference_exception, reference_expression = reference.signals[index]
            candidate_exception, candidate_expression = candidate.signals[index]
            if candidate_exception == reference_exception and not _mismatch(
                reference_expression, candidate_expression, pre_scenarios, profile
            ):
                continue
            diagnostics.append(_diagnostic(
                profile, "exceptions", SemanticDiagnosticCode.EXCEPTION_PARTITION_MISMATCH,
                signal_lines[index:index + 1], label,
            ))
    elif exception_mismatch:
        diagnostics.append(_diagnostic(
            profile, "exceptions", SemanticDiagnosticCode.EXCEPTION_PARTITION_MISMATCH,
            candidate.lines_for("signals"),
        ))
    elif enforce_solver and solver_statuses.get("exceptions") == SmtStatus.SAT:
        diagnostics.append(_diagnostic(
            profile, "exceptions", SemanticDiagnosticCode.EXCEPTION_PARTITION_MISMATCH,
            candidate.lines_for("signals"),
        ))

    if not comparison.locked_text_matches:
        locked_lines = tuple(
            clause.line for clause in candidate.clauses
            if clause.kind == "assignable" or clause.body.startswith("(* output->")
        )
        diagnostics.append(_diagnostic(
            profile, "locked", SemanticDiagnosticCode.LOCKED_CLAUSE_CHANGED,
            locked_lines,
        ))
    weights = profile.grading
    fractions = {
        "applicability": comparison.applicability_fraction,
        "postcondition": comparison.postcondition_fraction,
        "exceptions": comparison.exceptions_fraction,
        "locked": comparison.locked_fraction,
    }
    for region in ("applicability", "postcondition", "exceptions"):
        if enforce_solver and solver_statuses.get(region) == SmtStatus.SAT:
            fractions[region] = 0.0
    total_weight = sum(weights.values())
    passed_weight = sum(weight * fractions[name] for name, weight in weights.items())
    score = round(100 * passed_weight / total_weight)
    coverage = {
        "applicability": {
            "passed_weight": comparison.applicability_passed,
            "total_weight": comparison.applicability_total,
        },
        "postcondition": {
            "passed_weight": comparison.postcondition_passed,
            "total_weight": comparison.postcondition_total,
        },
        "exceptions": {
            "passed_weight": comparison.exceptions_passed,
            "total_weight": comparison.exceptions_total,
        },
        "locked": {
            "passed_weight": comparison.locked_passed,
            "total_weight": comparison.locked_total,
        },
    }
    smt_proved = bool(solver_statuses) and all(
        status == SmtStatus.UNSAT for status in solver_statuses.values()
    )
    evaluation = {
        "profile": profile.name,
        "suite": getattr(profile, "suite_name", None),
        "suite_version": getattr(profile, "suite_version", None),
        "guarantee_scope": (
            "smt_supported_subset" if smt_proved
            else getattr(profile, "guarantee_scope", "profile_scenarios")
        ),
    }
    return SemanticResult(
        score, not diagnostics, tuple(diagnostics), coverage, evaluation, solver_payload
    )


def evaluate_sources(
    reference_source: str,
    student_source: str,
    method_name: str = "followUser",
    profile: EvaluationProfile = DEFAULT_PROFILE,
) -> SemanticResult:
    try:
        reference = parse_contract(reference_source, method_name, profile)
    except (SpecError, ProfileError) as error:
        raise ProfileError(f"参考合同或评测配置无效：{error}") from error
    try:
        candidate = parse_contract(student_source, method_name, profile)
    except SpecError as error:
        return SemanticResult(0, False, (Diagnostic(
            SemanticDiagnosticCode.JML_FORMAT_OR_SYMBOL.value, "SUBMISSION", "JML 格式或接口符号",
            str(error), "检查空位是否填完、JML 语法是否完整，以及是否只使用模板允许的接口符号。",
        ),))
    return evaluate_contracts(reference, candidate, method_name, profile)


def evaluate_files(
    reference: Path,
    student: Path,
    method_name: str = "followUser",
    profile: EvaluationProfile = DEFAULT_PROFILE,
) -> SemanticResult:
    return evaluate_sources(
        reference.read_text(encoding="utf-8"), student.read_text(encoding="utf-8"),
        method_name, profile,
    )
