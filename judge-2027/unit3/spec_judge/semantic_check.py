"""Command-line entrypoint for the unified followUser semantic evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.profile import ProfileError
from core.suite import load_suite
from profiles.network_v1 import DEFAULT_PROFILE
from profiles.registry import PROFILES
from semantic_judge import SpecError, evaluate_files


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Unit 3 统一 JML 语义一致性评测")
    parser.add_argument("java_source", type=Path, help="学生填写后的 Java 接口文件")
    parser.add_argument("--suite", type=Path, help="方法 suite 配置；包含参考 JML、Profile 和测试点")
    parser.add_argument("--reference", type=Path, help="兼容模式：服务器端完整参考 JML 接口")
    parser.add_argument("--method", help="兼容模式：要评测的方法，默认 followUser")
    parser.add_argument("--json", action="store_true", help="输出结构化诊断 JSON")
    args = parser.parse_args()
    try:
        if args.suite:
            if args.reference or args.method:
                raise ProfileError("使用 --suite 时不要再传 --reference 或 --method")
            suite = load_suite(args.suite, PROFILES)
            reference = suite.reference
            method = suite.method
            profile = suite.profile
        else:
            if args.reference is None:
                raise ProfileError("必须提供 --suite，或使用兼容模式的 --reference")
            reference = args.reference
            method = args.method or "followUser"
            profile = DEFAULT_PROFILE
        result = evaluate_files(reference, args.java_source, method, profile)
    except (OSError, SpecError, ProfileError) as error:
        print(f"规格评测配置错误：{error}", file=sys.stderr)
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
