"""Machine-facing CLI for reference JML versus submitted JML evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.profile import ProfileError
from core.suite import load_suite
from profiles.network_v1 import DEFAULT_PROFILE
from profiles.registry import PROFILES
from semantic_judge import (
    RESULT_SCHEMA_VERSION, Diagnostic, SemanticDiagnosticCode, SemanticResult,
    SpecError, evaluate_sources, parse_contract,
)


MAX_SUBMISSION_BYTES = 1024 * 1024


class SubmissionTooLargeError(Exception):
    pass


def error_payload(code: str, observation: str) -> dict:
    """Keep operator details out of the machine result forwarded to students."""
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": "ERROR",
        "diagnostics": [{
            "code": code,
            "location": "JUDGE",
            "category": "评测未完成",
            "observation": observation,
            "guidance": "请由评测机维护者检查标准错误中的详细信息，再重新评测。",
        }],
    }


class JudgeArgumentParser(argparse.ArgumentParser):
    def __init__(self, *, json_mode: bool, **kwargs):
        super().__init__(**kwargs)
        self.json_mode = json_mode

    def error(self, message: str) -> None:
        if self.json_mode:
            print(json.dumps(error_payload(
                "JUDGE_ARGUMENTS", "评测调用参数无效。",
            ), ensure_ascii=False))
            self.exit(2, f"评测调用参数错误：{message}\n")
        super().error(message)


def read_submission(source: str) -> str:
    if source == "-":
        data = sys.stdin.buffer.read(MAX_SUBMISSION_BYTES + 1)
    else:
        with Path(source).open("rb") as stream:
            data = stream.read(MAX_SUBMISSION_BYTES + 1)
    if len(data) > MAX_SUBMISSION_BYTES:
        raise SubmissionTooLargeError
    return data.decode("utf-8-sig")


def submission_format_failure(observation: str, guidance: str) -> SemanticResult:
    return SemanticResult(0, False, (Diagnostic(
        SemanticDiagnosticCode.JML_FORMAT_OR_SYMBOL.value,
        "SUBMISSION", "JML 源码格式", observation, guidance,
    ),))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = JudgeArgumentParser(
        json_mode="--json" in sys.argv[1:],
        description="Unit 3 JML–JML 一致性评测机组件",
        allow_abbrev=False,
    )
    parser.add_argument("submission", help="UTF-8 JML 源码（含目标方法声明）；- 表示标准输入")
    parser.add_argument("--suite", type=Path, help="方法 suite 配置；包含参考 JML、Profile 和测试点")
    parser.add_argument("--reference", type=Path, help="兼容模式：服务器端完整参考 JML 接口")
    parser.add_argument("--method", help="兼容模式：要评测的方法，默认 followUser")
    parser.add_argument("--json", action="store_true", help="输出结构化诊断 JSON")
    args = parser.parse_args()
    if args.suite and (args.reference or args.method):
        parser.error("使用 --suite 时不要再传 --reference 或 --method")
    if not args.suite and args.reference is None:
        parser.error("必须提供 --suite，或使用兼容模式的 --reference")
    try:
        if args.suite:
            suite = load_suite(args.suite, PROFILES)
            reference = suite.reference
            method = suite.method
            profile = suite.profile
        else:
            reference = args.reference
            method = args.method or "followUser"
            profile = DEFAULT_PROFILE
        # Read the trusted reference separately: invalid server assets must
        # never be turned into a student syntax failure or a score of zero.
        with reference.open("rb") as stream:
            reference_data = stream.read(MAX_SUBMISSION_BYTES + 1)
        if len(reference_data) > MAX_SUBMISSION_BYTES:
            raise ProfileError("参考合同超过 1 MiB 上限")
        reference_source = reference_data.decode("utf-8-sig")
        parse_contract(reference_source, method, profile)
    except (OSError, UnicodeError, SpecError, ProfileError, RecursionError, MemoryError) as error:
        print(f"服务器端 Suite、参考合同或资源不可用：{error}", file=sys.stderr)
        if args.json:
            print(json.dumps(error_payload(
                "JUDGE_CONFIGURATION", "服务器端 Suite、Profile 或参考合同不可用。",
            ), ensure_ascii=False))
        return 2
    try:
        student_source = read_submission(args.submission)
    except OSError as error:
        print(f"无法读取学生提交：{error}", file=sys.stderr)
        if args.json:
            print(json.dumps(error_payload(
                "SUBMISSION_UNAVAILABLE", "评测机未能读取本次提交材料。",
            ), ensure_ascii=False))
        return 2
    except UnicodeError:
        result = submission_format_failure(
            "提交材料不是有效的 UTF-8 文本。",
            "请将 JML 源码保存为 UTF-8 后重新提交。",
        )
    except SubmissionTooLargeError:
        result = submission_format_failure(
            f"提交材料超过 {MAX_SUBMISSION_BYTES} 字节上限。",
            "请删除无关内容后重新提交，单次提交最多为 1 MiB。",
        )
    except MemoryError:
        print("评测机读取提交时内存不足", file=sys.stderr)
        if args.json:
            print(json.dumps(error_payload(
                "JUDGE_RESOURCE_ERROR", "评测机资源不足，本次评测未完成。",
            ), ensure_ascii=False))
        return 2
    else:
        try:
            result = evaluate_sources(reference_source, student_source, method, profile)
        except (SpecError, ProfileError) as error:
            print(f"服务器端评测配置不可用：{error}", file=sys.stderr)
            if args.json:
                print(json.dumps(error_payload(
                    "JUDGE_CONFIGURATION", "服务器端参考合同或评测语义配置无效。",
                ), ensure_ascii=False))
            return 2
        except (RecursionError, MemoryError):
            print("评测器内部资源或递归限制异常", file=sys.stderr)
            if args.json:
                print(json.dumps(error_payload(
                    "JUDGE_RESOURCE_ERROR", "评测机资源异常，本次评测未完成。",
                ), ensure_ascii=False))
            return 2
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    elif result.passed:
        print("规格评测通过：全部语义义务均满足。")
    else:
        print(f"规格评测未通过：得分 {result.score}")
        for item in result.diagnostics:
            print(f"- [{item.location}] {item.category}：{item.observation}")
            print(f"  建议：{item.guidance}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
