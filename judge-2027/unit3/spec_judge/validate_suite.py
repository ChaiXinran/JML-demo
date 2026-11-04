"""Validate one declarative JML suite before it is used for grading."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from core.profile import ProfileError
from core.errors import SpecError
from core.mutations import generate_contract_mutations
from core.judge import accepts_normal_transition, normal_applicable
from core.suite import load_suite
from profiles.registry import PROFILES
from semantic_judge import evaluate_sources, parse_contract


def validate(path: Path) -> dict:
    suite = load_suite(path, PROFILES)
    reference = suite.reference.read_text(encoding="utf-8")
    result = evaluate_sources(reference, reference, suite.method, suite.profile)
    if not result.passed:
        raise ProfileError(
            "参考 JML 未通过 suite 自检："
            + "; ".join(item.observation for item in result.diagnostics)
        )
    contract = parse_contract(reference, suite.method, suite.profile)
    generated_points = [
        point for point in suite.post_points if "generated-mutation" in point.tags
    ]
    generated_applicable = [
        point for point in generated_points
        if normal_applicable(contract, point, suite.profile)
    ]
    generated_accepted = sum(
        accepts_normal_transition(contract, point, suite.profile)
        for point in generated_applicable
    )
    mutations = generate_contract_mutations(reference, suite.method)
    by_id = {mutation.id: mutation for mutation in mutations}
    reviewed = suite.quality.get("equivalent_mutations", {})
    for mutation_id, digest in reviewed.items():
        mutation = by_id.get(mutation_id)
        if mutation is None or hashlib.sha256(mutation.source.encode("utf-8")).hexdigest() != digest:
            raise ProfileError(f"等价变异审核记录已过期：{mutation_id}，请重新审核源码后更新 SHA-256")
    survivors = [
        mutation.id
        for mutation in mutations
        if evaluate_sources(
            reference, mutation.source, suite.method, suite.profile
        ).passed
    ]
    killed = len(mutations) - len(survivors)
    mutation_score = round(100 * killed / len(mutations)) if mutations else 100
    if set(reviewed) - set(survivors):
        raise ProfileError("已审核等价变异被新测试点区分，请复核领域状态或移除过期审核记录")
    unexpected_survivors = [name for name in survivors if name not in reviewed]
    scored_total = len(mutations) - len(reviewed)
    effective_score = round(100 * killed / scored_total) if scored_total else 100
    minimum_score = suite.quality.get("min_mutation_score", 0)
    if effective_score < minimum_score:
        raise ProfileError(
            f"剔除已审核等价变异后的得分 {effective_score} 低于要求 {minimum_score}；"
            f"未解释的存活变异：{', '.join(unexpected_survivors)}"
        )
    return {
        "valid": True,
        "suite": suite.name,
        "schema_version": suite.version,
        "profile": suite.profile.name,
        "method": suite.method,
        "pre_points": len(suite.pre_points),
        "post_points": len(suite.post_points),
        "pre_weight": sum(point.weight for point in suite.pre_points),
        "post_weight": sum(point.weight for point in suite.post_points),
        "generated_post": {
            "total": len(generated_points),
            "normal_applicable": len(generated_applicable),
            "accepted_by_reference": generated_accepted,
            "rejected_by_reference": len(generated_applicable) - generated_accepted,
        },
        "mutations": {
            "total": len(mutations),
            "killed": killed,
            "score": mutation_score,
            "survivors": survivors,
            "reviewed_equivalent": sorted(reviewed),
            "unexpected_survivors": unexpected_survivors,
            "effective_score": effective_score,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 JML 一致性评测 suite")
    parser.add_argument("suite", type=Path)
    args = parser.parse_args()
    try:
        payload = validate(args.suite)
    except (OSError, UnicodeError, ProfileError, SpecError, RecursionError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
