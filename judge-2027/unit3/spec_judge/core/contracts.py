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
class MethodSignature:
    return_type: str
    parameters: tuple[tuple[str, str], ...]
    is_static: bool
    exceptions: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class MethodDeclaration:
    start: int
    end: int
    signature: MethodSignature


@dataclasses.dataclass(frozen=True)
class MethodContract:
    behaviors: tuple[Behavior, ...]
    clauses: tuple[Clause, ...] = ()
    signature: MethodSignature | None = None

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


_JML_BLOCK = re.compile(r"/\*@(?P<body>.*?)@\*/", re.DOTALL)
_NON_CODE = re.compile(
    r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
    re.DOTALL,
)
_IDENTIFIER = r"[A-Za-z_$][\w$]*"
_TYPE = _IDENTIFIER + r"(?:\." + _IDENTIFIER + r")*(?:\s*\[\s*\])*"
_MODIFIERS = r"public|protected|private|static|final|abstract|default|synchronized|native|strictfp"
_DECLARATION_MARKERS = {"safe", "pure"}


def _mask_non_code(source: str) -> str:
    return _NON_CODE.sub(
        lambda match: "".join("\n" if char == "\n" else " " for char in match.group()),
        source,
    )


def _jml_blocks(source: str) -> list[re.Match[str]]:
    blocks = []
    for token in _NON_CODE.finditer(source):
        if token.group().startswith("/*@"):
            block = _JML_BLOCK.fullmatch(source, token.start(), token.end())
            if block is None:
                raise SpecError("JML 块必须以 /*@ 开始并以 @*/ 结束")
            blocks.append(block)
    return blocks


def _method_declaration(java_source: str, method_name: str) -> MethodDeclaration:
    masked = _mask_non_code(java_source)
    pattern = re.compile(
        r"(?:^|(?<=[{};]))\s*(?P<declaration>"
        r"(?:@" + _IDENTIFIER + r"(?:\." + _IDENTIFIER + r")*\s+)*"
        r"(?P<modifiers>(?:(?:" + _MODIFIERS + r")\s+)*)"
        r"(?P<return>" + _TYPE + r")\s+" + re.escape(method_name)
        + r"\s*\((?P<parameters>[^()]*)\)\s*"
        r"(?:throws\s+(?P<exceptions>" + _IDENTIFIER + r"(?:\." + _IDENTIFIER
        + r")*(?:\s*,\s*" + _IDENTIFIER + r"(?:\." + _IDENTIFIER + r")*)*)\s*)?"
        r")[;{]",
    )
    matches = [
        match for match in pattern.finditer(masked)
        if match.group("return") not in {"return", "throw", "new", "yield", "assert"}
    ]
    if len(matches) != 1:
        raise SpecError(f"目标方法 {method_name} 必须有且只有一个可识别的声明，实际找到 {len(matches)} 个")
    match = matches[0]
    parameters: list[tuple[str, str]] = []
    text = match.group("parameters").strip()
    for parameter in text.split(",") if text else ():
        parsed = re.fullmatch(
            r"\s*(?:final\s+)?(?P<type>" + _TYPE + r")\s+(?P<name>"
            + _IDENTIFIER + r")(?P<arrays>(?:\s*\[\s*\])*)\s*", parameter,
        )
        if parsed is None:
            raise SpecError(f"方法 {method_name} 的参数声明不在支持范围内：{parameter.strip()}")
        parameter_type = re.sub(r"\s+", "", parsed.group("type") + parsed.group("arrays"))
        parameters.append((parameter_type, parsed.group("name")))
    for marker in _jml_blocks(java_source):
        if not (match.start("declaration") <= marker.start() < match.end()):
            continue
        if marker.group("body").strip() not in _DECLARATION_MARKERS:
            raise SpecError("方法签名中的 JML 标记仅支持 safe 和 pure")
    return MethodDeclaration(
        match.start("declaration"), match.end(),
        MethodSignature(
            re.sub(r"\s+", "", match.group("return")), tuple(parameters),
            "static" in match.group("modifiers").split(),
            tuple(sorted(re.sub(r"\s+", "", value)
                         for value in (match.group("exceptions") or "").split(",") if value.strip())),
        ),
    )


def _method_declaration_start(java_source: str, method_name: str) -> int:
    return _method_declaration(java_source, method_name).start


def _extract_jml_match(java_source: str, method_name: str) -> re.Match[str]:
    blocks = _jml_blocks(java_source)
    declaration = _method_declaration(java_source, method_name)
    declaration_start = declaration.start
    masked = _mask_non_code(java_source)
    for block in reversed(blocks):
        if block.end() > declaration_start:
            continue
        if masked[block.end():declaration_start].strip():
            break
        if block.group("body").strip() in _DECLARATION_MARKERS:
            continue
        if any(token.group().startswith("//@") for token in _NON_CODE.finditer(
            java_source, block.end(), declaration.end,
        )):
            raise SpecError("目标方法的合同不支持 //@ 行注释；请合并为一个 JML 块")
        for previous in reversed(blocks):
            if previous.end() > block.start():
                continue
            if masked[previous.end():block.start()].strip():
                break
            if previous.group("body").strip() not in _DECLARATION_MARKERS:
                raise SpecError("目标方法前存在多个相邻 JML 块；请将行为合同合并为一个块")
        return block
    raise SpecError(f"未找到紧邻方法 {method_name} 的 JML 注释块")


def extract_jml_block(java_source: str, method_name: str) -> str:
    return _extract_jml_match(java_source, method_name).group("body")


def extract_clauses(block: str, line_offset: int = 0) -> list[Clause]:
    cleaned = "\n".join(re.sub(r"^\s*@\s?", "", line).rstrip() for line in block.splitlines())
    # Consume the complete block. A regex search for known keywords used to
    # silently discard signals_only, invariants and arbitrary trailing text.
    clauses: list[Clause] = []
    position = 0
    behavior_index = 0
    behavior_kind = "generic"
    header_seen = False
    after_also = False
    behavior_has_clause = False
    while position < len(cleaned):
        if cleaned[position].isspace():
            position += 1
            continue
        line = line_offset + cleaned.count("\n", 0, position) + 1
        rest = cleaned[position:]
        also = re.match(r"also\b", rest)
        if also:
            if not behavior_has_clause:
                raise SpecError(f"第 {line} 行 also 前没有完整行为")
            behavior_index += 1
            behavior_kind = "generic"
            header_seen = False
            after_also = True
            behavior_has_clause = False
            position += also.end()
            continue
        header = re.match(r"(?:public\s+)?(normal_behavior|exceptional_behavior|behavior)\b", rest)
        if header:
            if header_seen or behavior_has_clause:
                raise SpecError(f"第 {line} 行的新行为缺少 also 分隔")
            behavior_kind = header.group(1).removesuffix("_behavior")
            header_seen = True
            position += header.end()
            continue
        start = re.match(r"(requires|ensures|signals|assignable)\b\s*", rest)
        if start is None:
            token = re.match(r"\S+", rest).group()[:60]
            raise SpecError(f"第 {line} 行不支持的 JML 条款或文本：{token}")
        body_start = position + start.end()
        depth = 0
        for index in range(body_start, len(cleaned)):
            char = cleaned[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    raise SpecError(f"第 {line} 行的 {start.group(1)} 子句括号不匹配")
            elif char == ";" and depth == 0:
                clauses.append(Clause(
                    start.group(1), re.sub(r"\s+", " ", cleaned[body_start:index]).strip(), line,
                    behavior_index, behavior_kind,
                ))
                position = index + 1
                behavior_has_clause = True
                after_also = False
                break
        else:
            raise SpecError(f"第 {line} 行的 {start.group(1)} 子句缺少分号")
    if (header_seen or after_also) and not behavior_has_clause:
        raise SpecError("JML 合同末尾有未完成的行为")
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
    declaration = _method_declaration(java_source, method_name)
    expected_parameters = dict(profile.parameter_types(method_name))
    actual_parameters = tuple(
        (name, {"boolean": "bool", "String": "string"}.get(kind, kind))
        for kind, name in declaration.signature.parameters
    )
    if len(actual_parameters) != len(expected_parameters) or dict(actual_parameters) != expected_parameters:
        raise SpecError(f"目标方法 {method_name} 的参数名称或类型与 Suite 不一致")
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
    if not behaviors:
        raise SpecError("目标方法的 JML 合同没有受支持的行为子句")
    return MethodContract(tuple(behaviors), tuple(clauses), declaration.signature)
