"""Deterministically derive a student interface from complete staff JML."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path


CLAUSE_RE = re.compile(
    r"(?m)^(?P<prefix>\s*@\s*)(?P<keyword>requires|ensures|signals|assignable)\b"
)
IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

DEFAULT_ALLOWED_MODES = ["hint", "review"]
DEFAULT_FEEDBACK_CONTRACT = {
    "hint": {
        "level": "guided",
        "reveals": ["one highest-priority category", "one direct repair direction"],
        "never_reveals": ["replacement clause", "reference JML", "state snapshot", "hidden mutations"],
    },
    "review": {
        "level": "detailed",
        "reveals": ["blank location", "category", "abstract counterexample shape", "repair direction"],
        "never_reveals": ["replacement clause", "reference JML", "complete state", "hidden mutations"],
    },
}
JML_KEYWORDS = {
    "also", "assignable", "ensures", "exceptional_behavior", "false", "normal_behavior",
    "nothing", "old", "public", "pure", "requires", "signals", "true",
}


def _semicolon_at_top_level(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            return index
    raise ValueError("Unterminated JML clause in authoritative interface")


def _method_jml_span(source: str, method_name: str) -> tuple[int, int]:
    for match in re.finditer(r"/\*@.*?@\*/", source, re.DOTALL):
        after = source[match.end():]
        declaration = re.match(
            rf"\s*public\s+(?:/\*@.*?@\*/\s*)?[^;{{]+?\b{re.escape(method_name)}\s*\(",
            after,
            re.DOTALL,
        )
        if declaration:
            return match.start(), match.end()
    raise ValueError(f"Cannot find an embedded JML block immediately before {method_name}")


def _clause_spans(jml_block: str, keyword: str) -> list[tuple[int, int]]:
    spans = []
    for match in CLAUSE_RE.finditer(jml_block):
        if match.group("keyword") != keyword:
            continue
        end = _semicolon_at_top_level(jml_block, match.end())
        spans.append((match.end(), end))
    return spans


def build_template(source: str, method_name: str, blank_plan: dict) -> str:
    """Replace approved existing clause bodies with named placeholders.

    The operation is intentionally local: it preserves the original Java file,
    all non-selected JML, and clause prefixes such as `signals (E e)`.
    """
    start, end = _method_jml_span(source, method_name)
    block = source[start:end]
    replacements: list[tuple[int, int, str]] = []
    for item in blank_plan["student_owned_blanks"]:
        selector = item["source_jml_selector"]
        occurrence = selector["occurrence"]
        keyword = selector["clause"]
        clauses = _clause_spans(block, keyword)
        if occurrence < 1 or occurrence > len(clauses):
            raise ValueError(f"No {keyword} clause #{occurrence} for blank {item['id']}")
        body_start, body_end = clauses[occurrence - 1]
        if keyword == "signals":
            exception_match = re.match(r"\s*\([^)]*\)", block[body_start:body_end])
            if not exception_match:
                raise ValueError(f"signals clause for {item['id']} has no exception declaration")
            body_start += exception_match.end()
        replacements.append((body_start, body_end, " {{" + item["id"] + "}}"))
    for body_start, body_end, placeholder in sorted(replacements, reverse=True):
        block = block[:body_start] + placeholder + block[body_end:]
    return source[:start] + block + source[end:]


def build_template_file(interface_file: Path, method_name: str, blank_plan_file: Path, output: Path) -> None:
    plan = json.loads(blank_plan_file.read_text(encoding="utf-8"))
    if plan.get("status") != "teacher_approved":
        raise ValueError("blank_plan.json must be teacher_approved before generating a student template")
    result = build_template(interface_file.read_text(encoding="utf-8"), method_name, plan)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result, encoding="utf-8")


def _method_name_from_blank_plan(blank_plan: dict) -> str:
    declared = blank_plan.get("method")
    if not isinstance(declared, str) or not declared.strip():
        raise ValueError("blank_plan.json must declare the target method as Interface.method")
    return declared.rsplit(".", maxsplit=1)[-1]


def _public_symbols(source: str, method_name: str) -> list[str]:
    """Derive the public symbol context shown to the learning assistant."""
    start, end = _method_jml_span(source, method_name)
    block = source[start:end]
    symbols = {
        token
        for token in IDENTIFIER_RE.findall(block)
        if token not in JML_KEYWORDS and len(token) > 1
    }
    for exception_declaration in re.finditer(r"signals\s*\((?P<type>[A-Za-z_]\w*)\s+\w+\)", block):
        symbols.add(exception_declaration.group("type"))
    return sorted(symbols)


def _semantic_suite_path(semantic_suite: Path, method_name: str) -> str:
    """Validate a server-side suite and store its path relative to Agent/."""
    if not semantic_suite.is_file():
        raise FileNotFoundError(f"Semantic suite does not exist: {semantic_suite}")
    try:
        suite = json.loads(semantic_suite.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Semantic suite must use JSON-compatible YAML: {semantic_suite}") from error
    if not isinstance(suite, dict) or suite.get("method") != method_name:
        raise ValueError(f"Semantic suite method must be {method_name}: {semantic_suite}")
    project_root = Path(__file__).resolve().parent.parent
    try:
        relative = os.path.relpath(semantic_suite.resolve(), project_root)
    except ValueError as error:
        raise ValueError("Semantic suite must be on the same filesystem as Agent/") from error
    return Path(relative).as_posix()


def build_exercise_package(
    interface_file: Path,
    requirement_file: Path,
    blank_plan_file: Path,
    exercise_dir: Path,
    title: str | None = None,
    semantic_suite: Path | None = None,
) -> None:
    """Create the public exercise assets from the three staff-authored inputs.

    The destination must be new so this deterministic generator never silently
    replaces a released student package or its optional demonstration samples.
    """
    if exercise_dir.exists():
        raise FileExistsError(f"Exercise directory already exists: {exercise_dir}")
    plan = json.loads(blank_plan_file.read_text(encoding="utf-8"))
    if plan.get("status") != "teacher_approved":
        raise ValueError("blank_plan.json must be teacher_approved before publishing an exercise")
    method_name = _method_name_from_blank_plan(plan)
    source = interface_file.read_text(encoding="utf-8")
    template = build_template(source, method_name, plan)
    placeholders = [item["id"] for item in plan["student_owned_blanks"]]
    if len(placeholders) != len(set(placeholders)):
        raise ValueError("blank_plan.json contains duplicate placeholder ids")
    if not requirement_file.is_file():
        raise FileNotFoundError(f"Requirement file does not exist: {requirement_file}")
    suite_path = _semantic_suite_path(semantic_suite, method_name) if semantic_suite else None

    exercise_dir.mkdir(parents=True)
    (exercise_dir / "samples").mkdir()
    (exercise_dir / "template.java").write_text(template, encoding="utf-8")
    shutil.copyfile(requirement_file, exercise_dir / "requirement.md")
    manifest = {
        "id": exercise_dir.name,
        "title": title or f"{method_name} JML 填空练习",
        "method": method_name,
        "allowed_modes": DEFAULT_ALLOWED_MODES,
        "default_mode": "hint",
        "feedback_contract": DEFAULT_FEEDBACK_CONTRACT,
        "placeholders": placeholders,
        "allowed_symbols": _public_symbols(source, method_name),
    }
    if suite_path is not None:
        manifest["semantic_suite"] = suite_path
    (exercise_dir / "exercise.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
