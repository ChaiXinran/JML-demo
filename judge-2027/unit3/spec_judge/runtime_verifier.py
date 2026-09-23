"""Bounded runtime counterexamples for the supported network fixture.

This module intentionally implements a narrow teacher-side adapter instead of
pretending to execute arbitrary Java object graphs.  It shares the submitted
JML binding helper with the OpenJML ESC chain, compiles the bound source with
OpenJML RAC, executes one generated runner, and then checks the observed
transition with the existing Profile semantics.
"""

from __future__ import annotations

import dataclasses
import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from consistency_judge import (
    _bind_student_jml,
    _decode_tool_output,
    check_jml_java,
)
from core.errors import SpecError
from core.judge import normal_applicable
from core.profile import ProfileError, Scenario
from core.suite import LoadedSuite, load_suite
from profiles.network_v1 import NetworkState
from profiles.registry import PROFILES
from semantic_judge import evaluate as evaluate_expression, parse_contract
from verification_evidence import Evidence, VerificationSession, sha256_file


@dataclasses.dataclass(frozen=True)
class RuntimeCandidate:
    id: str
    arguments: dict[str, int]
    pre: NetworkState
    tags: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Violation:
    code: str
    kind: str
    message: str
    clause_index: int | None = None
    line: int | None = None
    obligation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class RuntimeResult:
    candidate_id: str
    replay_status: str
    phase: str
    pre_state: Mapping[str, Any] | None = None
    post_state: Mapping[str, Any] | None = None
    exception: str | None = None
    arguments: Mapping[str, int] = dataclasses.field(default_factory=dict)
    tags: tuple[str, ...] = ()
    rac_failure: bool = False
    failure_signature: str | None = None
    execution_status: str = ""
    conclusion: str = ""
    evidence_origin: tuple[str, ...] = ()
    confirmation_status: str = "NOT_RUN"
    violations: tuple[Violation, ...] = ()
    evidence: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "replay_status": self.replay_status,
            "phase": self.phase,
            "pre_state": self.pre_state,
            "post_state": self.post_state,
            "exception": self.exception,
            "arguments": dict(self.arguments),
            "tags": list(self.tags),
            "rac_failure": self.rac_failure,
            "failure_signature": self.failure_signature,
            "execution_status": self.execution_status or (
                "ERROR" if self.replay_status in {"ERROR", "UNLOCATED_FAILURE"}
                else "COMPLETED"
            ),
            "conclusion": self.conclusion or {
                "REPRODUCED": "CONFIRMED_VIOLATION",
                "NOT_FOUND_WITHIN_BOUNDS": "NO_OBSERVED_VIOLATION",
                "UNLOCATED_FAILURE": "FAILURE_OBSERVED_UNLOCATED",
                "ERROR": "EXECUTION_ERROR",
            }.get(self.replay_status, "NOT_RUN"),
            "evidence_origin": list(self.evidence_origin),
            "confirmation_status": self.confirmation_status,
            "violations": [item.to_dict() for item in self.violations],
            "evidence": dict(self.evidence),
        }


RUNTIME_SUPPORT_MATRIX = {
    "requires": {
        "static": "supported",
        "runtime": "supported",
        "note": "由绑定后的 OpenJML 合同和抽象前置条件共同检查。",
    },
    "ensures": {
        "static": "supported",
        "runtime": "supported",
        "note": "RAC 检查实际执行路径，Profile 再对可观察前后状态确认。",
    },
    "assignable": {
        "static": "supported",
        "runtime": "supported_by_rac",
        "note": "首版不提供独立写入监测；运行 frame 证据来自 OpenJML RAC。",
    },
    "signals": {
        "static": "supported",
        "runtime": "not_in_scope",
        "note": "unfollowUser 首版合同不含异常行为；新增 signals 时拒绝静默忽略。",
    },
    "output": {
        "static": "not_in_scope",
        "runtime": "not_in_scope",
        "note": "本适配器不把控制台输出约定当作 JML 运行证据。",
    },
}


class UnfollowUserExecutionAdapter:
    """Adapter for ``UnfollowUserRuntimeDemo``-shaped implementations."""

    method = "unfollowUser"
    universe_size = 4

    @staticmethod
    def support_matrix() -> dict[str, dict[str, str]]:
        return {name: dict(value) for name, value in RUNTIME_SUPPORT_MATRIX.items()}

    def validate_source(self, source: str) -> str:
        without_comments = re.sub(
            r"/\*.*?\*/|//[^\n]*",
            lambda match: "".join("\n" if char == "\n" else " " for char in match.group()),
            source,
            flags=re.DOTALL,
        )
        class_match = re.search(r"\bclass\s+(?P<name>[A-Za-z_]\w*)\b", without_comments)
        if class_match is None:
            raise ValueError("执行适配器要求 Java 源包含一个 class")
        if re.search(r"\bpackage\s+", source):
            raise ValueError("首版执行适配器暂不支持 package 声明")
        required = (
            r"\bUser\[\]\s+users\b",
            r"\bvoid\s+unfollowUser\s*\(\s*int\s+\w+\s*,\s*int\s+\w+\s*\)",
            rf"\b{re.escape(class_match.group('name'))}\s*\(\s*int\s+\w+\s*\)",
        )
        for pattern in required:
            if re.search(pattern, source) is None:
                raise ValueError(f"Java 实现不符合 unfollowUser 适配器形状：{pattern}")
        return class_match.group("name")

    def state_to_java(self, state: NetworkState) -> str:
        if not state.users.issubset(set(range(self.universe_size))):
            raise ValueError(
                f"前态用户 ID 必须属于 0..{self.universe_size - 1}，实际为 {sorted(state.users)}"
            )
        lines = [
            f"subject.users[{user}] = null;"
            for user in range(self.universe_size)
        ]
        lines.extend(
            f"subject.users[{user}] = new {self._user_type_placeholder()}({user}, {self.universe_size});"
            for user in sorted(state.users)
        )
        for source, targets in sorted(state.following.items()):
            for target in sorted(targets):
                if source not in state.users or target not in state.users:
                    raise ValueError("following 关系的端点必须存在于前态用户集合")
                lines.append(f"subject.users[{source}].following[{target}] = true;")
        for user, followers in sorted(state.followers.items()):
            for follower in sorted(followers):
                if user not in state.users or follower not in state.users:
                    raise ValueError("followers 关系的端点必须存在于前态用户集合")
                lines.append(f"subject.users[{user}].followers[{follower}] = true;")
        return "\n        ".join(lines)

    @staticmethod
    def _user_type_placeholder() -> str:
        return "__USER_TYPE__"

    def runner_source(self, subject_name: str, candidate: RuntimeCandidate) -> str:
        setup = self.state_to_java(candidate.pre).replace(
            self._user_type_placeholder(), f"{subject_name}.User"
        )
        id1 = candidate.arguments["id1"]
        id2 = candidate.arguments["id2"]
        return f'''

public class UnfollowUserRuntimeRunner {{
    private static String presentUsers({subject_name} subject) {{
        StringBuilder out = new StringBuilder();
        for (int id = 0; id < subject.users.length; id++) {{
            if (subject.users[id] != null) {{
                if (out.length() > 0) out.append(",");
                out.append(id);
            }}
        }}
        return out.toString();
    }}

    private static String relation({subject_name} subject, boolean forward) {{
        StringBuilder out = new StringBuilder();
        for (int first = 0; first < subject.users.length; first++) {{
            if (subject.users[first] == null) continue;
            boolean[] row = forward ? subject.users[first].following : subject.users[first].followers;
            for (int second = 0; second < row.length; second++) {{
                if (row[second]) {{
                    if (out.length() > 0) out.append(",");
                    out.append(first).append(">").append(second);
                }}
            }}
        }}
        return out.toString();
    }}

    public static void main(String[] args) {{
        {subject_name} subject = new {subject_name}({self.universe_size});
        {setup}
        String exceptionName = "NONE";
        System.out.println("BEFORE|users=" + presentUsers(subject)
            + "|following=" + relation(subject, true)
            + "|followers=" + relation(subject, false));
        try {{
            subject.unfollowUser({id1}, {id2});
        }} catch (Throwable error) {{
            exceptionName = error.getClass().getName() + ":" + error.getMessage();
        }}
        System.out.println("RESULT|users=" + presentUsers(subject)
            + "|following=" + relation(subject, true)
            + "|followers=" + relation(subject, false)
            + "|exception=" + exceptionName);
    }}
}}
'''

    def observe(self, state_text: str) -> NetworkState:
        fields = dict(item.split("=", 1) for item in state_text.split("|") if "=" in item)
        users = {
            int(value) for value in fields.get("users", "").split(",") if value
        }
        following = {user: set() for user in users}
        followers = {user: set() for user in users}
        for raw_edge in fields.get("following", "").split(","):
            if raw_edge:
                first, second = map(int, raw_edge.split(">"))
                following.setdefault(first, set()).add(second)
        for raw_edge in fields.get("followers", "").split(","):
            if raw_edge:
                first, second = map(int, raw_edge.split(">"))
                followers.setdefault(first, set()).add(second)
        return NetworkState(users, following, followers, {user: set() for user in users})

    def check_roundtrip(self, expected: NetworkState, observed: NetworkState) -> None:
        if expected != observed:
            raise ValueError("Java 对象构造后的可观察状态与抽象前态不一致")


class UnfollowUserCandidateGenerator:
    """Generate only legal, deterministic normal-entry candidates."""

    def __init__(self, adapter: UnfollowUserExecutionAdapter | None = None):
        self.adapter = adapter or UnfollowUserExecutionAdapter()
        self.generated_count = 0
        self.skipped_count = 0

    @staticmethod
    def _state(users: Iterable[int], edges: Iterable[tuple[int, int]]) -> NetworkState:
        present = set(users)
        following = {user: set() for user in present}
        followers = {user: set() for user in present}
        for first, second in edges:
            following[first].add(second)
            followers[second].add(first)
        return NetworkState(present, following, followers, {user: set() for user in present})

    def generate(self, contract, profile) -> tuple[RuntimeCandidate, ...]:
        candidates = (
            RuntimeCandidate(
                "linked_two_users",
                {"id1": 0, "id2": 1},
                self._state((0, 1), ((0, 1),)),
                ("normal", "two-users"),
            ),
            RuntimeCandidate(
                "linked_with_unrelated_relation",
                {"id1": 0, "id2": 1},
                self._state((0, 1, 2), ((0, 1), (2, 0)),),
                ("normal", "unrelated-edge"),
            ),
            RuntimeCandidate(
                "linked_with_reverse_relation",
                {"id1": 0, "id2": 1},
                self._state((0, 1, 2), ((0, 1), (1, 0)),),
                ("normal", "reverse-edge"),
            ),
        )
        self.generated_count = len(candidates)
        accepted = []
        for candidate in candidates:
            scenario = Scenario(candidate.pre, candidate.pre.copy(), candidate.arguments, candidate.id)
            if normal_applicable(contract, scenario, profile):
                accepted.append(candidate)
        self.skipped_count = len(candidates) - len(accepted)
        return tuple(accepted)


class ViolationChecker:
    def check(self, contract, candidate: RuntimeCandidate, post: NetworkState, profile) -> tuple[Violation, ...]:
        scenario = Scenario(candidate.pre, post, candidate.arguments, candidate.id)
        context = scenario.context()
        violations: list[Violation] = []
        if not normal_applicable(contract, scenario, profile):
            return ()
        ensure_offset = 0
        ensure_clauses = [
            clause for clause in contract.clauses
            if clause.kind == "ensures" and clause.behavior_kind != "exceptional"
        ]
        for behavior in contract.normal_behaviors:
            if not all(bool(evaluate_expression(item, context.pre_state(), profile)) for item in behavior.requires):
                ensure_offset += len(behavior.ensures)
                continue
            for index, expression in enumerate(behavior.ensures):
                if bool(evaluate_expression(expression, context, profile)):
                    continue
                lines = contract.lines_for("ensures", normal_only=True)
                clause = ensure_clauses[ensure_offset + index] if ensure_offset + index < len(ensure_clauses) else None
                violations.append(Violation(
                    "POSTCONDITION_VIOLATION",
                    "postcondition",
                    "运行后的状态不满足绑定 JML 后置条件。",
                    ensure_offset + index,
                    lines[ensure_offset + index] if ensure_offset + index < len(lines) else None,
                    (
                        f"ensures:behavior-{clause.behavior_index}:clause-"
                        f"{sum(1 for item in ensure_clauses[:ensure_offset + index] if item.behavior_index == clause.behavior_index) + 1}"
                        if clause is not None else None
                    ),
                ))
            ensure_offset += len(behavior.ensures)
        return tuple(violations)


class RuntimeExecutor:
    """Compile and run one candidate with OpenJML RAC."""

    def __init__(self, openjml: str = "openjml", timeout: int = 10):
        self.openjml = openjml
        self.timeout = timeout

    @staticmethod
    def _is_rac_failure(exception: str) -> bool:
        lowered = exception.lower()
        return any(token in lowered for token in (
            "jml", "assertion", "precondition", "postcondition", "assignable",
            "frame condition",
        ))

    @staticmethod
    def _rac_failure_signature(output: str, method_name: str, exception: str | None = None) -> str | None:
        """Extract a stable identity for a JML runtime failure.

        RAC may report a violated clause on stderr while the runner itself
        still exits normally and emits ``exception=NONE``.  A broad
        ``exception != NONE`` check therefore misses real failures.  The
        signature deliberately keeps the check kind and the normalized
        diagnostic line, so a postcondition failure cannot confirm a later
        helper precondition failure.
        """

        lines = [re.sub(r"\s+", " ", line).strip() for line in output.splitlines()]
        markers = (
            ("precondition", "precondition"),
            ("postcondition", "postcondition"),
            ("assignable", "assignable"),
            ("frame condition", "frame"),
            ("invariant", "invariant"),
            ("assertion", "assertion"),
        )
        failure_words = ("false", "violat", "failed", "failure", "error")
        for line in lines:
            lowered = line.lower()
            kind = next((name for token, name in markers if token in lowered), None)
            if kind is None or not any(word in lowered for word in failure_words):
                continue
            # Prefer a stable source location over the full diagnostic text.
            # Temporary paths and wording around the same obligation are tool
            # noise; the original output remains in evidence for inspection.
            location = re.search(r"(?:^|\s)(?:at|:)(?:[^\s:]+:)?(?P<line>\d+)(?::\d+)?", lowered)
            if location is not None:
                return f"{method_name}|obligation={kind}|source_line={location.group('line')}"
            normalized = re.sub(r"[A-Za-z]:\\[^ ]+|/[^ ]+", "<path>", lowered)
            return f"{method_name}|obligation={kind}|unlocated|{normalized}"
        if exception and RuntimeExecutor._is_rac_failure(exception):
            lowered = re.sub(r"\s+", " ", exception.lower()).strip()
            return f"{method_name}|exception|unlocated|{lowered}"
        return None

    @staticmethod
    def _rac_failure_is_located(signature: str | None) -> bool:
        return bool(signature) and "|unlocated|" not in signature

    @staticmethod
    def _windows_to_wsl(path: Path) -> str:
        match = re.match(r"^(?P<drive>[A-Za-z]):\\(?P<rest>.*)$", str(path.resolve()))
        if match is None:
            raise ValueError(f"无法转换为 WSL 路径：{path}")
        return f"/mnt/{match.group('drive').lower()}/" + match.group("rest").replace("\\", "/")

    def _commands(
        self, bound: Path, runner: Path, classes: Path
    ) -> tuple[list[str], list[str], list[str]]:
        if self.openjml.startswith("wsl:"):
            executable = self.openjml.removeprefix("wsl:")
            compile_tool = posixpath.join(posixpath.dirname(executable), "openjml-compile")
            run_tool = posixpath.join(posixpath.dirname(executable), "openjml-java")
            classpath = self._windows_to_wsl(classes)
            rac_compile_command = [
                "wsl.exe", "bash", compile_tool, "--rac", "--rac-show-source=source",
                "-d", classpath, self._windows_to_wsl(bound),
            ]
            runner_compile_command = [
                "wsl.exe", "bash", compile_tool, "-cp", classpath,
                "-d", classpath, self._windows_to_wsl(runner),
            ]
            run_command = ["wsl.exe", "bash", run_tool, "-cp", classpath, "UnfollowUserRuntimeRunner"]
            return rac_compile_command, runner_compile_command, run_command
        rac_compile_command = [
            self.openjml, "--rac", "--rac-show-source=source", "-d", str(classes), str(bound)
        ]
        runner_compile_command = [
            self.openjml, "--compile", "-cp", str(classes), "-d", str(classes), str(runner)
        ]
        runtime = str(Path(self.openjml).with_name("openjml-java")) if Path(self.openjml).parent != Path(".") else "java"
        run_command = [runtime, "-cp", str(classes), "UnfollowUserRuntimeRunner"]
        return rac_compile_command, runner_compile_command, run_command

    def execute(
        self,
        candidate: RuntimeCandidate,
        student_java: Path,
        student_jml: Path,
        method_name: str,
        adapter: UnfollowUserExecutionAdapter,
    ) -> RuntimeResult:
        temporary: tempfile.TemporaryDirectory[str] | None = None
        try:
            source = student_java.read_text(encoding="utf-8")
            subject_name = adapter.validate_source(source)
            bound, temporary, binding = _bind_student_jml(student_jml, student_java, method_name)
            runner = Path(temporary.name) / "UnfollowUserRuntimeRunner.java"
            runner.write_text(adapter.runner_source(subject_name, candidate), encoding="utf-8")
            classes = Path(temporary.name) / "classes"
            classes.mkdir()
            compile_command, runner_compile_command, run_command = self._commands(bound, runner, classes)
            compiled = subprocess.run(
                compile_command, capture_output=True, text=False,
                timeout=self.timeout, check=False,
            )
            compile_output = "\n".join(
                part for part in (_decode_tool_output(compiled.stdout), _decode_tool_output(compiled.stderr)) if part
            ).strip()
            if compiled.returncode != 0:
                return RuntimeResult(
                    candidate.id, "ERROR", "rac_compile",
                    arguments=candidate.arguments, tags=candidate.tags,
                    execution_status="ERROR", conclusion="EXECUTION_ERROR",
                    evidence={"code": "RAC_COMPILE_ERROR", "output": compile_output, "binding": binding},
                )
            runner_compiled = subprocess.run(
                runner_compile_command, capture_output=True, text=False,
                timeout=self.timeout, check=False,
            )
            runner_compile_output = "\n".join(
                part for part in (
                    _decode_tool_output(runner_compiled.stdout),
                    _decode_tool_output(runner_compiled.stderr),
                ) if part
            ).strip()
            if runner_compiled.returncode != 0:
                return RuntimeResult(
                    candidate.id, "ERROR", "runner_compile",
                    arguments=candidate.arguments, tags=candidate.tags,
                    execution_status="ERROR", conclusion="EXECUTION_ERROR",
                    evidence={
                        "code": "RUNNER_COMPILE_ERROR",
                        "output": runner_compile_output,
                        "binding": binding,
                    },
                )
            executed = subprocess.run(
                run_command, capture_output=True, text=False,
                timeout=self.timeout, check=False,
            )
            output = "\n".join(
                part for part in (_decode_tool_output(executed.stdout), _decode_tool_output(executed.stderr)) if part
            ).strip()
            if executed.returncode != 0:
                failure_signature = self._rac_failure_signature(output, method_name)
                if failure_signature is not None:
                    localized = self._rac_failure_is_located(failure_signature)
                    return RuntimeResult(
                        candidate.id, "REPRODUCED" if localized else "UNLOCATED_FAILURE", "rac_runtime",
                        pre_state=_state_dict(candidate.pre),
                        arguments=candidate.arguments, tags=candidate.tags,
                        rac_failure=True, failure_signature=failure_signature,
                        execution_status="COMPLETED",
                        conclusion="CONFIRMED_VIOLATION" if localized else "FAILURE_OBSERVED_UNLOCATED",
                        evidence_origin=("openjml_rac",),
                        evidence={
                            "code": "RAC_RUNTIME_FAILURE",
                            "output": output,
                            "binding": binding,
                            "failure_signature": failure_signature,
                            "localized": localized,
                            "target_executed": True,
                        },
                    )
                return RuntimeResult(
                    candidate.id, "ERROR", "runtime",
                    arguments=candidate.arguments, tags=candidate.tags,
                    execution_status="ERROR", conclusion="EXECUTION_ERROR",
                    evidence={"code": "RUNTIME_PROCESS_ERROR", "output": output, "binding": binding},
                )
            before = next((line for line in output.splitlines() if line.startswith("BEFORE|")), None)
            result = next((line for line in output.splitlines() if line.startswith("RESULT|")), None)
            if before is None or result is None:
                return RuntimeResult(
                    candidate.id, "ERROR", "runtime_observation",
                    arguments=candidate.arguments, tags=candidate.tags,
                    execution_status="ERROR", conclusion="EXECUTION_ERROR",
                    evidence={"code": "RUNTIME_OUTPUT_INVALID", "output": output, "binding": binding},
                )
            pre = adapter.observe(before.removeprefix("BEFORE|"))
            post_fields = dict(item.split("=", 1) for item in result.removeprefix("RESULT|").split("|") if "=" in item)
            post = adapter.observe(result.removeprefix("RESULT|").split("|exception=", 1)[0])
            exception = post_fields.get("exception") or "NONE"
            failure_signature = self._rac_failure_signature(
                output,
                method_name,
                None if exception == "NONE" else exception,
            )
            is_rac_failure = failure_signature is not None
            rac_localized = self._rac_failure_is_located(failure_signature)
            if exception == "NONE":
                exception = None
            adapter.check_roundtrip(candidate.pre, pre)
            return RuntimeResult(
                candidate.id,
                "REPRODUCED" if is_rac_failure and rac_localized else "UNLOCATED_FAILURE" if is_rac_failure else "ERROR" if exception else "NOT_FOUND_WITHIN_BOUNDS",
                "rac_runtime" if is_rac_failure else "target_runtime" if exception else "runtime",
                pre_state=_state_dict(pre), post_state=_state_dict(post), exception=exception,
                arguments=candidate.arguments, tags=candidate.tags,
                rac_failure=is_rac_failure, failure_signature=failure_signature,
                execution_status="COMPLETED",
                conclusion=(
                    "CONFIRMED_VIOLATION" if is_rac_failure and rac_localized
                    else "FAILURE_OBSERVED_UNLOCATED" if is_rac_failure
                    else "EXECUTION_ERROR" if exception else "NO_OBSERVED_VIOLATION"
                ),
                evidence_origin=("openjml_rac",) if is_rac_failure else ("target_runtime",),
                evidence={
                    "output": output,
                    "binding": binding,
                    "rac_failure": is_rac_failure,
                    "failure_signature": failure_signature,
                    "localized": rac_localized,
                    "target_executed": True,
                },
            )
        except subprocess.TimeoutExpired:
            return RuntimeResult(
                candidate.id, "ERROR", "timeout",
                arguments=candidate.arguments, tags=candidate.tags,
                execution_status="TIMEOUT", conclusion="EXECUTION_ERROR",
                evidence={"code": "RUNTIME_TIMEOUT", "timeout_seconds": self.timeout},
            )
        except (OSError, UnicodeError, ValueError) as error:
            return RuntimeResult(
                candidate.id, "ERROR", "adapter",
                arguments=candidate.arguments, tags=candidate.tags,
                execution_status="ERROR", conclusion="ADAPTER_ERROR",
                evidence={"code": "ADAPTER_ERROR", "message": str(error)},
            )
        finally:
            if temporary is not None:
                temporary.cleanup()


def _state_dict(state: NetworkState) -> dict[str, Any]:
    return {
        "users": sorted(state.users),
        "following": [
            [first, second]
            for first, targets in sorted(state.following.items())
            for second in sorted(targets)
        ],
        "followers": [
            [first, second]
            for first, targets in sorted(state.followers.items())
            for second in sorted(targets)
        ],
    }


def _state_from_dict(data: Mapping[str, Any]) -> NetworkState:
    users = {int(value) for value in data.get("users", [])}
    following = {user: set() for user in users}
    followers = {user: set() for user in users}
    for first, second in data.get("following", []):
        following.setdefault(int(first), set()).add(int(second))
    for first, second in data.get("followers", []):
        followers.setdefault(int(first), set()).add(int(second))
    return NetworkState(users, following, followers, {user: set() for user in users})


def _static_status(verdict: str) -> str:
    return {
        "PASS": "PROVED",
        "FAIL": "UNPROVED",
        "UNKNOWN": "UNKNOWN",
        "NOT_RUN": "NOT_RUN",
    }.get(verdict, "UNKNOWN")


def _safe_file_hash(path: Path) -> str:
    try:
        return sha256_file(path)
    except OSError:
        return "unavailable"


def _profile_violations(
    checker: ViolationChecker,
    contract,
    candidate: RuntimeCandidate,
    result: RuntimeResult,
    profile,
) -> tuple[Violation, ...]:
    if result.post_state is None:
        return ()
    return checker.check(
        contract, candidate, _state_from_dict(result.post_state), profile
    )


def _same_violation_set(
    first: tuple[Violation, ...], second: tuple[Violation, ...]
) -> bool:
    return {
        (item.code, item.kind, item.obligation_id, item.line)
        for item in first
    } == {
        (item.code, item.kind, item.obligation_id, item.line)
        for item in second
    }


def verify_unfollow_user(
    suite: LoadedSuite,
    student_jml: Path,
    student_java: Path,
    openjml: str = "openjml",
    timeout: int = 10,
) -> dict[str, Any]:
    source = student_jml.read_text(encoding="utf-8")
    contract = parse_contract(source, suite.method, suite.profile)
    if contract.signals or contract.exceptional_behaviors:
        raise ValueError(
            "unfollowUser 首版运行适配器不覆盖 exceptional_behavior/signals；"
            "请先使用不含异常行为的受限 Suite。"
        )
    adapter = UnfollowUserExecutionAdapter()
    generator = UnfollowUserCandidateGenerator(adapter)
    candidates = generator.generate(contract, suite.profile)
    static_result = check_jml_java(
        student_java,
        openjml,
        timeout,
        (),
        student_jml,
        suite.method,
    )
    executor = RuntimeExecutor(openjml, timeout)
    checker = ViolationChecker()
    results: list[RuntimeResult] = []
    for candidate in candidates:
        result = executor.execute(candidate, student_java, student_jml, suite.method, adapter)
        if result.replay_status == "NOT_FOUND_WITHIN_BOUNDS" and result.post_state is not None:
            violations = _profile_violations(checker, contract, candidate, result, suite.profile)
            if violations:
                result = dataclasses.replace(
                    result,
                    replay_status="REPRODUCED",
                    violations=violations,
                    conclusion="CONFIRMED_VIOLATION",
                    evidence_origin=("profile_transition_check",),
                    evidence={
                        **result.evidence,
                        "confirmed_by": "profile_transition_check",
                    },
                )
        if result.replay_status == "REPRODUCED":
            confirmation = executor.execute(
                candidate, student_java, student_jml, suite.method, adapter
            )
            confirmation_violations = _profile_violations(
                checker, contract, candidate, confirmation, suite.profile
            )
            if result.rac_failure:
                same_violation = (
                    confirmation.rac_failure
                    and result.failure_signature is not None
                    and result.failure_signature == confirmation.failure_signature
                )
            else:
                same_violation = _same_violation_set(result.violations, confirmation_violations)
            if same_violation:
                result = dataclasses.replace(
                    result,
                    evidence={
                        **result.evidence,
                        "replay_confirmation": {
                            "status": "REPRODUCED",
                            "independent_execution": True,
                            "phase": confirmation.phase,
                            "rac_failure": confirmation.rac_failure,
                            "failure_signature": confirmation.failure_signature,
                            "violations": [item.to_dict() for item in confirmation_violations],
                        },
                    },
                    confirmation_status="REPLAY_CONFIRMED",
                )
            else:
                result = dataclasses.replace(
                    result,
                    replay_status="ERROR",
                    phase="replay_confirmation",
                    execution_status="ERROR",
                    conclusion="REPLAY_MISMATCH",
                    confirmation_status="REPLAY_MISMATCH",
                    evidence={
                        **result.evidence,
                        "code": "REPLAY_CONFIRMATION_FAILED",
                        "replay_confirmation": {
                            "status": confirmation.replay_status,
                            "independent_execution": True,
                            "phase": confirmation.phase,
                            "result": confirmation.to_dict(),
                            "violations": [item.to_dict() for item in confirmation_violations],
                        },
                    },
                )
        results.append(result)
    reproduced = [item for item in results if item.replay_status == "REPRODUCED"]
    errors = [item for item in results if item.replay_status == "ERROR"]
    unlocated = [item for item in results if item.replay_status == "UNLOCATED_FAILURE"]
    if not candidates:
        replay_status = "NO_VALID_CANDIDATES"
        conclusion = "NO_VALID_CANDIDATES"
    elif reproduced:
        replay_status = "REPRODUCED"
        conclusion = "CONFIRMED_VIOLATION"
    elif errors:
        replay_status = "ERROR"
        conclusion = "EXECUTION_ERROR"
    elif unlocated:
        replay_status = "UNLOCATED_FAILURE"
        conclusion = "FAILURE_OBSERVED_UNLOCATED"
    else:
        replay_status = "NOT_FOUND_WITHIN_BOUNDS"
        conclusion = "NOT_FOUND_WITHIN_BOUNDS"
    if reproduced and _static_status(static_result.verdict) == "PROVED":
        conclusion = "EVIDENCE_CONFLICT"
    executed_count = sum(
        bool(item.evidence.get("target_executed")) for item in results
    )
    no_observed_count = sum(
        item.replay_status == "NOT_FOUND_WITHIN_BOUNDS" for item in results
    )
    evidence_origins = sorted({
        origin for item in results for origin in item.evidence_origin
    })
    execution_status = (
        "COMPLETED_WITH_ERRORS" if errors and (reproduced or unlocated)
        else "ERROR" if errors else "COMPLETED"
    )
    search_complete = (
        len(results) == len(candidates)
        and not any(item.phase == "timeout" for item in results)
    )
    # The current deterministic generator enumerates its complete fixed set;
    # reaching the last candidate is completion, not budget exhaustion.
    budget_exhausted = False
    binding = (static_result.evidence or {}).get("binding", {}) if static_result.evidence else {}
    session = VerificationSession.start(
        suite.method,
        {
            "suite_reference_sha256": _safe_file_hash(suite.reference),
            "student_jml_sha256": _safe_file_hash(student_jml),
            "student_java_sha256": _safe_file_hash(student_java),
            "student_contract_sha256": str(binding.get("student_contract_sha256", "unavailable")),
            "bound_java_sha256": str(binding.get("bound_java_sha256", "unavailable")),
        },
        {
            "openjml": openjml,
            "timeout_seconds_per_attempt": timeout,
            "adapter": "UnfollowUserExecutionAdapter",
            "adapter_version": "unfollowUser-v1",
            "suite_version": suite.version,
            "profile": getattr(suite.profile, "name", "unknown"),
            "search_strategy": "deterministic_small_states",
            "universe_size": adapter.universe_size,
            "search_budget": {
                "candidate_limit": generator.generated_count,
                "timeout_seconds_per_attempt": timeout,
            },
        },
    )
    session.add(Evidence(
        "support_matrix", "runtime_verifier", "本次运行使用的受限规格能力清单",
        {"matrix": adapter.support_matrix()},
    ))
    session.add(Evidence(
        "static_result", "openjml_esc", "绑定后的静态检查结果",
        {
            "status": _static_status(static_result.verdict),
            "verdict": static_result.verdict,
            "diagnostics": list(static_result.diagnostics),
            "evidence": static_result.evidence or {},
        },
    ))
    session.add(Evidence(
        "candidate_search", "candidate_generator", "确定性候选搜索已完成",
        {
            "generated_count": generator.generated_count,
            "candidate_count": len(candidates),
            "skipped_count": generator.skipped_count,
            "attempted_count": len(results),
            "executed_count": executed_count,
            "no_observed_violation_count": no_observed_count,
            "confirmed_count": len(reproduced),
            "error_count": len(errors),
            "unlocated_failure_count": len(unlocated),
            "search_complete": search_complete,
            "budget_exhausted": budget_exhausted,
        },
    ))
    for item in results:
        session.add(Evidence(
            "runtime_result", "openjml_rac", f"候选 {item.candidate_id} 的执行结果",
            item.to_dict(),
        ))
    return {
        "method": suite.method,
        "suite": suite.name,
        "static_status": _static_status(static_result.verdict),
        "static_result": static_result.to_dict(),
        "replay_status": replay_status,
        "execution_status": execution_status,
        "conclusion": conclusion,
        "evidence_origin": evidence_origins,
        "confirmation_status": "REPLAY_CONFIRMED" if reproduced else "NOT_CONFIRMED",
        "support": adapter.support_matrix(),
        "search": {
            "strategy": "deterministic_small_states",
            "generated_count": generator.generated_count,
            "candidate_count": len(candidates),
            "skipped_count": generator.skipped_count,
            "attempted_count": len(results),
            "executed_count": executed_count,
            "no_observed_violation_count": no_observed_count,
            "confirmed_count": len(reproduced),
            "error_count": len(errors),
            "unlocated_failure_count": len(unlocated),
            "universe_size": adapter.universe_size,
            "search_complete": search_complete,
            "budget_exhausted": budget_exhausted,
            "timeout_seconds_per_attempt": timeout,
        },
        "results": [item.to_dict() for item in results],
        "confirmed_counterexamples": [item.to_dict() for item in reproduced],
        "errors": [item.to_dict() for item in errors],
        "unconfirmed_observations": [item.to_dict() for item in unlocated],
        "session": session.to_dict(),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="受限 unfollowUser RAC 反例搜索与确认")
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--student-jml", type=Path, required=True)
    parser.add_argument("--student-java", type=Path, required=True)
    parser.add_argument("--openjml", default=os.environ.get("OPENJML", "openjml"))
    parser.add_argument("--timeout", type=int, default=10)
    args = parser.parse_args()
    try:
        suite = load_suite(args.suite, PROFILES)
        if suite.method != "unfollowUser":
            raise ProfileError(
                f"当前里程碑只支持 unfollowUser，suite 配置的是 {suite.method}"
            )
        result = verify_unfollow_user(
            suite, args.student_jml, args.student_java, args.openjml, args.timeout
        )
    except (OSError, UnicodeError, ProfileError, SpecError, ValueError) as error:
        print(json.dumps({
            "method": "unfollowUser",
            "static_status": "UNKNOWN",
            "replay_status": "ERROR",
            "error": str(error),
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["replay_status"] == "REPRODUCED" else 2 if result["replay_status"] == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
