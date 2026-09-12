import dataclasses
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from core.contracts import parse_contract as parse_generic_contract
from core.judge import accepts_normal_transition, compare_contracts
from core.profile import ProfileError, Scenario
from core.suite import load_suite
from semantic_judge import SemanticDiagnosticCode, evaluate_sources
from profiles.network_v1 import DEFAULT_PROFILE
from profiles.registry import PROFILES
from smt_counterexample import counterexamples
from validate_suite import validate


class RecordingProfile:
    """Proves that the judge depends on the profile protocol, not globals."""

    name = "recording_network_v1"
    allowed_calls = DEFAULT_PROFILE.allowed_calls
    symbols = DEFAULT_PROFILE.symbols
    grading = DEFAULT_PROFILE.grading

    def __init__(self):
        self.calls = []

    def evaluate_call(self, name, values, context):
        self.calls.append(name)
        return DEFAULT_PROFILE.evaluate_call(name, values, context)

    def pre_scenarios(self, method_name):
        return DEFAULT_PROFILE.pre_scenarios(method_name)

    def post_scenarios(self, method_name):
        return DEFAULT_PROFILE.post_scenarios(method_name)

    def parameter_types(self, method_name):
        if method_name == "anotherMethod":
            return {}
        return DEFAULT_PROFILE.parameter_types(method_name)


ROOT = Path(__file__).resolve().parents[3]
REFERENCE = ROOT / "Agent" / "staff" / "fixtures" / "follow_user_complete.java"
SAMPLES = ROOT / "Agent" / "exercises" / "follow_user" / "samples"
SUITE = Path(__file__).parent / "suites" / "NetworkInterface" / "followUser" / "suite.yaml"
CONTAINS_BOTH_SUITE = Path(__file__).parent / "suites" / "NetworkInterface" / "containsBoth" / "suite.yaml"
CAN_INTERACT_SUITE = Path(__file__).parent / "suites" / "NetworkInterface" / "canInteract" / "suite.yaml"
COUNTER_SUITE = Path(__file__).parent / "suites" / "CounterInterface" / "checkNonNegative" / "suite.yaml"


class SemanticJudgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = REFERENCE.read_text(encoding="utf-8")

    def judge(self, filename: str):
        return evaluate_sources(self.reference, (SAMPLES / filename).read_text(encoding="utf-8"))

    def test_complete_contract_passes_one_unified_evaluation(self):
        result = evaluate_sources(self.reference, self.reference)
        self.assertTrue(result.passed)
        self.assertEqual(100, result.score)
        self.assertEqual((), result.diagnostics)

    def test_missing_normal_condition_has_precise_diagnostic(self):
        result = self.judge("missing-normal-condition.java")
        self.assertFalse(result.passed)
        self.assertIn(SemanticDiagnosticCode.NORMAL_CONDITION_MISMATCH.value, {item.code for item in result.diagnostics})
        issue = next(item for item in result.diagnostics if item.code == SemanticDiagnosticCode.NORMAL_CONDITION_MISMATCH.value)
        self.assertEqual("NORMAL_CONDITION", issue.location)
        self.assertNotIn("containsUser", issue.guidance)

    def test_reversed_postconditions_are_rejected(self):
        result = self.judge("wrong-relation-direction.java")
        locations = {item.location for item in result.diagnostics}
        self.assertIn("FORWARD_POSTCONDITION", locations)
        self.assertIn("INVERSE_POSTCONDITION", locations)

    def test_overlapping_exception_conditions_are_rejected(self):
        result = self.judge("overlapping-exceptions.java")
        locations = {item.location for item in result.diagnostics}
        self.assertIn("SECOND_USER_MISSING", locations)
        self.assertIn("SELF_FOLLOW", locations)
        self.assertIn("DUPLICATE_FOLLOW", locations)

    def test_unknown_interface_symbol_is_a_format_diagnostic(self):
        result = self.judge("hallucinated-symbol.java")
        self.assertEqual(0, result.score)
        self.assertEqual("JML_FORMAT_OR_SYMBOL", result.diagnostics[0].code)

    def test_unfilled_placeholder_is_a_format_diagnostic(self):
        result = self.judge("incomplete.java")
        self.assertEqual(0, result.score)
        self.assertEqual("JML_FORMAT_OR_SYMBOL", result.diagnostics[0].code)
        self.assertRegex(result.diagnostics[0].observation, r"第 \d+ 行")

    def test_evaluation_uses_an_injected_profile(self):
        profile = RecordingProfile()
        result = evaluate_sources(self.reference, self.reference, profile=profile)
        self.assertTrue(result.passed)
        self.assertIn("containsUser", profile.calls)
        self.assertIn("isFollowing", profile.calls)

    def test_declarative_suite_reproduces_follow_user_scenarios(self):
        suite = load_suite(SUITE, {DEFAULT_PROFILE.name: DEFAULT_PROFILE})
        self.assertEqual("followUser", suite.method)
        self.assertEqual(9, len(suite.pre_points))
        self.assertEqual(5, len(suite.post_points))
        result = evaluate_sources(self.reference, self.reference, suite.method, suite.profile)
        self.assertTrue(result.passed)

    def test_profile_mutations_generate_stable_oracle_checked_post_points(self):
        suite = load_suite(SUITE, PROFILES)
        repeated = load_suite(SUITE, PROFILES)
        self.assertEqual(suite.post_points, repeated.post_points)
        generated = [point for point in suite.post_points if "generated-mutation" in point.tags]
        by_variant = {point.id.rsplit(".", 1)[-1]: point for point in generated}
        self.assertEqual(
            {"correct", "omit_forward", "omit_inverse", "reverse_direction"},
            set(by_variant),
        )
        self.assertEqual(4, len(generated))
        contract = parse_generic_contract(self.reference, suite.method, suite.profile)
        self.assertTrue(accepts_normal_transition(contract, by_variant["correct"], suite.profile))
        for label in ("omit_forward", "omit_inverse", "reverse_direction"):
            self.assertFalse(accepts_normal_transition(contract, by_variant[label], suite.profile))
        self.assertEqual(by_variant["correct"].pre, by_variant["omit_inverse"].pre)
        self.assertFalse(by_variant["correct"].pre.follows(1, 2))

    def test_network_profile_exposes_additional_controlled_variants(self):
        suite = load_suite(SUITE, PROFILES)
        pre = next(point.pre for point in suite.post_points if "generated-mutation" in point.tags)
        before = pre.copy()
        variants = DEFAULT_PROFILE.post_variants("follow_pair", pre, {"id1": 1, "id2": 2})
        self.assertEqual(pre, before)
        self.assertEqual(
            {"correct", "omit_forward", "omit_inverse", "reverse_direction",
             "unrelated_change", "wrong_delete"},
            set(variants),
        )
        self.assertTrue(variants["unrelated_change"].is_blocked(1, 2))
        self.assertFalse(variants["wrong_delete"].follows(3, 1))

    def test_mutation_generator_rejects_unknown_variant(self):
        config = json.loads(SUITE.read_text(encoding="utf-8"))
        points = json.loads((SUITE.parent / "points.yaml").read_text(encoding="utf-8"))
        config["reference"] = str(REFERENCE)
        config["points"] = "points.yaml"
        points["generators"][0]["variants"] = ["nonexistent"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "suite.yaml").write_text(json.dumps(config), encoding="utf-8")
            (root / "points.yaml").write_text(json.dumps(points), encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "不含变体"):
                load_suite(root / "suite.yaml", PROFILES)

    def test_declarative_suite_still_rejects_reversed_relations(self):
        suite = load_suite(SUITE, {DEFAULT_PROFILE.name: DEFAULT_PROFILE})
        student = (SAMPLES / "wrong-relation-direction.java").read_text(encoding="utf-8")
        result = evaluate_sources(self.reference, student, suite.method, suite.profile)
        self.assertEqual(
            {"FORWARD_POSTCONDITION", "INVERSE_POSTCONDITION"},
            {item.location for item in result.diagnostics},
        )
        for diagnostic in result.diagnostics:
            self.assertEqual(1, len(diagnostic.lines))
            self.assertIn("ensures", student.splitlines()[diagnostic.lines[0] - 1])

    def test_success_reports_suite_identity_coverage_and_scope(self):
        suite = load_suite(SUITE, PROFILES)
        result = evaluate_sources(
            self.reference, self.reference, suite.method, suite.profile
        ).to_dict()
        self.assertEqual("NetworkInterface.followUser", result["evaluation"]["suite"])
        self.assertEqual(1, result["evaluation"]["suite_version"])
        self.assertIn(
            result["evaluation"]["guarantee_scope"],
            {"fixed_test_points", "smt_supported_subset"},
        )
        self.assertEqual(9.0, result["coverage"]["applicability"]["total_weight"])

    def test_invalid_reference_is_a_configuration_error(self):
        invalid_reference = self.reference.replace("containsUser(id1)", "containsUser(true)", 1)
        with self.assertRaisesRegex(ProfileError, "参考合同或评测配置无效"):
            evaluate_sources(invalid_reference, self.reference)

    def test_suite_rejects_wrong_argument_set_before_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "schema_version": 1,
                "name": "CounterInterface.invalid",
                "profile": "counter_v1",
                "method": "checkNonNegative",
                "parameters": {},
                "contract_shape": {"requires": 1, "ensures": 1, "signals": 0},
                "grading": {"applicability": 1, "postcondition": 1, "exceptions": 0, "locked": 0},
                "reference": str(COUNTER_SUITE.parent / "reference.java"),
                "points": "points.yaml",
            }
            points = {
                "schema_version": 1,
                "fixtures": {},
                "points": [
                    {"id": "pre", "kind": "pre", "args": {"extra": 1}, "pre": {"value": 0}},
                    {"id": "post", "kind": "post", "args": {}, "pre": {"value": 0}, "post": {"copy": "pre"}},
                ],
            }
            (root / "suite.yaml").write_text(json.dumps(config), encoding="utf-8")
            (root / "points.yaml").write_text(json.dumps(points), encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "参数必须恰好是"):
                load_suite(root / "suite.yaml", PROFILES)

    def test_generic_contract_parser_accepts_another_shape_and_method(self):
        source = """public interface Example {
/*@ requires true;
  @ ensures true;
  @ ensures false;
  @ ensures true;
  @ signals (ExampleException e) false;
  @*/
void anotherMethod();
}"""
        contract = parse_generic_contract(source, "anotherMethod", RecordingProfile())
        self.assertEqual(1, len(contract.requires))
        self.assertEqual(3, len(contract.ensures))
        self.assertEqual(1, len(contract.signals))

    def test_contract_parser_preserves_also_behavior_boundaries(self):
        contract = parse_generic_contract(self.reference, "followUser", DEFAULT_PROFILE)
        self.assertEqual(("normal", "exceptional"), tuple(
            behavior.kind for behavior in contract.behaviors
        ))
        self.assertEqual(2, len(contract.normal_behaviors[0].ensures))
        self.assertEqual(4, len(contract.exceptional_behaviors[0].signals))

    def test_generic_judge_combines_multiple_normal_behaviors(self):
        reference_source = """public interface Example {
/*@ public normal_behavior
  @ requires true;
  @ ensures true;
  @ also
  @ public normal_behavior
  @ requires false;
  @ ensures false;
  @*/
void anotherMethod();
}"""
        candidate_source = """public interface Example {
/*@ public normal_behavior
  @ requires true;
  @ ensures true;
  @*/
void anotherMethod();
}"""
        profile = RecordingProfile()
        reference = parse_generic_contract(reference_source, "anotherMethod", profile)
        candidate = parse_generic_contract(candidate_source, "anotherMethod", profile)
        suite = load_suite(SUITE, {DEFAULT_PROFILE.name: DEFAULT_PROFILE})
        comparison = compare_contracts(
            reference, candidate, list(suite.pre_points), list(suite.post_points), profile
        )
        self.assertTrue(comparison.applicability_matches)
        self.assertTrue(comparison.postcondition_matches)

    def test_frame_store_reference_order_is_not_semantic(self):
        reference_source = """public interface Example {
/*@ requires true;
  @ assignable users[*], audit[*];
  @ ensures true;
  @*/
void anotherMethod();
}"""
        candidate_source = reference_source.replace(
            "users[*], audit[*]", "audit[*], users[*]"
        )
        profile = RecordingProfile()
        reference = parse_generic_contract(reference_source, "anotherMethod", profile)
        candidate = parse_generic_contract(candidate_source, "anotherMethod", profile)
        suite = load_suite(SUITE, PROFILES)
        comparison = compare_contracts(
            reference, candidate, list(suite.pre_points), list(suite.post_points), profile
        )
        self.assertTrue(comparison.locked_text_matches)

    def test_broader_frame_is_rejected(self):
        candidate = self.reference.replace("assignable users[*];", "assignable \\everything;")
        result = evaluate_sources(self.reference, candidate)
        self.assertFalse(result.passed)
        issue = next(
            item for item in result.diagnostics
            if item.code == SemanticDiagnosticCode.LOCKED_CLAUSE_CHANGED.value
        )
        self.assertTrue(issue.lines)

    def test_suite_accepts_reordered_equivalent_ensures(self):
        suite = load_suite(SUITE, {DEFAULT_PROFILE.name: DEFAULT_PROFILE})
        forward = "@ ensures getUser(id1).isFollowing(getUser(id2));"
        inverse = "@ ensures getUser(id2).containsFollower(getUser(id1));"
        student = self.reference.replace(f"{forward}\n      {inverse}", f"{inverse}\n      {forward}")
        result = evaluate_sources(self.reference, student, suite.method, suite.profile)
        self.assertTrue(result.passed)

    def test_suite_accepts_merged_equivalent_ensures(self):
        suite = load_suite(SUITE, {DEFAULT_PROFILE.name: DEFAULT_PROFILE})
        forward = "@ ensures getUser(id1).isFollowing(getUser(id2));"
        inverse = "@ ensures getUser(id2).containsFollower(getUser(id1));"
        merged = (
            "@ ensures getUser(id1).isFollowing(getUser(id2)) && "
            "getUser(id2).containsFollower(getUser(id1));"
        )
        student = self.reference.replace(f"{forward}\n      {inverse}", merged)
        result = evaluate_sources(self.reference, student, suite.method, suite.profile)
        self.assertTrue(result.passed)

    def test_static_types_reject_a_wrong_call_argument(self):
        student = self.reference.replace("containsUser(id1)", "containsUser(true)", 1)
        result = evaluate_sources(self.reference, student)
        self.assertEqual("JML_FORMAT_OR_SYMBOL", result.diagnostics[0].code)
        self.assertIn("不接受参数类型", result.diagnostics[0].observation)

    def test_static_types_require_boolean_clauses(self):
        start = "containsUser(id1) && containsUser(id2)\n      @          && id1 != id2\n      @          && !getUser(id1).isFollowing(getUser(id2))"
        student = self.reference.replace(start, "id1")
        result = evaluate_sources(self.reference, student)
        self.assertEqual("JML_FORMAT_OR_SYMBOL", result.diagnostics[0].code)
        self.assertIn("必须是 bool", result.diagnostics[0].observation)

    def test_second_method_uses_the_same_core_and_profile(self):
        suite = load_suite(CONTAINS_BOTH_SUITE, {DEFAULT_PROFILE.name: DEFAULT_PROFILE})
        reference = suite.reference.read_text(encoding="utf-8")
        correct = evaluate_sources(reference, reference, suite.method, suite.profile)
        wrong = evaluate_sources(
            reference,
            (CONTAINS_BOTH_SUITE.parent / "wrong.java").read_text(encoding="utf-8"),
            suite.method,
            suite.profile,
        )
        self.assertEqual(100, correct.score)
        # The finite grid awards partial credit while rejecting the weaker OR.
        self.assertEqual(82, wrong.score)
        self.assertEqual("POSTCONDITION", wrong.diagnostics[0].location)

    def test_another_class_uses_a_registered_scalar_profile(self):
        suite = load_suite(COUNTER_SUITE, PROFILES)
        reference = suite.reference.read_text(encoding="utf-8")
        wrong_source = (COUNTER_SUITE.parent / "wrong.java").read_text(encoding="utf-8")
        self.assertTrue(evaluate_sources(
            reference, reference, suite.method, suite.profile
        ).passed)
        wrong = evaluate_sources(reference, wrong_source, suite.method, suite.profile)
        self.assertEqual(
            {"unchanged", "above", "below"},
            {point.id.rsplit(".", 1)[-1] for point in suite.post_points},
        )
        # Only the zero boundary differs, so two of three post points pass.
        self.assertEqual(77, wrong.score)
        self.assertEqual("POSTCONDITION_MISMATCH", wrong.diagnostics[0].code)

    def test_existing_profile_can_add_a_new_state_relation(self):
        suite = load_suite(CAN_INTERACT_SUITE, PROFILES)
        reference = suite.reference.read_text(encoding="utf-8")
        wrong_source = (CAN_INTERACT_SUITE.parent / "wrong.java").read_text(encoding="utf-8")
        self.assertTrue(evaluate_sources(
            reference, reference, suite.method, suite.profile
        ).passed)
        wrong = evaluate_sources(reference, wrong_source, suite.method, suite.profile)
        self.assertEqual(94, wrong.score)

    def test_extension_suites_reject_strong_weak_and_illegal_contracts(self):
        cases = (
            (
                CONTAINS_BOTH_SUITE,
                lambda source: source.replace(
                    "containsUser(id1) && containsUser(id2)",
                    "containsUser(id1) || containsUser(id2)",
                ),
                lambda source: source.replace(
                    "containsUser(id1) && containsUser(id2);",
                    "containsUser(id1) && containsUser(id2) && id1 != id2;",
                ),
                "containsUser",
            ),
            (
                CAN_INTERACT_SUITE,
                lambda source: source.replace(
                    "containsUser(id1) && containsUser(id2)\n      @      && !getUser(id1).isBlocked(getUser(id2))",
                    "containsUser(id1) && containsUser(id2)",
                ),
                lambda source: source.replace(
                    "!getUser(id1).isBlocked(getUser(id2));",
                    "!getUser(id1).isBlocked(getUser(id2)) && id1 != id2;",
                ),
                "isBlocked",
            ),
            (
                COUNTER_SUITE,
                lambda source: source.replace("getValue() >= 0", "getValue() >= 0 || true"),
                lambda source: source.replace("getValue() >= 0", "getValue() >= 0 && false"),
                "getValue",
            ),
        )
        for suite_path, make_weak, make_strong, symbol in cases:
            with self.subTest(suite=suite_path.name):
                suite = load_suite(suite_path, PROFILES)
                reference = suite.reference.read_text(encoding="utf-8")
                weak = make_weak(reference)
                strong = make_strong(reference)
                illegal = reference.replace(symbol, "unknownSymbol", 1)
                self.assertTrue(evaluate_sources(
                    reference, reference, suite.method, suite.profile
                ).passed)
                self.assertFalse(evaluate_sources(
                    reference, weak, suite.method, suite.profile
                ).passed)
                self.assertFalse(evaluate_sources(
                    reference, strong, suite.method, suite.profile
                ).passed)
                illegal_result = evaluate_sources(
                    reference, illegal, suite.method, suite.profile
                )
                self.assertEqual("JML_FORMAT_OR_SYMBOL", illegal_result.diagnostics[0].code)

    @unittest.skipUnless(importlib.util.find_spec("z3"), "optional z3-solver is not installed")
    def test_smt_audit_reports_logic_difference_without_changing_fixed_score(self):
        suite = load_suite(CONTAINS_BOTH_SUITE, PROFILES)
        reference = suite.reference.read_text(encoding="utf-8")
        wrong = (suite.reference.parent / "wrong.java").read_text(encoding="utf-8")
        result = evaluate_sources(reference, wrong, suite.method, suite.profile)
        self.assertEqual(82, result.score)
        self.assertEqual("SAT", result.solver["postcondition"]["status"])

    @unittest.skipUnless(importlib.util.find_spec("z3"), "optional z3-solver is not installed")
    def test_required_smt_rejects_difference_missed_by_restricted_points(self):
        suite = load_suite(CONTAINS_BOTH_SUITE, PROFILES)
        reference = suite.reference.read_text(encoding="utf-8")
        candidate = reference.replace(
            "containsUser(id1) && containsUser(id2);",
            "containsUser(id1) && containsUser(id2) && id1 != id2;",
        )
        restricted_pre = tuple(
            point for point in suite.pre_points if point.arguments == {"id1": 1, "id2": 2}
        )
        restricted_post = tuple(
            point for point in suite.post_points if point.arguments == {"id1": 1, "id2": 2}
        )
        profile = dataclasses.replace(
            suite.profile,
            configured_pre=restricted_pre,
            configured_post=restricted_post,
            solver={"mode": "required", "timeout_ms": 1000},
        )
        result = evaluate_sources(reference, candidate, suite.method, profile)
        self.assertFalse(result.passed)
        self.assertEqual(30, result.score)
        self.assertEqual("SAT", result.solver["postcondition"]["status"])
        self.assertIn(
            SemanticDiagnosticCode.POSTCONDITION_MISMATCH.value,
            {item.code for item in result.diagnostics},
        )

    @unittest.skipUnless(importlib.util.find_spec("z3"), "optional z3-solver is not installed")
    def test_smt_witness_can_be_materialized_as_a_discriminating_point(self):
        student = CONTAINS_BOTH_SUITE.parent / "wrong.java"
        payload = counterexamples(CONTAINS_BOTH_SUITE, student)
        point = next(
            item for item in payload["candidate_points"]
            if item["kind"] == "post"
        )
        suite = load_suite(CONTAINS_BOTH_SUITE, PROFILES)
        scenario = Scenario(
            suite.profile.state_from_data(point["pre"]),
            suite.profile.state_from_data(point["post"]),
            point["args"],
        )
        reference = parse_generic_contract(
            suite.reference.read_text(encoding="utf-8"), suite.method, suite.profile
        )
        candidate = parse_generic_contract(
            student.read_text(encoding="utf-8"), suite.method, suite.profile
        )
        comparison = compare_contracts(reference, candidate, [], [scenario], suite.profile)
        self.assertFalse(comparison.postcondition_matches)
        ordinary_result = evaluate_sources(
            suite.reference.read_text(encoding="utf-8"),
            student.read_text(encoding="utf-8"),
            suite.method,
            suite.profile,
        ).to_dict()
        self.assertNotIn("witness", json.dumps(ordinary_result))

    def test_all_declarative_suites_pass_preflight_validation(self):
        for path in (SUITE, CONTAINS_BOTH_SUITE, CAN_INTERACT_SUITE, COUNTER_SUITE):
            with self.subTest(suite=path.name):
                report = validate(path)
                self.assertTrue(report["valid"])
                self.assertGreater(report["pre_points"], 0)
                self.assertGreater(report["post_points"], 0)
                self.assertEqual(100, report["mutations"]["score"])
                self.assertEqual([], report["mutations"]["survivors"])
                if path in (SUITE, COUNTER_SUITE):
                    self.assertGreater(report["generated_post"]["accepted_by_reference"], 0)
                    self.assertGreater(report["generated_post"]["rejected_by_reference"], 0)


if __name__ == "__main__":
    unittest.main()
