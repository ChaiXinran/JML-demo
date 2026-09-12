"""Validate one declarative JML suite before it is used for grading."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.profile import ProfileError
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
    survivors = [
        mutation.id
        for mutation in mutations
        if evaluate_sources(
            reference, mutation.source, suite.method, suite.profile
        ).passed
    ]
    killed = len(mutations) - len(survivors)
    mutation_score = round(100 * killed / len(mutations)) if mutations else 100
    minimum_score = suite.quality.get("min_mutation_score", 0)
    if mutation_score < minimum_score:
        raise ProfileError(
            f"变异得分 {mutation_score} 低于要求 {minimum_score}；"
            f"存活变异：{', '.join(survivors)}"
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
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 JML 一致性评测 suite")
    parser.add_argument("suite", type=Path)
    args = parser.parse_args()
    try:
        payload = validate(args.suite)
    except (OSError, ProfileError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
