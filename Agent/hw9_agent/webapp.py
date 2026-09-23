from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .client import DeepSeekChatClient, ModelClientError
from .exercise import (
    ExerciseBundle,
    StructuralDiagnosticCode,
    build_review_prompt,
    deterministic_check,
)


COACH_VERDICTS = {
    "READY_FOR_DETERMINISTIC_CHECK",
    "NEEDS_REVISION",
    "INCOMPLETE",
    "UNCERTAIN",
}


def default_openjml() -> str:
    """Return the local OpenJML command used by the optional demo chain.

    OPENJML is intentionally an environment/configuration concern: the demo
    may run a native executable, a WSL installation, or no verifier at all.
    The Windows default preserves the repository's existing WSL installation
    while allowing other machines to override it without editing source.
    """
    configured = os.environ.get("OPENJML", "").strip()
    if configured:
        return configured
    if os.name == "nt":
        return "wsl:/home/ranye/.local/openjml-21.0.27/openjml"
    return "openjml"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return "unavailable"
    return digest.hexdigest()


def _tool_probe(command: list[str], label: str, timeout: int = 15) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return {"status": "UNAVAILABLE", "label": label, "version": "找不到命令"}
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "label": label, "version": "环境自检超时"}
    except OSError as error:
        return {"status": "UNAVAILABLE", "label": label, "version": str(error)[:180]}
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
    return {
        "status": "AVAILABLE" if completed.returncode == 0 else "UNAVAILABLE",
        "label": label,
        "version": first_line[:180] or f"退出码 {completed.returncode}",
    }


def _environment_preflight(openjml: str) -> dict[str, Any]:
    """Probe the configured toolchain; configuration alone is not availability."""

    configured = bool(openjml.strip())
    if not configured:
        return {
            "status": "UNCONFIGURED",
            "message": "尚未配置 OpenJML；规格检查仍可使用，Java 检查不会伪装成已运行。",
            "openjml": {"status": "UNCONFIGURED", "label": "OpenJML", "path": ""},
            "java": {"status": "UNCONFIGURED", "label": "Java", "path": ""},
            "esc": {"status": "NOT_RUN", "label": "ESC"},
            "rac": {"status": "NOT_RUN", "label": "RAC"},
        }
    if openjml.startswith("wsl:"):
        executable = openjml.removeprefix("wsl:")
        parent = executable.rsplit("/", 1)[0] if "/" in executable else "."
        probes = {
            "openjml": ["wsl.exe", "bash", executable, "--version"],
            "esc": ["wsl.exe", "bash", executable, "--esc", "--help"],
            "rac": ["wsl.exe", "bash", f"{parent}/openjml-compile", "--version"],
        }
        display = "WSL OpenJML"
        java_check = {
            "status": "BUNDLED",
            "label": "OpenJML Java",
            "version": "由 OpenJML WSL 运行时提供",
        }
    else:
        executable = openjml
        parent = str(Path(executable).parent)
        compile_tool = str(Path(parent) / "openjml-compile")
        probes = {
            "openjml": [executable, "--version"],
            "esc": [executable, "--esc", "--help"],
            "rac": [compile_tool, "--version"],
            "java": ["java", "-version"],
        }
        display = Path(executable).name or "OpenJML"
        java_check = None
    checks = {
        "openjml": _tool_probe(probes["openjml"], display),
        "esc": _tool_probe(probes["esc"], "ESC"),
        "rac": _tool_probe(probes["rac"], "RAC"),
    }
    checks["java"] = java_check or _tool_probe(probes["java"], "Java")
    required_checks = ("openjml", "esc", "rac")
    if not openjml.startswith("wsl:"):
        required_checks += ("java",)
    available = all(checks[item]["status"] == "AVAILABLE" for item in required_checks)
    return {
        "status": "AVAILABLE" if available else "UNAVAILABLE",
        "message": (
            "OpenJML、ESC、RAC 环境自检通过；Java 由 OpenJML 的 WSL 运行时提供。"
            if available and openjml.startswith("wsl:")
            else "OpenJML、ESC、RAC、Java 环境自检通过。"
            if available
            else "OpenJML 已配置，但 OpenJML/ESC/RAC 环境自检未通过；Java 结果会明确标记为不可用。"
        ),
        "openjml": checks["openjml"],
        "java": checks["java"],
        "paths": {
            "openjml": openjml,
            "java": "wsl:java" if openjml.startswith("wsl:") else "java",
        },
        "esc": checks["esc"],
        "rac": checks["rac"],
    }


def _coach_format_error() -> dict[str, Any]:
    """Return safe UI content when the model ignores its JSON contract."""
    return {
        "verdict": "UNCERTAIN",
        "progress_summary": "Agent 未能生成可显示的结构化说明；请以确定性规格评测结果为准。",
        "correct_parts": [],
        "issues": [{
            "location": "AGENT",
            "category": "Agent 反馈格式异常",
            "explanation": "本次不会展示原始模型输出，以免错误格式影响阅读。",
            "counterexample": "",
        }],
        "next_step": "根据确定性规格评测中的错误类别和修正方向修改后重新提交。",
        "may_resubmit": True,
    }


def _incomplete_coach() -> dict[str, Any]:
    return {
        "verdict": "INCOMPLETE",
        "progress_summary": "仍有 JML 空位未填写，尚不能进行语义评测。",
        "correct_parts": [],
        "issues": [{
            "location": "未填写空位",
            "category": "规格未完成",
            "explanation": "请先填写所有占位符，并保持其余接口框架不变。",
            "counterexample": "",
        }],
        "next_step": "填写全部空位后重新提交。",
        "may_resubmit": True,
    }


def _unfence_json(text: str) -> str:
    match = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", text, re.DOTALL)
    return match.group(1) if match else text.strip()


def _short_text(value: Any, limit: int = 800) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _display_filename(value: object, fallback: str = "implementation.java") -> str:
    """Return a harmless display name; never use a browser-provided path."""

    raw = str(value or "").strip()
    name = re.split(r"[\\/]", raw)[-1].strip()
    if not name:
        return fallback
    if not name.lower().endswith(".java"):
        name += ".java"
    return name[:120]


def _spec_preflight(source: str, method_name: str, source_mode: str = "template") -> dict[str, Any]:
    """Perform cheap, actionable checks before invoking the semantic checker."""

    text = str(source or "")
    if not text.strip():
        return {
            "status": "EMPTY",
            "code": "EMPTY",
            "message": "还没有提交 JML 规格。",
            "source_mode": source_mode,
        }
    if re.search(r"\{\{[^}]+\}\}", text):
        return {
            "status": "INCOMPLETE",
            "code": "UNFILLED_BLANKS",
            "message": "规格中仍有未填写的占位符。",
            "source_mode": source_mode,
        }
    if not re.search(rf"\b{re.escape(method_name)}\s*\(", text):
        return {
            "status": "INCOMPATIBLE",
            "code": "METHOD_NOT_FOUND",
            "message": f"提交内容中没有找到方法 {method_name} 的声明。",
            "source_mode": source_mode,
        }
    if "/*@" not in text and "//@" not in text and "@ requires" not in text:
        return {
            "status": "INCOMPATIBLE",
            "code": "CONTRACT_NOT_FOUND",
            "message": "没有找到可检查的 JML 行为规格。",
            "source_mode": source_mode,
        }
    return {
        "status": "READY",
        "code": "SPEC_READY",
        "message": "规格材料已识别，可以开始检查。",
        "source_mode": source_mode,
    }


def _java_preflight(source: str, method_name: str, filename: str = "implementation.java") -> dict[str, Any]:
    """Validate the first-release Java upload boundary without compiling it."""

    text = str(source or "")
    display_name = _display_filename(filename)
    if not text.strip():
        return {
            "status": "NOT_PROVIDED",
            "code": "NO_JAVA",
            "filename": display_name,
            "message": "未添加 Java 实现。",
        }
    if "\x00" in text:
        return {
            "status": "INCOMPATIBLE",
            "code": "BINARY_CONTENT",
            "filename": display_name,
            "message": "上传内容不是可读取的 Java 源码。",
        }
    if len(text.encode("utf-8")) > 1_000_000:
        return {
            "status": "INCOMPATIBLE",
            "code": "FILE_TOO_LARGE",
            "filename": display_name,
            "message": "首版只接受 1 MB 以内的单个 Java 源文件。",
        }
    if re.search(r"(?m)^\s*package\s+[\w.]+\s*;", text):
        return {
            "status": "INCOMPATIBLE",
            "code": "PACKAGE_NOT_SUPPORTED",
            "filename": display_name,
            "message": "当前练习暂不支持带 package 的源码；请上传单文件实现。",
        }

    without_comments = re.sub(r"/\*.*?\*/|//[^\n]*", " ", text, flags=re.S)
    classes = re.findall(r"\bclass\s+([A-Za-z_$][\w$]*)", without_comments)
    if not classes:
        return {
            "status": "INCOMPATIBLE",
            "code": "CLASS_NOT_FOUND",
            "filename": display_name,
            "message": "没有找到可执行的 Java class。",
        }

    method_pattern = re.compile(
        rf"\b(?:public|protected|private|static|final|safe|synchronized|\s)*"
        rf"[A-Za-z_$][\w$<>\[\].?, ]*\s+{re.escape(method_name)}\s*\(([^)]*)\)",
        flags=re.S,
    )
    method_matches = list(method_pattern.finditer(without_comments))
    if len(method_matches) != 1:
        return {
            "status": "INCOMPATIBLE",
            "code": "METHOD_AMBIGUOUS",
            "filename": display_name,
            "class_name": classes[0],
            "method": method_name,
            "message": f"需要恰好一个 {method_name} 方法，当前找到 {len(method_matches)} 个。",
        }

    params_text = method_matches[0].group(1).strip()
    params = [] if not params_text else [item.strip() for item in params_text.split(",")]
    has_users = bool(re.search(r"\bUser\s*\[\s*\]\s+users\b", without_comments))
    has_constructor = bool(
        re.search(rf"\b{re.escape(classes[0])}\s*\(\s*int\s+\w+\s*\)", without_comments)
    )
    runtime_supported = method_name == "unfollowUser" and has_users and has_constructor
    return {
        "status": "READY",
        "code": "JAVA_READY",
        "filename": display_name,
        "class_name": classes[0],
        "method": method_name,
        "parameter_count": len(params),
        "embedded_jml": bool(re.search(
            r"(?:requires|ensures|signals|assignable|normal_behavior|exceptional_behavior)",
            text,
        )),
        "runtime_supported": runtime_supported,
        "message": "Java 源码已识别，可以提交检查。",
    }


def parse_coach_feedback(raw: str) -> dict[str, Any]:
    """Validate the LLM response before it reaches the browser.

    The UI consumes this fixed schema only. In particular, malformed YAML or
    arbitrary model prose is never exposed as a preformatted response.
    """
    try:
        payload = json.loads(_unfence_json(raw))
    except (json.JSONDecodeError, TypeError):
        return _coach_format_error()
    if not isinstance(payload, dict):
        return _coach_format_error()
    verdict = payload.get("verdict")
    progress_summary = _short_text(payload.get("progress_summary"))
    next_step = _short_text(payload.get("next_step"))
    if verdict not in COACH_VERDICTS or not progress_summary or not next_step:
        return _coach_format_error()
    correct_parts = [
        text for item in payload.get("correct_parts", [])
        if (text := _short_text(item, 240))
    ] if isinstance(payload.get("correct_parts", []), list) else []
    issues: list[dict[str, str]] = []
    raw_issues = payload.get("issues", [])
    if not isinstance(raw_issues, list):
        return _coach_format_error()
    for item in raw_issues[:6]:
        if not isinstance(item, dict):
            return _coach_format_error()
        explanation = _short_text(item.get("explanation"))
        category = _short_text(item.get("category"), 120)
        if not explanation or not category:
            return _coach_format_error()
        issues.append({
            "location": _short_text(item.get("location"), 120) or "未定位",
            "category": category,
            "explanation": explanation,
            "counterexample": _short_text(item.get("counterexample")),
        })
    if not isinstance(payload.get("may_resubmit", True), bool):
        return _coach_format_error()
    return {
        "verdict": verdict,
        "progress_summary": progress_summary,
        "correct_parts": correct_parts,
        "issues": issues,
        "next_step": next_step,
        "may_resubmit": payload.get("may_resubmit", True),
    }


class ExerciseWebApp:
    def __init__(
        self,
        project_root: Path,
        exercise_dir: Path,
        model: str,
        base_url: str,
        openjml: str | None = None,
        discover_exercises: bool = True,
    ) -> None:
        self.project_root = project_root
        self.bundle = ExerciseBundle.load(exercise_dir)
        self.model = model
        self.base_url = base_url
        self.openjml = (openjml or default_openjml()).strip()
        self._environment_status: dict[str, Any] | None = None
        self.static_dir = project_root / "web"
        suite_value = self.bundle.config.get("semantic_suite")
        self.semantic_suite = (
            (project_root / suite_value).resolve()
            if isinstance(suite_value, str) and suite_value else None
        )
        self.semantic_entry = (
            project_root.parent / "judge-2027" / "unit3" / "spec_judge" / "semantic_check.py"
        )
        self.consistency_entry = (
            project_root.parent / "judge-2027" / "unit3" / "spec_judge" / "consistency_judge.py"
        )
        self.consistency_demo_java = (
            project_root.parent / "judge-2027" / "unit3" / "spec_judge"
            / "examples" / "FollowUserEscDemo.java"
        )
        self.runtime_entry = (
            project_root.parent / "judge-2027" / "unit3" / "spec_judge" / "runtime_verifier.py"
        )
        self.runtime_suite = (
            project_root.parent / "judge-2027" / "unit3" / "spec_judge" / "suites"
            / "NetworkInterface" / "unfollowUser" / "suite.yaml"
        )
        self.runtime_reference = self.runtime_suite.parent / "reference.java"
        self.runtime_demo_java = (
            project_root.parent / "judge-2027" / "unit3" / "spec_judge"
            / "examples" / "UnfollowUserRuntimeDemoMissingInverse.java"
        )
        self.runtime_demo_case = {
            "id": "unfollow-missing-inverse",
            "label": "unfollowUser · 漏更新粉丝关系",
            "method": "unfollowUser",
            "description": "教师配置的真实 RAC 反例教学案例：实现只更新了关注方，没有同步更新粉丝方。",
        }
        self.exercise_apps: dict[str, ExerciseWebApp] = {str(self.bundle.config["id"]): self}
        if discover_exercises:
            exercises_root = exercise_dir.resolve().parent
            for candidate in sorted(exercises_root.iterdir()):
                if candidate.resolve() == exercise_dir.resolve() or not (candidate / "exercise.json").is_file():
                    continue
                child = ExerciseWebApp(
                    project_root, candidate, model, base_url, self.openjml,
                    discover_exercises=False,
                )
                self.exercise_apps[str(child.bundle.config["id"])] = child

    def resolve_exercise(self, exercise_id: str | None) -> "ExerciseWebApp":
        if not exercise_id:
            return self
        app = self.exercise_apps.get(str(exercise_id))
        if app is None:
            raise ValueError("未知题目")
        return app

    def public_exercises(self) -> list[dict[str, Any]]:
        return [
            {
                "id": exercise_id,
                "title": app.bundle.config["title"],
                "method": app.bundle.config["method"],
                "material_version": app.material_version(),
                "runtime_status": "AVAILABLE" if app.bundle.config["method"] == "unfollowUser" else "UNSUPPORTED",
            }
            for exercise_id, app in self.exercise_apps.items()
        ]

    def material_version(self) -> str:
        parts = [
            _sha256_path(self.bundle.directory / "requirement.md"),
            _sha256_path(self.bundle.directory / "template.java"),
            _sha256_path(self.bundle.directory / "exercise.json"),
            _sha256_path(self.semantic_suite) if self.semantic_suite else "unavailable",
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]

    def environment_preflight(self) -> dict[str, Any]:
        if self._environment_status is None:
            self._environment_status = _environment_preflight(self.openjml)
        return self._environment_status

    def _submission_snapshot(
        self,
        submission: str,
        java_source: str,
        java_filename: str,
        source_mode: str,
        implementation: dict[str, Any] | None = None,
        case_id: str | None = None,
        case_label: str | None = None,
        case_exact_match: bool | None = None,
    ) -> dict[str, Any]:
        runtime_result = (implementation or {}).get("runtime", {}) or {}
        payload = runtime_result.get("result", {}) if isinstance(runtime_result, dict) else {}
        session = payload.get("session", {}) if isinstance(payload, dict) else {}
        static_result = (implementation or {}).get("static_result", {}) or {}
        static_evidence = static_result.get("evidence") if isinstance(static_result, dict) else None
        binding = static_evidence.get("binding", {}) if isinstance(static_evidence, dict) else {}
        if not binding and isinstance(payload, dict):
            payload_static = payload.get("static_result", {})
            payload_evidence = payload_static.get("evidence") if isinstance(payload_static, dict) else None
            binding = payload_evidence.get("binding", {}) if isinstance(payload_evidence, dict) else {}
        session_id = session.get("session_id") or str(uuid.uuid4())
        return {
            "submission_id": str(uuid.uuid4()),
            "session_id": session_id,
            "exercise_id": self.bundle.config["id"],
            "material_version": self.material_version(),
            "case_id": case_id,
            "case_label": case_label,
            "case_exact_match": case_exact_match,
            "method": self.bundle.config["method"],
            "spec_origin": "java_embedded" if source_mode == "java_embedded" else "submitted_jml",
            "source_mode": source_mode,
            "sources": {
                "jml": {"sha256": _sha256_text(submission), "provided": bool(submission.strip())},
                "java": {
                    "sha256": _sha256_text(java_source) if java_source else None,
                    "filename": java_filename,
                    "provided": bool(java_source.strip()),
                },
            },
            "assets": {
                "suite_sha256": _sha256_path(self.semantic_suite) if self.semantic_suite else "unavailable",
                "runtime_suite_sha256": _sha256_path(self.runtime_suite),
                "requirement_ir_sha256": _sha256_path(self.bundle.directory / "requirement_ir.json"),
                "adapter": "UnfollowUserExecutionAdapter" if self.bundle.config["method"] == "unfollowUser" else "static-only",
                "adapter_version": "unfollowUser-v1" if self.bundle.config["method"] == "unfollowUser" else "static-only-v1",
            },
            "toolchain": {
                "openjml": self.environment_preflight().get("openjml", {}).get("label", "OpenJML"),
                "environment_status": self.environment_preflight().get("status", "UNKNOWN"),
            },
            "budget": {
                "runtime_timeout_seconds": 20,
                "runtime_candidate_strategy": "deterministic_small_states",
            },
            "binding": binding,
        }

    def public_exercise(self) -> dict[str, Any]:
        samples = []
        for sample in self.bundle.config.get("samples", []):
            path = self.bundle.directory / sample["file"]
            samples.append({
                "id": sample["id"],
                "label": sample["label"],
                "content": path.read_text(encoding="utf-8"),
            })
        implementation_template = None
        template_value = self.bundle.config.get("implementation_template")
        if isinstance(template_value, str) and template_value:
            template_path = (self.bundle.directory / template_value).resolve()
            if template_path.is_file() and self.bundle.directory.resolve() in template_path.parents:
                implementation_template = {
                    "filename": template_path.name,
                    "content": template_path.read_text(encoding="utf-8"),
                }
        environment = self.environment_preflight()
        consistency_cases = [
            {key: item[key] for key in (
                "id", "label", "description", "jml_excerpt", "java_excerpt", "expected",
            )}
            for item in self.bundle.config.get("consistency_demo_cases", [])
        ]
        return {
            "id": self.bundle.config["id"],
            "material_version": self.material_version(),
            "title": self.bundle.config["title"],
            "method": self.bundle.config["method"],
            "default_mode": self.bundle.config["default_mode"],
            "allowed_modes": self.bundle.config["allowed_modes"],
            "feedback_contract": self.bundle.config["feedback_contract"],
            "placeholders": self.bundle.config["placeholders"],
            "requirement": self.bundle.requirement,
            "template": self.bundle.template,
            "samples": samples,
            "implementation_template": implementation_template,
            "upload_cases": self._public_upload_cases(),
            "workbench": {
                "modes": ["submission", "teaching"],
                "tool_status": environment["message"],
                "environment_preflight": environment,
                "runtime_validation": {
                    **self.runtime_demo_case,
                    "available": all(path.is_file() for path in (
                        self.runtime_entry,
                        self.runtime_suite,
                        self.runtime_reference,
                        self.runtime_demo_java,
                    )),
                    "kind": "teacher_demo",
                },
                "runtime_status": "AVAILABLE" if self.bundle.config["method"] == "unfollowUser" else "UNSUPPORTED",
            },
            # Keep the original flat list for older clients, while exposing
            # the richer group shape to the current teaching workbench.
            "consistency_demo_cases": consistency_cases,
            "consistency_demo_groups": self._public_consistency_demo_groups(consistency_cases),
        }

    def _public_upload_cases(self) -> list[dict[str, Any]]:
        """Expose only whitelisted, self-contained case-library assets.

        The browser receives source text for the declared JML/Java pair, never
        an arbitrary server path.  This keeps one-click loading on the same
        formal submission path as manually uploaded files.
        """

        library = (self.project_root / "case_library").resolve()
        manifest_path = library / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return []
        result: list[dict[str, Any]] = []
        for item in manifest.get("cases", []):
            if not isinstance(item, dict) or item.get("method") != self.bundle.config["method"]:
                continue
            try:
                directory = (library / str(item["directory"])).resolve()
                if library not in directory.parents:
                    continue
                nl_path = (directory / str(item["nl"])).resolve()
                jml_path = (directory / str(item["jml"])).resolve()
                java_path = (directory / str(item["java"])).resolve()
                if any(library not in path.parents for path in (nl_path, jml_path, java_path)):
                    continue
                nl = nl_path.read_text(encoding="utf-8")
                jml = jml_path.read_text(encoding="utf-8")
                java = java_path.read_text(encoding="utf-8")
            except (KeyError, OSError, UnicodeError):
                continue
            result.append({
                "id": str(item.get("id", "")),
                "label": str(item.get("label") or item.get("id") or "案例"),
                "description": nl,
                "intentional_defect": item.get("intentional_defect"),
                "expected": item.get("expected", {}),
                "jml": {"filename": jml_path.name, "content": jml},
                "java": {"filename": java_path.name, "content": java},
            })
        return result

    def _consistency_demo_cases(self) -> dict[str, dict[str, Any]]:
        """Return configured demo cases indexed by their stable public id."""
        cases: dict[str, dict[str, Any]] = {}
        for item in self.bundle.config.get("consistency_demo_cases", []):
            if isinstance(item, dict) and item.get("id"):
                cases[str(item["id"])] = item
        for group in self.bundle.config.get("consistency_demo_groups", []):
            if not isinstance(group, dict):
                continue
            for item in group.get("cases", []):
                if isinstance(item, dict) and item.get("id"):
                    cases[str(item["id"])] = item
        return cases

    @staticmethod
    def _public_consistency_case(item: dict[str, Any]) -> dict[str, Any]:
        return {key: item[key] for key in (
            "id", "label", "description", "jml_excerpt", "java_excerpt", "expected",
        ) if key in item}

    def _public_consistency_demo_groups(
        self,
        flat_cases: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        case_map = {str(item["id"]): item for item in flat_cases if item.get("id")}
        groups: list[dict[str, Any]] = []
        for raw_group in self.bundle.config.get("consistency_demo_groups", []):
            if not isinstance(raw_group, dict) or not raw_group.get("id"):
                continue
            selected: list[dict[str, Any]] = []
            case_ids = raw_group.get("case_ids", [])
            if isinstance(case_ids, list):
                selected = [case_map[str(case_id)] for case_id in case_ids if str(case_id) in case_map]
            if not selected:
                selected = [
                    item for item in raw_group.get("cases", [])
                    if isinstance(item, dict) and item.get("id")
                ]
            groups.append({
                "id": str(raw_group["id"]),
                "label": str(raw_group.get("label", raw_group["id"])),
                "method": str(raw_group.get("method", self.bundle.config.get("method", ""))),
                "nl_description": str(raw_group.get("nl_description", "")),
                "cases": [self._public_consistency_case(item) for item in selected],
            })
        if groups:
            return groups
        if flat_cases:
            return [{
                "id": "default",
                "label": "默认案例组",
                "method": self.bundle.config.get("method", ""),
                "nl_description": "从下方选择一个预设规格与 Java 组合运行。",
                "cases": [self._public_consistency_case(item) for item in flat_cases],
            }]
        return []

    def demo_consistency(self, case_id: str, group_id: str | None = None) -> dict[str, Any]:
        """Run one server-owned demo without accepting arbitrary file paths."""
        cases = self._consistency_demo_cases()
        case = cases.get(case_id)
        if case is None:
            raise ValueError("未知的双一致性演示案例")
        configured_groups = [
            item for item in self.bundle.config.get("consistency_demo_groups", [])
            if isinstance(item, dict)
        ]
        if group_id:
            group = next((item for item in configured_groups if str(item.get("id")) == group_id), None)
            if group is None:
                raise ValueError("未知的双一致性演示案例组")
            case_ids = {str(value) for value in group.get("case_ids", [])}
            case_ids.update(
                str(candidate.get("id"))
                for candidate in group.get("cases", [])
                if isinstance(candidate, dict) and candidate.get("id")
            )
            if case_id not in case_ids:
                raise ValueError("所选案例不属于当前案例组")
        else:
            group = next(
                (
                    item for item in configured_groups
                    if case_id in {str(value) for value in item.get("case_ids", [])}
                    or any(
                        isinstance(candidate, dict) and candidate.get("id") == case_id
                        for candidate in item.get("cases", [])
                    )
                ),
                None,
            )
        requirement_ir = self.bundle.directory / "requirement_ir.json"
        student_jml = self.project_root / case["student_jml"]
        assets = (self.consistency_entry, self.consistency_demo_java, requirement_ir, student_jml)
        if not all(path.is_file() for path in assets):
            raise ValueError("双一致性演示资产不完整")
        completed = subprocess.run(
            [
                sys.executable, str(self.consistency_entry),
                "--requirement-ir", str(requirement_ir),
                "--student-jml", str(student_jml),
                "--student-java", str(self.consistency_demo_java),
                "--openjml", self.openjml,
                f"--openjml-arg=--method={case['implementation_method']}",
                "--embedded-java-contract",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ValueError(completed.stderr.strip() or "双一致性评测未返回有效结果") from error
        return {
            "case": {key: case[key] for key in (
                "id", "label", "description", "jml_excerpt", "java_excerpt", "expected",
            )},
            "group": {
                "id": str(group["id"]),
                "label": str(group.get("label", group["id"])),
                "method": str(group.get("method", self.bundle.config.get("method", ""))),
                "nl_description": str(group.get("nl_description", "")),
            } if group else None,
            "kind": "independent_demo",
            "contract_source": "student_jml_and_embedded_java_contract",
            "warning": "这是独立示意案例，不代表当前提交的同一份规格贯穿两条检查链。",
            "result": result,
        }

    def runtime_demo(self, case_id: str) -> dict[str, Any]:
        """Run the single configured runtime case without accepting paths.

        This endpoint is deliberately a teacher-owned demonstration. It is not
        a general Java sandbox and never executes browser-provided source.
        """
        if case_id != self.runtime_demo_case["id"]:
            raise ValueError("未知的运行时反例教学案例")
        assets = (
            self.runtime_entry,
            self.runtime_suite,
            self.runtime_reference,
            self.runtime_demo_java,
        )
        if not all(path.is_file() for path in assets):
            raise ValueError("运行时反例教学资产不完整")
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(self.runtime_entry),
                    "--suite", str(self.runtime_suite),
                    "--student-jml", str(self.runtime_reference),
                    "--student-java", str(self.runtime_demo_java),
                    "--openjml", self.openjml,
                    "--timeout", "20",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=150,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ValueError("运行时反例搜索超时；请检查 OpenJML 配置") from error
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ValueError(completed.stderr.strip() or "运行时验证器未返回有效结果") from error
        if not isinstance(result, dict):
            raise ValueError("运行时验证器返回格式错误")
        return {
            "case": {**self.runtime_demo_case, "kind": "teacher_demo"},
            "result": result,
        }

    def _implementation_check(
        self,
        submission: str,
        java_source: str,
        java_filename: str,
        source_mode: str,
    ) -> dict[str, Any]:
        """Run implementation evidence using the same submitted JML snapshot."""

        method_name = self.bundle.config["method"]
        preflight = _java_preflight(java_source, method_name, java_filename)
        if preflight["status"] != "READY":
            return {
                "status": preflight["status"],
                "preflight": preflight,
                "static_status": "NOT_RUN",
                "replay_status": "NOT_RUN",
                "runtime": None,
            }

        requirement_ir = self.bundle.directory / "requirement_ir.json"
        needs_consistency_chain = method_name != "unfollowUser"
        if needs_consistency_chain and (not requirement_ir.is_file() or not self.consistency_entry.is_file()):
            return {
                "status": "ERROR",
                "preflight": preflight,
                "static_status": "ERROR",
                "replay_status": "NOT_RUN",
                "message": "实现检查所需的服务端规格资产不可用。",
                "runtime": None,
            }

        with tempfile.TemporaryDirectory(prefix="hw9-implementation-") as directory:
            root = Path(directory)
            jml_path = root / "submitted_spec.java"
            java_path = root / f"{preflight['class_name']}.java"
            jml_path.write_text(submission, encoding="utf-8")
            java_path.write_text(java_source, encoding="utf-8")
            if not needs_consistency_chain:
                runtime = self._runtime_check(
                    submission,
                    java_source,
                    preflight,
                    jml_path,
                    java_path,
                )
                runtime_result = runtime.get("result", {}) if isinstance(runtime, dict) else {}
                static_status = str(runtime_result.get("static_status", "NOT_RUN")).upper()
                return {
                    "status": "CHECKED" if runtime.get("status") == "CHECKED" else runtime.get("status", "ERROR"),
                    "preflight": preflight,
                    "static_status": static_status,
                    "replay_status": runtime.get("replay_status", "NOT_RUN"),
                    "static_result": runtime_result.get("static_result", {
                        "verdict": static_status,
                        "diagnostics": [],
                    }),
                    "static": runtime_result.get("static_result", {
                        "verdict": static_status,
                        "diagnostics": [],
                    }),
                    "runtime": runtime,
                    "source_mode": source_mode,
                }
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(self.consistency_entry),
                        "--requirement-ir", str(requirement_ir),
                        "--student-jml", str(jml_path),
                        "--student-java", str(java_path),
                        "--method", method_name,
                        "--openjml", self.openjml,
                        "--timeout", "30",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                    check=False,
                )
                payload = json.loads(completed.stdout)
                if not isinstance(payload, dict):
                    raise ValueError("实现检查器返回格式错误")
            except subprocess.TimeoutExpired:
                return {
                    "status": "ERROR",
                    "preflight": preflight,
                    "static_status": "TIMEOUT",
                    "replay_status": "NOT_RUN",
                    "message": "实现静态检查超时；可以保留规格结果并稍后重试。",
                    "runtime": None,
                }
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
                return {
                    "status": "ERROR",
                    "preflight": preflight,
                    "static_status": "ERROR",
                    "replay_status": "NOT_RUN",
                    "message": "实现静态检查未能完成；请检查 Java 方法签名和 OpenJML 配置。",
                    "runtime": None,
                }

            jml_java = payload.get("jml_java")
            if not isinstance(jml_java, dict):
                jml_java = {}
            static_status = str(
                jml_java.get("verdict")
                or jml_java.get("status")
                or payload.get("overall")
                or "UNKNOWN"
            ).upper()
            runtime = self._runtime_check(
                submission,
                java_source,
                preflight,
                jml_path,
                java_path,
            )
            return {
                "status": "CHECKED",
                "preflight": preflight,
                "static_status": static_status,
                "replay_status": runtime.get("replay_status", "NOT_RUN") if runtime else "NOT_RUN",
                "consistency": payload,
                "static_result": jml_java,
                "static": jml_java,
                "runtime": runtime,
                "source_mode": source_mode,
            }

    def _runtime_check(
        self,
        submission: str,
        java_source: str,
        preflight: dict[str, Any],
        jml_path: Path,
        java_path: Path,
    ) -> dict[str, Any]:
        """Run the supported runtime adapter, or state why it was not run."""

        if self.bundle.config["method"] != "unfollowUser":
            return {
                "status": "UNSUPPORTED",
                "execution_status": "NOT_RUN",
                "replay_status": "UNSUPPORTED",
                "conclusion": "UNSUPPORTED",
                "message": "当前题目已完成静态实现检查；运行反例适配器暂只支持 unfollowUser。",
            }
        assets = (self.runtime_entry, self.runtime_suite)
        if not all(path.is_file() for path in assets):
            return {
                "status": "ERROR",
                "execution_status": "ERROR",
                "replay_status": "ERROR",
                "conclusion": "EXECUTION_ERROR",
                "message": "运行诊断所需的服务端资产不可用。",
            }
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(self.runtime_entry),
                    "--suite", str(self.runtime_suite),
                    "--student-jml", str(jml_path),
                    "--student-java", str(java_path),
                    "--openjml", self.openjml,
                    "--timeout", "20",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=150,
                check=False,
            )
            payload = json.loads(completed.stdout)
            if not isinstance(payload, dict):
                raise ValueError("运行验证器返回格式错误")
        except subprocess.TimeoutExpired:
            return {
                "status": "ERROR",
                "execution_status": "TIMEOUT",
                "replay_status": "TIMEOUT",
                "conclusion": "EXECUTION_ERROR",
                "message": "反例搜索超时；这不等于实现正确。",
            }
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
            return {
                "status": "ERROR",
                "execution_status": "ERROR",
                "replay_status": "ERROR",
                "conclusion": "EXECUTION_ERROR",
                "message": "运行诊断未能完成；请先确认实现可以被 OpenJML RAC 编译。",
            }
        replay_status = str(payload.get("replay_status", payload.get("status", "UNKNOWN"))).upper()
        confirmed = payload.get("confirmed_counterexamples", [])
        errors = payload.get("errors", [])
        if payload.get("error") and "search" not in payload:
            return {
                "status": "ERROR",
                "execution_status": "ERROR",
                "replay_status": "ERROR",
                "conclusion": "CHECK_ERROR",
                "confirmed_counterexamples": [],
                "errors": [],
                "result": payload,
                "message": str(payload["error"]),
            }
        if not preflight.get("runtime_supported"):
            return {
                "status": "UNSUPPORTED",
                "execution_status": "NOT_RUN",
                "replay_status": "UNSUPPORTED",
                "conclusion": "UNSUPPORTED",
                "confirmed_counterexamples": [],
                "errors": errors if isinstance(errors, list) else [],
                "search": payload.get("search", {}),
                "result": payload,
                "message": "这份 Java 尚不符合当前运行适配器要求；静态验证仍已单独运行，未执行目标方法。",
            }
        return {
            "status": "CHECKED",
            "execution_status": payload.get("execution_status", "COMPLETED"),
            "replay_status": replay_status,
            "conclusion": payload.get("conclusion", replay_status),
            "confirmation_status": payload.get("confirmation_status", "NOT_CONFIRMED"),
            "confirmed_counterexamples": confirmed if isinstance(confirmed, list) else [],
            "errors": errors if isinstance(errors, list) else [],
            "unconfirmed_observations": payload.get("unconfirmed_observations", []),
            "search": payload.get("search", {}),
            "result": payload,
        }

    def review(self, data: dict[str, Any]) -> dict[str, Any]:
        submission = str(data.get("submission", ""))
        mode = str(data.get("mode", self.bundle.config["default_mode"]))
        source_mode = str(data.get("source_mode", "template"))
        java_source = str(data.get("java_source", ""))
        java_filename = _display_filename(data.get("java_filename", "implementation.java"))
        requested_case_id = str(data.get("case_id", "")).strip()
        case = next(
            (item for item in self._public_upload_cases() if item["id"] == requested_case_id),
            None,
        )
        case_id = case["id"] if case else None
        case_label = case["label"] if case else None
        case_exact_match = (
            submission.strip() == str(case["jml"]["content"]).strip()
            and java_source.strip() == str(case["java"]["content"]).strip()
        ) if case else None
        history = data.get("history", [])
        if not isinstance(history, list):
            history = []
        if source_mode == "template":
            checks = deterministic_check(self.bundle, submission)
            spec_ready = not any(
                item["code"] == StructuralDiagnosticCode.UNFILLED_BLANKS.value
                for item in checks
            )
        else:
            preflight = _spec_preflight(submission, self.bundle.config["method"], source_mode)
            checks = [{
                "code": preflight["code"],
                "location": "提交规格",
                "category": "提交材料",
                "observation": preflight["message"],
                "guidance": "" if preflight["status"] == "READY" else "请修正材料后重新检查。",
            }]
            spec_ready = preflight["status"] == "READY"
        if not spec_ready:
            snapshot = self._submission_snapshot(
                submission, java_source, java_filename, source_mode,
                case_id=case_id, case_label=case_label, case_exact_match=case_exact_match,
            )
            return {
                "exercise_id": self.bundle.config["id"],
                "material_version": self.material_version(),
                "checks": checks,
                "semantic": None,
                "implementation": None,
                "coach": _incomplete_coach() if source_mode == "template" else None,
                "mode": mode,
                "source_mode": source_mode,
                "submission_snapshot": snapshot,
                "environment_preflight": self.environment_preflight(),
            }
        semantic = self.semantic_check(submission)
        semantic_diagnostics = semantic.get("diagnostics", []) if isinstance(semantic, dict) else []
        config_error = any(
            item.get("code") in {"JUDGE_CONFIGURATION", "JUDGE_UNAVAILABLE"}
            for item in semantic_diagnostics if isinstance(item, dict)
        )
        if isinstance(semantic, dict):
            semantic["execution_status"] = "ERROR" if config_error else "COMPLETED"
            semantic["conclusion"] = "SPEC_CHECK_ERROR" if config_error else "DATA_POINTS_MATCH" if semantic.get("passed") else "DATA_POINTS_DIFFER"
            semantic["evidence_origin"] = ["specification_data_points"]
        if java_source.strip() and semantic.get("passed"):
            implementation = self._implementation_check(
                submission, java_source, java_filename, source_mode
            )
        elif java_source.strip():
            implementation = {
                "status": "NOT_RUN",
                "static_status": "NOT_RUN",
                "replay_status": "NOT_RUN",
                "preflight": _java_preflight(
                    java_source, self.bundle.config["method"], java_filename
                ),
                "static_result": {"verdict": "NOT_RUN", "diagnostics": []},
                "static": {"verdict": "NOT_RUN", "diagnostics": []},
                "runtime": {
                    "status": "NOT_RUN",
                    "execution_status": "NOT_RUN",
                    "replay_status": "NOT_RUN",
                    "conclusion": "NOT_RUN",
                    "message": "提交规格尚未通过题意数据点检查，因此未执行实现与运行验证。",
                },
                "message": "先修正规格，再检查 Java 是否满足该规格。",
                "source_mode": source_mode,
            }
        else:
            implementation = None
        snapshot = self._submission_snapshot(
            submission, java_source, java_filename, source_mode, implementation,
            case_id=case_id, case_label=case_label, case_exact_match=case_exact_match,
        )
        response = {
            "exercise_id": self.bundle.config["id"],
            "material_version": self.material_version(),
            "checks": checks,
            "semantic": semantic,
            "implementation": implementation,
            "coach": None,
            "mode": mode,
            "source_mode": source_mode,
            "submission_snapshot": snapshot,
            "environment_preflight": self.environment_preflight(),
        }
        if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
            return response
        client = DeepSeekChatClient(model=self.model, base_url=self.base_url)
        prompt = build_review_prompt(
            self.project_root,
            self.bundle,
            submission,
            mode,
            history[-6:],
            semantic,
        )
        try:
            response["coach"] = parse_coach_feedback(client.generate(prompt))
        except ModelClientError:
            response["coach"] = {
                "verdict": "UNCERTAIN",
                "progress_summary": "学习解释暂时不可用；确定性检查结果仍然有效。",
                "correct_parts": [],
                "issues": [],
                "next_step": "根据规格检查和实现证据修改后重新提交。",
                "may_resubmit": True,
                "status": "UNAVAILABLE",
            }
        return response

    def semantic_check(self, submission: str) -> dict[str, Any]:
        """Run the server-owned semantic judge without exposing its reference file."""
        if self.semantic_suite is None or not self.semantic_suite.is_file() or not self.semantic_entry.is_file():
            return {
                "score": 0,
                "passed": False,
                "diagnostics": [{
                    "code": "JUDGE_CONFIGURATION",
                    "location": "SERVER",
                    "category": "评测服务配置",
                    "observation": "服务器端语义评测资产不可用。",
                    "guidance": "请联系课程组。",
                }],
            }
        name = ""
        try:
            descriptor, name = tempfile.mkstemp(prefix="jml-submission-", suffix=".java")
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(submission)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(self.semantic_entry),
                    name,
                    "--suite",
                    str(self.semantic_suite),
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            if completed.returncode == 2:
                return {
                    "score": 0,
                    "passed": False,
                    "diagnostics": [{
                        "code": "JUDGE_CONFIGURATION",
                        "location": "SERVER",
                        "category": "评测服务配置",
                        "observation": "服务器端 suite 或参考合同配置无效。",
                        "guidance": "请联系课程组。",
                    }],
                }
            try:
                payload = json.loads(completed.stdout)
            except json.JSONDecodeError:
                raise ValueError(completed.stderr.strip() or "语义评测器未返回有效结果")
            if not isinstance(payload, dict):
                raise ValueError("语义评测器返回格式错误")
            return payload
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            return {
                "score": 0,
                "passed": False,
                "diagnostics": [{
                    "code": "JUDGE_UNAVAILABLE",
                    "location": "SERVER",
                    "category": "评测服务异常",
                    "observation": "语义评测器未能完成本次检查。",
                    "guidance": "请稍后重试；若持续出现，请联系课程组。",
                }],
            }
        finally:
            if name:
                try:
                    os.unlink(name)
                except OSError:
                    pass


def make_handler(app: ExerciseWebApp):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(app.static_dir), **kwargs)

        def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/exercises":
                self._json({"exercises": app.public_exercises(), "default_id": app.bundle.config["id"]})
                return
            if parsed.path == "/api/exercise":
                exercise_id = parse_qs(parsed.query).get("id", [None])[0]
                self._json(app.resolve_exercise(exercise_id).public_exercise())
                return
            if parsed.path == "/health":
                self._json({"status": "ok"})
                return
            if parsed.path == "/":
                self.path = "/index.html"
            super().do_GET()

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 1_000_000:
                    self._json({"error": "request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                    return
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                target = app.resolve_exercise(str(data.get("exercise_id", "")).strip() or None)
                if self.path == "/api/check":
                    submission = str(data.get("submission", ""))
                    self._json({
                        "exercise_id": target.bundle.config["id"],
                        "checks": deterministic_check(target.bundle, submission),
                        "semantic": target.semantic_check(submission),
                    })
                    return
                if self.path == "/api/preflight":
                    submission = str(data.get("submission", ""))
                    source_mode = str(data.get("source_mode", "template"))
                    self._json({
                        "spec": _spec_preflight(
                            submission,
                            target.bundle.config["method"],
                            source_mode,
                        ),
                        "java": _java_preflight(
                            str(data.get("java_source", "")),
                            target.bundle.config["method"],
                            str(data.get("java_filename", "implementation.java")),
                        ),
                    })
                    return
                if self.path == "/api/review":
                    self._json(target.review(data))
                    return
                if self.path == "/api/demo-consistency":
                    self._json(target.demo_consistency(
                        str(data.get("case_id", "")),
                        str(data.get("group_id", "")).strip() or None,
                    ))
                    return
                if self.path == "/api/runtime-demo":
                    self._json(target.runtime_demo(str(data.get("case_id", ""))))
                    return
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except (ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except ModelClientError as exc:
                self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
            except Exception as exc:
                self._json({"error": f"server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format, *args):
            print(f"[web] {self.address_string()} {format % args}")

    return Handler


def serve(app: ExerciseWebApp, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"HW9 JML Learning Agent: http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
