"""Maintainer CLI: materialize internal SMT witnesses as candidate suite points."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.profile import ProfileError
from core.smt import SmtBackendUnavailable, SmtStatus, compare_contracts_smt
from core.suite import load_suite
from profiles.registry import PROFILES
from semantic_judge import parse_contract


def counterexamples(suite_path: Path, student_path: Path) -> dict:
    suite = load_suite(suite_path, PROFILES)
    reference = parse_contract(
        suite.reference.read_text(encoding="utf-8"), suite.method, suite.profile
    )
    candidate = parse_contract(
        student_path.read_text(encoding="utf-8"), suite.method, suite.profile
    )
    comparison = compare_contracts_smt(
        reference,
        candidate,
        suite.method,
        suite.profile,
        suite.solver.get("timeout_ms", 1000),
    )
    points = []
    for region in ("applicability", "postcondition", "exceptions"):
        result = getattr(comparison, region)
        if result.status != SmtStatus.SAT or result.witness is None:
            continue
        witness = result.witness
        point = {
            "id": f"smt_{region}",
            "kind": "post" if region == "postcondition" else "pre",
            "args": witness["arguments"],
            "pre": suite.profile.state_data_from_smt_calls(witness["pre_calls"]),
            "public": False,
            "tags": ["smt-counterexample", region],
        }
        if region == "postcondition":
            point["post"] = suite.profile.state_data_from_smt_calls(witness["post_calls"])
        points.append(point)
    return {
        "suite": suite.name,
        "student": student_path.name,
        "statuses": comparison.to_dict(),
        "candidate_points": points,
        "warning": "加入 points 前必须运行 validate_suite.py；模型只覆盖当前 SMT/Profile 子集。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="将 JML SMT 差异转换为候选测试点")
    parser.add_argument("student", type=Path)
    parser.add_argument("--suite", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = counterexamples(args.suite, args.student)
    except (OSError, ProfileError, SmtBackendUnavailable) as error:
        print(f"SMT 反例生成失败：{error}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
