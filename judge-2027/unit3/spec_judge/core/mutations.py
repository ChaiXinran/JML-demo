"""Small deterministic mutation set for measuring suite discrimination power."""

from __future__ import annotations

import dataclasses
import re

from .contracts import extract_jml_block
from .errors import SpecError
from .expressions import Binary, Call, Expr, ExpressionParser, Literal, Old, Unary, Variable


@dataclasses.dataclass(frozen=True)
class ContractMutation:
    id: str
    source: str


def _single_replacements(
    source: str, block_start: int, block: str, pattern: str, replacement, label: str
) -> list[ContractMutation]:
    result: list[ContractMutation] = []
    for index, match in enumerate(re.finditer(pattern, block), start=1):
        value = replacement(match) if callable(replacement) else replacement
        absolute_start = block_start + match.start()
        absolute_end = block_start + match.end()
        mutated = source[:absolute_start] + value + source[absolute_end:]
        result.append(ContractMutation(f"{label}.{index}", mutated))
    return result


def _render(expression: Expr) -> str:
    if isinstance(expression, Literal):
        if isinstance(expression.value, bool):
            return "true" if expression.value else "false"
        return str(expression.value)
    if isinstance(expression, Variable):
        return expression.name
    if isinstance(expression, Call):
        return f"{expression.name}({', '.join(_render(item) for item in expression.args)})"
    if isinstance(expression, Unary):
        return f"!({_render(expression.operand)})"
    if isinstance(expression, Old):
        return f"\\old({_render(expression.expression)})"
    if isinstance(expression, Binary):
        return f"({_render(expression.left)} {expression.operator} {_render(expression.right)})"
    raise TypeError(type(expression).__name__)


def _delete_conjuncts(expression: Expr) -> list[Expr]:
    # Delete one top-level side only.  Recursively deleting nested terms often
    # creates equivalent mutants (for example, id1 == id2 makes the two user
    # existence predicates interchangeable), which distorts a point suite's
    # mutation score.
    if isinstance(expression, Binary) and expression.operator == "&&":
        return [expression.left, expression.right]
    return []


def _structured_condition_deletions(
    java_source: str, block_start: int, block: str
) -> list[ContractMutation]:
    starts = list(re.finditer(r"(?m)^\s*@?\s*(requires|ensures|signals)\b\s*", block))
    mutations: list[ContractMutation] = []
    mutation_index = 0
    for start in starts:
        depth = 0
        end = None
        for index in range(start.end(), len(block)):
            char = block[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif char == ";" and depth == 0:
                end = index
                break
        if end is None:
            continue
        raw_body = block[start.end():end]
        body = re.sub(r"\s*@\s?", " ", raw_body).strip()
        prefix = ""
        if start.group(1) == "signals":
            match = re.match(r"^(\([A-Za-z_]\w*\s+[A-Za-z_]\w*\)\s*)(.+)$", body)
            if match is None:
                continue
            prefix, body = match.groups()
        if body.startswith("(* output->"):
            continue
        try:
            expression = ExpressionParser(body).parse()
        except SpecError:
            continue
        for replacement in _delete_conjuncts(expression):
            mutation_index += 1
            absolute_start = block_start + start.end()
            absolute_end = block_start + end
            replacement_text = " " + prefix + _render(replacement)
            mutations.append(ContractMutation(
                f"delete_conjunct.{mutation_index}",
                java_source[:absolute_start] + replacement_text + java_source[absolute_end:],
            ))
    return mutations


def generate_contract_mutations(java_source: str, method_name: str) -> tuple[ContractMutation, ...]:
    """Return reproducible one-site mutants inside the target JML block.

    The set intentionally stays syntax-subset agnostic: it targets the common
    boolean/comparison operators plus assignable widening.  A killed mutant is
    evidence that at least one configured observation distinguishes that fault;
    a surviving mutant is a prompt to inspect or extend the suite.
    """
    block = extract_jml_block(java_source, method_name)
    block_start = java_source.find(block)
    mutations: list[ContractMutation] = []
    mutations.extend(_structured_condition_deletions(java_source, block_start, block))
    mutations.extend(_single_replacements(
        java_source, block_start, block, r"&&", "||", "and_to_or"
    ))
    mutations.extend(_single_replacements(
        java_source, block_start, block, r"\|\|", "&&", "or_to_and"
    ))
    comparison_flips = {
        "==": "!=", "!=": "==", "<=": ">", ">=": "<", "<": ">=", ">": "<=",
    }
    mutations.extend(_single_replacements(
        java_source,
        block_start,
        block,
        r"==|!=|<=|>=|(?<![<>=])<(?![=])|(?<![<>=])>(?![=])",
        lambda match: comparison_flips[match.group()],
        "flip_comparison",
    ))
    mutations.extend(_single_replacements(
        java_source, block_start, block, r"!(?!=)", "", "remove_not"
    ))
    mutations.extend(_single_replacements(
        java_source,
        block_start,
        block,
        r"\b(?:true|false)\b",
        lambda match: "false" if match.group() == "true" else "true",
        "flip_boolean",
    ))
    mutations.extend(_single_replacements(
        java_source,
        block_start,
        block,
        r"(?m)(?<=assignable)\s+[^;]+",
        " \\everything",
        "widen_frame",
    ))
    mutations.extend(_single_replacements(
        java_source,
        block_start,
        block,
        r"\b([A-Za-z_]\w*)\(\s*([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s*\)",
        lambda match: f"{match.group(1)}({match.group(3)}, {match.group(2)})",
        "swap_arguments",
    ))
    old_index = 0
    search_start = 0
    while True:
        match = re.search(r"\\old\s*\(", block[search_start:])
        if match is None:
            break
        opening = search_start + match.end() - 1
        depth = 1
        closing = opening + 1
        while closing < len(block) and depth:
            if block[closing] == "(":
                depth += 1
            elif block[closing] == ")":
                depth -= 1
            closing += 1
        if depth == 0:
            old_index += 1
            start = search_start + match.start()
            inner = block[opening + 1:closing - 1]
            absolute_start = block_start + start
            absolute_end = block_start + closing
            mutations.append(ContractMutation(
                f"remove_old.{old_index}",
                java_source[:absolute_start] + inner + java_source[absolute_end:],
            ))
        search_start = opening + 1
    unique: dict[str, ContractMutation] = {}
    for mutation in mutations:
        if mutation.source != java_source:
            unique.setdefault(mutation.source, mutation)
    return tuple(unique.values())
