"""Two-chain consistency judge: course NL -> student JML -> student Java.

The NL/JML chain uses a teacher-approved requirement IR.  The Java/JML chain
delegates verification to OpenJML and preserves UNKNOWN as a first-class
result when verification cannot be completed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from semantic_judge import SpecError, evaluate_sources


VERDICTS = {"PASS", "FAIL", "UNKNOWN", "NOT_RUN"}


@dataclass(frozen=True)
class ChainResult:
    verdict: str
    diagnostics: tuple[dict[str, Any], ...] = ()
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _requirement_contract(requirement_ir: dict[str, Any]) -> str:
    if requirement_ir.get("status") != "teacher_approved":
        raise SpecError("Requirement IR 尚未经过课程组批准")
    method = requirement_ir.get("method")
    signature = requirement_ir.get("java_signature")
    obligations = requirement_ir.get("obligations")
    if not isinstance(method, str) or not method:
        raise SpecError("Requirement IR 缺少 method")
    if not isinstance(signature, str) or method not in signature:
        raise SpecError("Requirement IR 缺少有效的 java_signature")
    if not isinstance(obligations, dict):
        raise SpecError("Requirement IR 缺少 obligations")

    lines = ["/*@ public normal_behavior"]
    requires = obligations.get("requires", [])
    ensures = obligations.get("ensures", [])
    signals = obligations.get("signals", [])
    assignable = obligations.get("assignable", [])
    output_ensures = obligations.get("output_ensures", [])
    if len(requires) != 1:
        raise SpecError("当前 Profile 要求恰好一个 requires 义务")
    lines.append(f"  @ requires {requires[0]['expression']};")
    for item in ensures:
        lines.append(f"  @ ensures {item['expression']};")
    for item in output_ensures:
        lines.append(f"  @ ensures {item['expression']};")
    for expression in assignable:
        lines.append(f"  @ assignable {expression};")
    for item in signals:
        lines.append("  @ also")
        lines.append("  @ public exceptional_behavior")
        lines.append(
            f"  @ signals ({item['exception']} e) {item['expression']};"
        )
    lines.extend(("  @*/", signature))
    return "public interface RequirementContract {\n" + "\n".join(lines) + "\n}\n"


def check_nl_jml(
    requirement_ir_path: Path, student_jml_path: Path, method_name: str | None = None
) -> ChainResult:
    try:
        requirement_ir = json.loads(requirement_ir_path.read_text(encoding="utf-8"))
        method = method_name or requirement_ir.get("method", "followUser")
        requirement_contract = _requirement_contract(requirement_ir)
        student_source = student_jml_path.read_text(encoding="utf-8")
        result = evaluate_sources(requirement_contract, student_source, method)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, SpecError) as error:
        return ChainResult("UNKNOWN", ({
            "code": "REQUIREMENT_IR_INVALID",
            "location": "COURSE_REQUIREMENT",
            "category": "需求模型配置",
            "observation": str(error),
            "guidance": "请课程组检查并重新批准 Requirement IR。",
        },))
    diagnostics = tuple(item.to_dict() for item in result.diagnostics)
    return ChainResult(
        "PASS" if result.passed else "FAIL",
        diagnostics,
        {"score": result.score, "basis": "teacher_approved_requirement_ir"},
    )


def check_jml_java(
    java_path: Path,
    openjml: str = "openjml",
    timeout: int = 60,
    extra_args: tuple[str, ...] = (),
) -> ChainResult:
    if openjml.startswith("wsl:"):
        resolved = str(java_path.resolve())
        match = re.match(r"^(?P<drive>[A-Za-z]):\\(?P<rest>.*)$", resolved)
        if match is None:
            return ChainResult("UNKNOWN", ({
                "code": "WSL_PATH_UNSUPPORTED",
                "location": "TOOLCHAIN",
                "category": "验证路径不可用",
                "observation": f"无法把 Windows 路径转换为 WSL 路径：{resolved}",
                "guidance": "请使用本地磁盘中的 Java 文件。",
            },))
        wsl_java_path = (
            f"/mnt/{match.group('drive').lower()}/"
            + match.group("rest").replace("\\", "/")
        )
        command = [
            "wsl.exe", openjml.removeprefix("wsl:"),
            "--esc", *extra_args, wsl_java_path,
        ]
    else:
        command = [openjml, "--esc", *extra_args, str(java_path)]
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
        return ChainResult("UNKNOWN", ({
            "code": "OPENJML_NOT_FOUND",
            "location": "TOOLCHAIN",
            "category": "验证工具不可用",
            "observation": f"找不到 OpenJML 可执行文件：{openjml}",
            "guidance": "安装 OpenJML，或通过 --openjml 指定可执行文件路径。",
        },))
    except subprocess.TimeoutExpired:
        return ChainResult("UNKNOWN", ({
            "code": "OPENJML_TIMEOUT",
            "location": "TOOLCHAIN",
            "category": "验证超时",
            "observation": f"OpenJML 在 {timeout} 秒内未完成。",
            "guidance": "检查规格复杂度，或提高 --timeout 后重试。",
        },))
    except OSError as error:
        return ChainResult("UNKNOWN", ({
            "code": "OPENJML_UNAVAILABLE",
            "location": "TOOLCHAIN",
            "category": "验证工具异常",
            "observation": str(error),
            "guidance": "检查 OpenJML 与 Java 运行环境。",
        },))

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    evidence = {
        "engine": "OpenJML ESC",
        "exit_code": completed.returncode,
        "output": output[-12000:],
    }
    if completed.returncode == 0:
        return ChainResult("PASS", evidence=evidence)
    if completed.returncode == 6:
        return ChainResult("FAIL", ({
            "code": "OPENJML_VERIFICATION_FAILURE",
            "location": "IMPLEMENTATION",
            "category": "实现不满足学生 JML",
            "observation": "OpenJML ESC 报告验证失败；具体证明义务见 evidence.output。",
            "guidance": "根据失败的 postcondition、frame、invariant 或调用前置条件定位实现。",
        },), evidence)
    return ChainResult("UNKNOWN", ({
        "code": "OPENJML_ANALYSIS_ERROR",
        "location": "TOOLCHAIN",
        "category": "验证未完成",
        "observation": f"OpenJML 因解析、类型、参数或系统错误退出（代码 {completed.returncode}）。",
        "guidance": "先修复 evidence.output 中的工具错误，再重新进行一致性判断。",
    },), evidence)


def combined_verdict(nl_jml: ChainResult, jml_java: ChainResult) -> str:
    if "UNKNOWN" in {nl_jml.verdict, jml_java.verdict}:
        return "UNKNOWN"
    if nl_jml.verdict == "PASS" and jml_java.verdict == "PASS":
        return "PASS"
    if nl_jml.verdict == "FAIL" and jml_java.verdict == "PASS":
        return "SPECIFICATION_INCORRECT"
    if nl_jml.verdict == "PASS" and jml_java.verdict == "FAIL":
        return "IMPLEMENTATION_INCORRECT"
    return "SPECIFICATION_AND_IMPLEMENTATION_INCORRECT"


def evaluate_consistency(
    requirement_ir: Path,
    student_jml: Path,
    student_java: Path,
    method: str | None = None,
    openjml: str = "openjml",
    timeout: int = 60,
    openjml_args: tuple[str, ...] = (),
) -> dict[str, Any]:
    nl_jml = check_nl_jml(requirement_ir, student_jml, method)
    jml_java = check_jml_java(student_java, openjml, timeout, openjml_args)
    return {
        "nl_jml": nl_jml.to_dict(),
        "jml_java": jml_java.to_dict(),
        "overall": combined_verdict(nl_jml, jml_java),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="NL-JML 与 JML-Java 双一致性检测")
    parser.add_argument("--requirement-ir", type=Path, required=True)
    parser.add_argument("--student-jml", type=Path, required=True)
    parser.add_argument("--student-java", type=Path, required=True)
    parser.add_argument("--method")
    parser.add_argument("--openjml", default="openjml")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--openjml-arg", action="append", default=[])
    args = parser.parse_args()
    result = evaluate_consistency(
        args.requirement_ir,
        args.student_jml,
        args.student_java,
        args.method,
        args.openjml,
        args.timeout,
        tuple(args.openjml_arg),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
