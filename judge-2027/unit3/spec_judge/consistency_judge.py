"""Two-chain consistency judge: course NL -> student JML -> student Java.

The NL/JML chain uses a teacher-approved requirement IR.  The Java/JML chain
delegates verification to OpenJML and preserves UNKNOWN as a first-class
result when verification cannot be completed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from semantic_judge import SpecError, evaluate_sources
from verification_evidence import Evidence, SourceSpan, VerificationSession, sha256_file


VERDICTS = {"PASS", "FAIL", "UNKNOWN", "NOT_RUN"}


@dataclass(frozen=True)
class ChainResult:
    verdict: str
    diagnostics: tuple[dict[str, Any], ...] = ()
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_JML_BLOCK_RE = re.compile(r"/\*@.*?@\*/", re.DOTALL)


def _mask_comments(source: str) -> str:
    """Keep offsets while hiding Java/JML comments from declaration lookup."""
    masked = re.sub(
        r"/\*.*?\*/|//[^\n]*",
        lambda match: "".join("\n" if char == "\n" else " " for char in match.group()),
        source,
        flags=re.DOTALL,
    )
    return masked


def _method_declarations(source: str, method_name: str) -> list[dict[str, Any]]:
    masked = _mask_comments(source)
    declarations: list[dict[str, Any]] = []
    for match in re.finditer(rf"\b{re.escape(method_name)}\s*\(", masked):
        declaration_start = max(
            masked.rfind("\n", 0, match.start()),
            masked.rfind("{", 0, match.start()),
            masked.rfind("}", 0, match.start()),
            masked.rfind(";", 0, match.start()),
        ) + 1
        prefix = masked[declaration_start:match.start()]
        if not re.search(
            r"\b(public|protected|private|static|final|synchronized|abstract|native)\b",
            prefix,
        ) and re.search(r"\b(if|for|while|switch|catch)\s*$", prefix):
            continue
        close = masked.find(")", match.end())
        if close < 0:
            continue
        raw_parameters = masked[match.end():close].strip()
        parameters: list[tuple[str, str]] = []
        if raw_parameters:
            for item in raw_parameters.split(","):
                tokens = item.strip().split()
                if len(tokens) < 2:
                    continue
                parameters.append((" ".join(tokens[:-1]), tokens[-1]))
        declarations.append({
            "start": declaration_start,
            "parameters": parameters,
        })
    return declarations


def _line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _method_declaration_offset(source: str, method_name: str) -> int | None:
    """Find a method declaration without treating a JML call as a method."""
    declarations = _method_declarations(source, method_name)
    return declarations[0]["start"] if len(declarations) == 1 else None


def _student_contract_block(source: str, method_name: str) -> tuple[str, SourceSpan] | None:
    """Return the JML block immediately associated with a target method."""
    for match in _JML_BLOCK_RE.finditer(source):
        after = source[match.end():]
        if re.match(
            rf"\s*(?:public|protected|private|static|final|abstract|synchronized|native|safe|pure|\s)+[^;{{]+\b{re.escape(method_name)}\s*\(",
            after,
            re.DOTALL,
        ):
            return match.group(0), SourceSpan(
                "student_jml",
                _line_number(source, match.start()),
                _line_number(source, match.end()),
            )
    return None


def _bind_student_jml(student_jml_path: Path, java_path: Path, method_name: str) -> tuple[Path, tempfile.TemporaryDirectory[str], dict[str, Any]]:
    """Create an ephemeral Java source whose target method uses the submitted JML.

    The original files are never modified.  Replacing an existing contract is
    important: checking a Java file's old embedded contract would otherwise
    silently verify a different submission.
    """
    jml_source = student_jml_path.read_text(encoding="utf-8")
    contract = _student_contract_block(jml_source, method_name)
    if contract is None:
        raise ValueError(f"提交 JML 中找不到 {method_name} 方法对应的 /*@ ... @*/ 合同块")
    contract_text, jml_span = contract
    java_source = java_path.read_text(encoding="utf-8")
    student_declarations = _method_declarations(jml_source, method_name)
    java_declarations = _method_declarations(java_source, method_name)
    if len(student_declarations) != 1:
        raise ValueError(f"提交 JML 中 {method_name} 的声明不唯一")
    if len(java_declarations) != 1:
        raise ValueError(
            f"实现文件中 {method_name} 的声明不唯一（找到 {len(java_declarations)} 个）"
            if java_declarations else f"实现文件中找不到目标方法 {method_name}"
        )
    student_parameters = student_declarations[0]["parameters"]
    java_parameters = java_declarations[0]["parameters"]
    if student_parameters != java_parameters:
        raise ValueError(
            f"{method_name} 的参数类型或名称不匹配："
            f"规格为 {student_parameters}，实现为 {java_parameters}"
        )
    method_offset = java_declarations[0]["start"]

    replacement = contract_text
    existing_start = None
    existing_end = None
    for match in _JML_BLOCK_RE.finditer(java_source):
        if java_source[match.end():method_offset].strip() == "":
            existing_start, existing_end = match.span()
            break
    if existing_start is not None:
        bound_source = java_source[:existing_start] + replacement + java_source[existing_end:]
        binding_mode = "replaced_embedded_contract"
        bound_contract_start = existing_start
        bound_method_offset = method_offset + len(replacement) - (existing_end - existing_start)
    else:
        bound_source = java_source[:method_offset] + replacement + "\n" + java_source[method_offset:]
        binding_mode = "injected_contract"
        bound_contract_start = method_offset
        bound_method_offset = method_offset + len(replacement) + 1

    temporary = tempfile.TemporaryDirectory(prefix="jml-bound-")
    bound_path = Path(temporary.name) / java_path.name
    bound_path.write_text(bound_source, encoding="utf-8")
    metadata = {
        "mode": binding_mode,
        "method": method_name,
        "student_jml_sha256": sha256_file(student_jml_path),
        "student_contract_sha256": hashlib.sha256(contract_text.encode("utf-8")).hexdigest(),
        "student_contract_span": jml_span.to_dict(),
        "bound_java_sha256": hashlib.sha256(bound_source.encode("utf-8")).hexdigest(),
        "parameter_mapping": [
            {"spec_type": type_name, "spec_name": name,
             "java_type": java_type, "java_name": java_name}
            for (type_name, name), (java_type, java_name)
            in zip(student_parameters, java_parameters)
        ],
        "source_map": {
            "submitted_contract": jml_span.to_dict(),
            "target_java_method": SourceSpan(
                "student_java", _line_number(java_source, method_offset),
                _line_number(java_source, method_offset),
            ).to_dict(),
            "bound_contract": SourceSpan(
                "bound_java", _line_number(bound_source, bound_contract_start),
                _line_number(bound_source, bound_contract_start + len(replacement)),
            ).to_dict(),
            "bound_java_method": SourceSpan(
                "bound_java", _line_number(bound_source, bound_method_offset),
                _line_number(bound_source, bound_method_offset),
            ).to_dict(),
        },
    }
    return bound_path, temporary, metadata


def _openjml_diagnostics(output: str) -> list[dict[str, Any]]:
    """Extract stable, source-oriented fragments from OpenJML text output."""
    diagnostics: list[dict[str, Any]] = []
    pattern = re.compile(r"^(?P<source>.*?):(?P<line>\d+):\s+verify:\s+(?P<message>.*)$")
    for raw_line in output.splitlines():
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        diagnostics.append({
            "source": Path(match.group("source")).name,
            "line": int(match.group("line")),
            "message": match.group("message").strip(),
        })
    return diagnostics


def _safe_file_hash(path: Path) -> str:
    try:
        return sha256_file(path)
    except OSError:
        return "unavailable"


def _decode_tool_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not value:
        return ""
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


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
    exceptional_assignable = obligations.get("exceptional_assignable", [])
    output_ensures = obligations.get("output_ensures", [])
    if len(requires) != 1:
        raise SpecError("当前 Profile 要求恰好一个 requires 义务")
    lines.append(f"  @ requires {requires[0]['expression']};")
    for expression in assignable:
        lines.append(f"  @ assignable {expression};")
    for item in ensures:
        lines.append(f"  @ ensures {item['expression']};")
    for item in output_ensures:
        lines.append(f"  @ ensures {item['expression']};")
    if signals or exceptional_assignable:
        lines.append("  @ also")
        lines.append("  @ public exceptional_behavior")
    for expression in exceptional_assignable:
        lines.append(f"  @ assignable {expression};")
    for item in signals:
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
    student_jml_path: Path | None = None,
    method_name: str | None = None,
) -> ChainResult:
    method = method_name or "unknown"
    binding: dict[str, Any] = {
        "mode": "embedded_java_contract" if method_name else "not_requested",
        "method": method,
    }
    temporary: tempfile.TemporaryDirectory[str] | None = None
    java_to_check = java_path
    try:
        if student_jml_path is not None:
            if method_name is None:
                source = student_jml_path.read_text(encoding="utf-8")
                method_match = re.search(r"\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:throws\s+[^;{]+)?[;{]", source)
                if method_match is None:
                    raise ValueError("无法从提交 JML 推断目标方法；请显式提供 method")
                method = method_match.group(1)
            java_to_check, temporary, binding = _bind_student_jml(
                student_jml_path, java_path, method
            )

        if openjml.startswith("wsl:"):
            resolved = str(java_to_check.resolve())
            match = re.match(r"^(?P<drive>[A-Za-z]):\\(?P<rest>.*)$", resolved)
            if match is None:
                return ChainResult("UNKNOWN", ({
                    "code": "WSL_PATH_UNSUPPORTED",
                    "location": "TOOLCHAIN",
                    "category": "验证路径不可用",
                    "observation": f"无法把 Windows 路径转换为 WSL 路径：{resolved}",
                    "guidance": "请使用本地磁盘中的 Java 文件。",
                },), {"engine": "OpenJML ESC", "binding": binding})
            wsl_java_path = (
                f"/mnt/{match.group('drive').lower()}/"
                + match.group("rest").replace("\\", "/")
            )
            command = [
                "wsl.exe", openjml.removeprefix("wsl:"),
                "--esc", *extra_args, wsl_java_path,
            ]
        else:
            command = [openjml, "--esc", *extra_args, str(java_to_check)]
        if method != "unknown" and not any(
            argument == "--method" or argument.startswith("--method=")
            for argument in extra_args
        ):
            # A source file may contain several exercise methods, including
            # deliberately broken examples.  The session's target method is
            # the default OpenJML scope unless the caller explicitly selects
            # another one (the legacy demo relies on that override).
            command.insert(len(command) - 1, f"--method={method}")
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=False,
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
            },), {"engine": "OpenJML ESC", "binding": binding})
        except subprocess.TimeoutExpired:
            return ChainResult("UNKNOWN", ({
                "code": "OPENJML_TIMEOUT",
                "location": "TOOLCHAIN",
                "category": "验证超时",
                "observation": f"OpenJML 在 {timeout} 秒内未完成。",
                "guidance": "检查规格复杂度，或提高 --timeout 后重试。",
            },), {"engine": "OpenJML ESC", "binding": binding})
        except OSError as error:
            return ChainResult("UNKNOWN", ({
                "code": "OPENJML_UNAVAILABLE",
                "location": "TOOLCHAIN",
                "category": "验证工具异常",
                "observation": str(error),
                "guidance": "检查 OpenJML 与 Java 运行环境。",
            },), {"engine": "OpenJML ESC", "binding": binding})

        output = "\n".join(
            part for part in (
                _decode_tool_output(completed.stdout),
                _decode_tool_output(completed.stderr),
            ) if part
        ).strip()
        evidence = {
            "engine": "OpenJML ESC",
            "exit_code": completed.returncode,
            "output": output[-12000:],
            "diagnostics": _openjml_diagnostics(output),
            "binding": binding,
        }
        if java_path.is_file():
            evidence["java_sha256"] = sha256_file(java_path)
        if completed.returncode == 0:
            return ChainResult("PASS", evidence=evidence)
        if completed.returncode == 6:
            return ChainResult("FAIL", ({
                "code": "OPENJML_VERIFICATION_FAILURE",
                "location": "IMPLEMENTATION",
                "category": "实现不满足已绑定的学生 JML",
                "observation": "OpenJML ESC 报告验证失败；具体证明义务见 evidence.diagnostics。",
                "guidance": "根据失败的 postcondition、frame、invariant 或调用前置条件定位实现。",
            },), evidence)
        return ChainResult("UNKNOWN", ({
            "code": "OPENJML_ANALYSIS_ERROR",
            "location": "TOOLCHAIN",
            "category": "验证未完成",
            "observation": f"OpenJML 因解析、类型、参数或系统错误退出（代码 {completed.returncode}）。",
            "guidance": "先修复 evidence.output 中的工具错误，再重新进行一致性判断。",
        },), evidence)
    except (OSError, UnicodeError, ValueError) as error:
        return ChainResult("UNKNOWN", ({
            "code": "JML_JAVA_BINDING_ERROR",
            "location": "BINDING",
            "category": "规格与实现未绑定",
            "observation": str(error),
            "guidance": "确认学生 JML 包含目标方法合同，且 Java 实现包含同名目标方法。",
        },), {
            "engine": "OpenJML ESC",
            "binding": {"mode": "failed", "method": method},
        })
    finally:
        if temporary is not None:
            temporary.cleanup()


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
    bind_student_jml: bool = True,
) -> dict[str, Any]:
    resolved_method = method
    if resolved_method is None:
        try:
            resolved_method = json.loads(requirement_ir.read_text(encoding="utf-8"))["method"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            resolved_method = "unknown"
    nl_jml = check_nl_jml(requirement_ir, student_jml, resolved_method)
    jml_java = check_jml_java(
        student_java,
        openjml,
        timeout,
        openjml_args,
        student_jml if bind_student_jml else None,
        resolved_method,
    )
    session = VerificationSession.start(
        resolved_method,
        {
            "requirement_ir_sha256": _safe_file_hash(requirement_ir),
            "student_jml_sha256": _safe_file_hash(student_jml),
            "student_java_sha256": _safe_file_hash(student_java),
        },
        {
            "openjml": openjml,
            "timeout_seconds": timeout,
            "jml_binding": "submitted_contract" if bind_student_jml else "embedded_java_contract",
        },
    )
    session.add(Evidence(
        "chain_result", "requirement_judge", "需求到 JML 链已完成",
        {"verdict": nl_jml.verdict, "diagnostic_count": len(nl_jml.diagnostics)},
    ))
    session.add(Evidence(
        "chain_result", "openjml_esc", "JML 到 Java 链已完成",
        {"verdict": jml_java.verdict, "diagnostic_count": len(jml_java.diagnostics)},
    ))
    known_failures = [
        name for name, result in (("nl_jml", nl_jml), ("jml_java", jml_java))
        if result.verdict == "FAIL"
    ]
    unknown_chains = [
        name for name, result in (("nl_jml", nl_jml), ("jml_java", jml_java))
        if result.verdict in {"UNKNOWN", "NOT_RUN"}
    ]
    return {
        "nl_jml": nl_jml.to_dict(),
        "jml_java": jml_java.to_dict(),
        "overall": combined_verdict(nl_jml, jml_java),
        "overall_evidence": {
            "known_failures": known_failures,
            "unknown_chains": unknown_chains,
            "interpretation": (
                "存在已确认失败，同时仍有链路未完成。"
                if known_failures and unknown_chains
                else "所有链路均已完成。"
                if not unknown_chains
                else "至少一条链路未完成，不能据此判定整体通过。"
            ),
        },
        "session": session.to_dict(),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="NL-JML 与 JML-Java 双一致性检测")
    parser.add_argument("--requirement-ir", type=Path, required=True)
    parser.add_argument("--student-jml", type=Path, required=True)
    parser.add_argument("--student-java", type=Path, required=True)
    parser.add_argument("--method")
    parser.add_argument("--openjml", default=os.environ.get("OPENJML", "openjml"))
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--openjml-arg", action="append", default=[])
    parser.add_argument(
        "--embedded-java-contract",
        action="store_true",
        help="legacy demo mode: verify the contract already embedded in student-java",
    )
    args = parser.parse_args()
    result = evaluate_consistency(
        args.requirement_ir,
        args.student_jml,
        args.student_java,
        args.method,
        args.openjml,
        args.timeout,
        tuple(args.openjml_arg),
        not args.embedded_java_contract,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
