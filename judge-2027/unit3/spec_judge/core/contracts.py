"""Extract and parse method contracts independently of a course domain."""

from __future__ import annotations

import dataclasses
import re

from .errors import SpecError
from .expressions import Expr, ExpressionParser, infer_type, validate_calls
from .profile import EvaluationProfile


@dataclasses.dataclass(frozen=True)
class Clause:
    kind: str
    body: str
    line: int
    behavior_index: int = 0
    behavior_kind: str = "generic"


@dataclasses.dataclass(frozen=True)
class Behavior:
    kind: str
    requires: tuple[Expr, ...]
    ensures: tuple[Expr, ...]
    signals: tuple[tuple[str, Expr], ...]
    assignables: tuple[str, ...]
    output_ensures: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class MethodContract:
    behaviors: tuple[Behavior, ...]
    clauses: tuple[Clause, ...] = ()

    @property
    def normal_behaviors(self) -> tuple[Behavior, ...]:
        return tuple(item for item in self.behaviors if item.kind != "exceptional")

    @property
    def exceptional_behaviors(self) -> tuple[Behavior, ...]:
        return tuple(item for item in self.behaviors if item.kind == "exceptional")

    @property
    def requires(self) -> tuple[Expr, ...]:
        return tuple(expression for item in self.normal_behaviors for expression in item.requires)

    @property
    def ensures(self) -> tuple[Expr, ...]:
        return tuple(expression for item in self.normal_behaviors for expression in item.ensures)

    @property
    def signals(self) -> tuple[tuple[str, Expr], ...]:
        return tuple(signal for item in self.behaviors for signal in item.signals)

    @property
    def assignables(self) -> tuple[str, ...]:
        return tuple(value for item in self.behaviors for value in item.assignables)

    @property
    def output_ensures(self) -> tuple[str, ...]:
        return tuple(value for item in self.behaviors for value in item.output_ensures)

    def lines_for(self, kind: str, *, normal_only: bool = False) -> tuple[int, ...]:
        return tuple(
            clause.line
            for clause in self.clauses
            if clause.kind == kind
            and (not normal_only or clause.behavior_kind != "exceptional")
        )


def _method_declaration_start(java_source: str, method_name: str) -> int:
    # Ignore comments when locating the Java declaration.  Otherwise a call to
    # the target method inside JML could be mistaken for the declaration.
    without_comments = re.sub(
        r"/\*.*?\*/|//[^\n]*",
        lambda match: "".join("\n" if char == "\n" else " " for char in match.group()),
        java_source,
        flags=re.DOTALL,
    )
    declaration = re.search(r"\b" + re.escape(method_name) + r"\s*\(", without_comments)
    if declaration is None:
        raise SpecError(f"未找到方法 {method_name} 的 Java 声明")
    return declaration.start()


def _extract_jml_match(java_source: str, method_name: str) -> re.Match[str]:
    blocks = list(re.finditer(r"/\*@(?P<body>.*?)@\*/", java_source, re.DOTALL))
    declaration_start = _method_declaration_start(java_source, method_name)
    for block in reversed(blocks):
        if block.end() <= declaration_start and re.search(
            r"\b(?:requires|ensures|signals|assignable)\b", block.group("body")
        ):
            return block
    raise SpecError(f"未找到紧邻方法 {method_name} 的 JML 注释块")


def extract_jml_block(java_source: str, method_name: str) -> str:
    return _extract_jml_match(java_source, method_name).group("body")


def extract_clauses(block: str, line_offset: int = 0) -> list[Clause]:
    cleaned = "\n".join(re.sub(r"^\s*@\s?", "", line).rstrip() for line in block.splitlines())
    headers = list(re.finditer(
        r"(?m)^\s*(?:public\s+)?(?P<kind>normal_behavior|exceptional_behavior|behavior)\b",
        cleaned,
    ))
    starts = list(re.finditer(r"(?m)^\s*(requires|ensures|signals|assignable)\b\s*", cleaned))
    clauses: list[Clause] = []
    for start in starts:
        depth = 0
        for index in range(start.end(), len(cleaned)):
            char = cleaned[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif char == ";" and depth == 0:
                preceding = [item for item in headers if item.start() < start.start()]
                header = preceding[-1] if preceding else None
                behavior_index = headers.index(header) if header is not None else 0
                behavior_kind = (
                    header.group("kind").removesuffix("_behavior")
                    if header is not None else "generic"
                )
                clauses.append(Clause(
                    start.group(1), re.sub(r"\s+", " ", cleaned[start.end():index]).strip(),
                    line_offset + cleaned.count("\n", 0, start.start()) + 1,
                    behavior_index, behavior_kind,
                ))
                break
        else:
            line = line_offset + cleaned.count("\n", 0, start.start()) + 1
            raise SpecError(f"第 {line} 行的 {start.group(1)} 子句缺少分号")
    return clauses


def _expression(
    clause: Clause, profile: EvaluationProfile, variables: dict[str, str]
) -> Expr:
    try:
        expression = ExpressionParser(clause.body).parse()
        validate_calls(expression, profile)
        result_type = infer_type(expression, profile, variables)
        if result_type != "bool":
            raise SpecError(f"{clause.kind} 条件必须是 bool，实际为 {result_type}")
        return expression
    except SpecError as error:
        raise SpecError(f"第 {clause.line} 行 {clause.kind}：{error}") from error


def parse_contract(java_source: str, method_name: str, profile: EvaluationProfile) -> MethodContract:
    if "{{" in java_source:
        placeholder = java_source.index("{{")
        line = java_source.count("\n", 0, placeholder) + 1
        raise SpecError(f"第 {line} 行仍有未填写的空位")
    block = _extract_jml_match(java_source, method_name)
    line_offset = java_source.count("\n", 0, block.start("body"))
    clauses = extract_clauses(block.group("body"), line_offset)
    variables = dict(profile.parameter_types(method_name))
    grouped: dict[int, list[Clause]] = {}
    for clause in clauses:
        grouped.setdefault(clause.behavior_index, []).append(clause)
    behaviors: list[Behavior] = []
    for index in sorted(grouped):
        group = grouped[index]
        ensures: list[Expr] = []
        outputs: list[str] = []
        for clause in (item for item in group if item.kind == "ensures"):
            if clause.body.startswith("(* output->"):
                outputs.append(clause.body)
            else:
                ensures.append(_expression(clause, profile, variables))
        signals: list[tuple[str, Expr]] = []
        for clause in (item for item in group if item.kind == "signals"):
            match = re.match(r"^\((?P<exception>[A-Za-z_]\w*)\s+[A-Za-z_]\w*\)\s*(?P<condition>.+)$", clause.body)
            if match is None:
                raise SpecError(f"第 {clause.line} 行 signals：异常声明格式错误")
            condition = dataclasses.replace(clause, body=match.group("condition"))
            signals.append((match.group("exception"), _expression(condition, profile, variables)))
        behaviors.append(Behavior(
            group[0].behavior_kind,
            tuple(_expression(item, profile, variables) for item in group if item.kind == "requires"),
            tuple(ensures), tuple(signals),
            tuple(item.body for item in group if item.kind == "assignable"), tuple(outputs),
        ))
    return MethodContract(tuple(behaviors), tuple(clauses))
