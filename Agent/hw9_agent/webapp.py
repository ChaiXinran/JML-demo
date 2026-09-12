from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

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
    ) -> None:
        self.project_root = project_root
        self.bundle = ExerciseBundle.load(exercise_dir)
        self.model = model
        self.base_url = base_url
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

    def public_exercise(self) -> dict[str, Any]:
        samples = []
        for sample in self.bundle.config.get("samples", []):
            path = self.bundle.directory / sample["file"]
            samples.append({
                "id": sample["id"],
                "label": sample["label"],
                "content": path.read_text(encoding="utf-8"),
            })
        return {
            "id": self.bundle.config["id"],
            "title": self.bundle.config["title"],
            "method": self.bundle.config["method"],
            "default_mode": self.bundle.config["default_mode"],
            "allowed_modes": self.bundle.config["allowed_modes"],
            "feedback_contract": self.bundle.config["feedback_contract"],
            "placeholders": self.bundle.config["placeholders"],
            "requirement": self.bundle.requirement,
            "template": self.bundle.template,
            "samples": samples,
            "consistency_demo_cases": [
                {key: item[key] for key in (
                    "id", "label", "description", "jml_excerpt", "java_excerpt", "expected",
                )}
                for item in self.bundle.config.get("consistency_demo_cases", [])
            ],
        }

    def demo_consistency(self, case_id: str) -> dict[str, Any]:
        """Run one server-owned demo without accepting arbitrary file paths."""
        cases = {item["id"]: item for item in self.bundle.config.get("consistency_demo_cases", [])}
        case = cases.get(case_id)
        if case is None:
            raise ValueError("未知的双一致性演示案例")
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
                "--openjml", "wsl:/home/ranye/.local/openjml-21.0.27/openjml",
                f"--openjml-arg=--method={case['implementation_method']}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
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
            "result": result,
        }

    def review(self, data: dict[str, Any]) -> dict[str, Any]:
        submission = str(data.get("submission", ""))
        mode = str(data.get("mode", self.bundle.config["default_mode"]))
        history = data.get("history", [])
        if not isinstance(history, list):
            history = []
        checks = deterministic_check(self.bundle, submission)
        if any(item["code"] == StructuralDiagnosticCode.UNFILLED_BLANKS.value for item in checks):
            return {
                "checks": checks,
                "semantic": None,
                "coach": _incomplete_coach(),
                "mode": mode,
            }
        semantic = self.semantic_check(submission)
        if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
            return {
                "checks": checks,
                "semantic": semantic,
                "coach": None,
                "mode": mode,
            }
        client = DeepSeekChatClient(model=self.model, base_url=self.base_url)
        prompt = build_review_prompt(
            self.project_root,
            self.bundle,
            submission,
            mode,
            history[-6:],
            semantic,
        )
        coach = parse_coach_feedback(client.generate(prompt))
        return {
            "checks": checks,
            "semantic": semantic,
            "coach": coach,
            "mode": mode,
        }

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
            if self.path == "/api/exercise":
                self._json(app.public_exercise())
                return
            if self.path == "/health":
                self._json({"status": "ok"})
                return
            if self.path == "/":
                self.path = "/index.html"
            super().do_GET()

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 1_000_000:
                    self._json({"error": "request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                    return
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                if self.path == "/api/check":
                    submission = str(data.get("submission", ""))
                    self._json({
                        "checks": deterministic_check(app.bundle, submission),
                        "semantic": app.semantic_check(submission),
                    })
                    return
                if self.path == "/api/review":
                    self._json(app.review(data))
                    return
                if self.path == "/api/demo-consistency":
                    self._json(app.demo_consistency(str(data.get("case_id", ""))))
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
