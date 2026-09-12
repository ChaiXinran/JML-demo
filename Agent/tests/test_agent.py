import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hw9_agent.critic import analyze
from hw9_agent.client import ModelClientError, extract_chat_content, extract_output_text
from hw9_agent.parser import parse_interface
from hw9_agent.pipeline import run_pipeline
from hw9_agent.exercise import (
    ExerciseBundle,
    StructuralDiagnosticCode,
    build_review_prompt,
    deterministic_check,
)
from hw9_agent.webapp import ExerciseWebApp, parse_coach_feedback
from hw9_agent.template_builder import build_exercise_package, build_template


FIXTURE = r"""
public interface DemoInterface {
    //@ ensures \result == value;
    public /*@ pure @*/ int getValue();

    /*@ public normal_behavior
      @ requires value >= 0;
      @ assignable items;
      @ ensures items.length == \old(items.length) + 1;
      @ also
      @ public exceptional_behavior
      @ signals (IllegalArgumentException e) value < 0;
      @*/
    public /*@ safe @*/ void add(int value);
}
"""


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "DemoInterface.java"
        self.path.write_text(FIXTURE, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_parses_single_and_block_specs(self):
        interface = parse_interface(self.path)
        self.assertEqual(["getValue", "add"], [m.name for m in interface.methods])
        self.assertEqual(["pure"], interface.methods[0].markers)
        self.assertEqual(["value >= 0"], interface.methods[1].requires)
        self.assertEqual(1, len(interface.methods[1].signals))

    def test_parses_unannotated_method_from_teacher_skeleton(self):
        self.path.write_text(
            "public interface DemoInterface { public void draft(int value); }",
            encoding="utf-8",
        )
        method = parse_interface(self.path).methods[0]
        self.assertEqual("draft", method.name)
        self.assertEqual("", method.jml)

    def test_pure_method_creates_side_effect_obligation(self):
        method = parse_interface(self.path).methods[0]
        result = analyze(method)
        self.assertTrue(any("状态必须完全一致" in item for item in result.test_obligations))

    def test_extracts_responses_api_output_text(self):
        payload = {
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "hello"}],
            }]
        }
        self.assertEqual("hello", extract_output_text(payload))
        with self.assertRaises(ModelClientError):
            extract_output_text({"output": []})

    def test_extracts_deepseek_chat_content(self):
        payload = {"choices": [{"message": {"content": "demo"}}]}
        self.assertEqual("demo", extract_chat_content(payload))
        with self.assertRaises(ModelClientError):
            extract_chat_content({"choices": []})

    def test_five_stage_pipeline_with_fake_model(self):
        root = Path(self.temp.name)
        official = root / "official" / "com" / "oocourse" / "spec1" / "main"
        official.mkdir(parents=True)
        (official / "NetworkInterface.java").write_text(
            """public interface NetworkInterface {
            //@ ensures \\result == true;
            public /*@ pure @*/ boolean followUser(int id1, int id2);
            }""",
            encoding="utf-8",
        )
        for name in ("UserInterface", "VideoInterface"):
            (official / f"{name}.java").write_text(
                f"public interface {name} {{}}", encoding="utf-8"
            )
        case_dir = root / "case"
        case_dir.mkdir()
        (case_dir / "requirement.md").write_text("demo", encoding="utf-8")
        (case_dir / "blank_plan.json").write_text(
            '{"status":"teacher_approved"}', encoding="utf-8"
        )
        project_root = Path(__file__).resolve().parent.parent

        class FakeClient:
            def __init__(self):
                self.count = 0

            def generate(self, prompt):
                self.count += 1
                self.last_prompt = prompt
                return f"stage-{self.count}"

        fake = FakeClient()
        result = run_pipeline(
            client=fake,
            project_root=project_root,
            source_root=str(root),
            case_dir=case_dir,
            output_dir=root / "run",
            method_name="followUser",
        )
        self.assertEqual(5, fake.count)
        self.assertEqual(
            {"analyzer", "planner", "template", "critic", "assessment"},
            set(result.artifacts),
        )
        self.assertIn("Teacher-authored authoritative JML", fake.last_prompt)
        self.assertIn("Teacher-approved blank plan", fake.last_prompt)
        self.assertIn("Prior artifact: review.yaml", fake.last_prompt)

    def test_exercise_detects_unfilled_blank(self):
        project_root = Path(__file__).resolve().parent.parent
        bundle = ExerciseBundle.load(project_root / "exercises" / "follow_user")
        submission = (
            project_root / "exercises" / "follow_user" / "samples" / "incomplete.java"
        ).read_text(encoding="utf-8")
        findings = deterministic_check(bundle, submission)
        self.assertTrue(any(item["code"] == StructuralDiagnosticCode.UNFILLED_BLANKS.value for item in findings))

    def test_exercise_accepts_complete_structure_for_semantic_review(self):
        project_root = Path(__file__).resolve().parent.parent
        bundle = ExerciseBundle.load(project_root / "exercises" / "follow_user")
        submission = (
            project_root / "staff" / "fixtures" / "follow_user_complete.java"
        ).read_text(encoding="utf-8")
        findings = deterministic_check(bundle, submission)
        self.assertEqual(["STRUCTURE_OK"], [item["code"] for item in findings])

    def test_web_payload_does_not_expose_hidden_rubric(self):
        project_root = Path(__file__).resolve().parent.parent
        app = ExerciseWebApp(
            project_root=project_root,
            exercise_dir=project_root / "exercises" / "follow_user",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        payload = app.public_exercise()
        self.assertNotIn("rubric", payload)
        self.assertNotIn("criteria", payload)
        self.assertNotIn("correct", {sample["id"] for sample in payload["samples"]})
        self.assertNotIn("solution", payload["allowed_modes"])
        self.assertEqual("guided", payload["feedback_contract"]["hint"]["level"])
        self.assertIn("template", payload)

    def test_consistency_demo_exposes_labels_but_not_server_paths(self):
        project_root = Path(__file__).resolve().parent.parent
        app = ExerciseWebApp(
            project_root=project_root,
            exercise_dir=project_root / "exercises" / "follow_user",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        cases = app.public_exercise()["consistency_demo_cases"]
        self.assertEqual(3, len(cases))
        self.assertEqual(
            {"id", "label", "description", "jml_excerpt", "java_excerpt", "expected"},
            set(cases[0]),
        )
        self.assertNotIn("student_jml", json.dumps(cases))

    def test_web_uses_deterministic_semantic_judge_without_exposing_reference(self):
        project_root = Path(__file__).resolve().parent.parent
        app = ExerciseWebApp(
            project_root=project_root,
            exercise_dir=project_root / "exercises" / "follow_user",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        submission = (
            project_root / "exercises" / "follow_user" / "samples" / "wrong-relation-direction.java"
        ).read_text(encoding="utf-8")
        result = app.semantic_check(submission)
        self.assertFalse(result["passed"])
        self.assertIn("FORWARD_POSTCONDITION", {item["location"] for item in result["diagnostics"]})
        self.assertEqual("NetworkInterface.followUser", result["evaluation"]["suite"])
        self.assertNotIn("reference", json.dumps(result, ensure_ascii=False).lower())

    def test_web_returns_unfilled_blank_feedback_without_semantic_judge_or_llm(self):
        project_root = Path(__file__).resolve().parent.parent
        app = ExerciseWebApp(
            project_root=project_root,
            exercise_dir=project_root / "exercises" / "follow_user",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        submission = (
            project_root / "exercises" / "follow_user" / "samples" / "incomplete.java"
        ).read_text(encoding="utf-8")
        with patch.object(app, "semantic_check", side_effect=AssertionError("semantic judge must not run")), \
             patch("hw9_agent.webapp.DeepSeekChatClient", side_effect=AssertionError("LLM must not run")):
            result = app.review({"submission": submission, "mode": "hint"})
        self.assertEqual(["UNFILLED_BLANKS"], [item["code"] for item in result["checks"]])
        self.assertIsNone(result["semantic"])
        self.assertEqual("INCOMPLETE", result["coach"]["verdict"])
        self.assertIn("填写", result["coach"]["next_step"])

    def test_web_review_without_api_key_returns_deterministic_result(self):
        project_root = Path(__file__).resolve().parent.parent
        app = ExerciseWebApp(
            project_root=project_root,
            exercise_dir=project_root / "exercises" / "follow_user",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        submission = (
            project_root / "exercises" / "follow_user" / "samples" / "wrong-relation-direction.java"
        ).read_text(encoding="utf-8")
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": ""}), \
             patch("hw9_agent.webapp.DeepSeekChatClient", side_effect=AssertionError("LLM must not run")):
            result = app.review({"submission": submission, "mode": "hint"})
        self.assertEqual("STRUCTURE_OK", result["checks"][0]["code"])
        self.assertFalse(result["semantic"]["passed"])
        self.assertEqual("NetworkInterface.followUser", result["semantic"]["evaluation"]["suite"])
        self.assertIsNone(result["coach"])

    def test_web_returns_structured_coach_feedback_not_raw_model_yaml(self):
        project_root = Path(__file__).resolve().parent.parent
        app = ExerciseWebApp(
            project_root=project_root,
            exercise_dir=project_root / "exercises" / "follow_user",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        submission = (
            project_root / "exercises" / "follow_user" / "samples" / "wrong-relation-direction.java"
        ).read_text(encoding="utf-8")
        model_response = json.dumps({
            "verdict": "NEEDS_REVISION",
            "progress_summary": "后置条件的关系方向需要调整。",
            "correct_parts": ["接口框架保持完整"],
            "issues": [{
                "location": "FORWARD_POSTCONDITION",
                "category": "后置状态关系",
                "explanation": "关注关系的方向与题意不一致。",
                "counterexample": "成功后应检查发起关注的一方。",
            }],
            "next_step": "检查两个关系谓词中用户的位置。",
            "may_resubmit": True,
        }, ensure_ascii=False)
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}), \
             patch("hw9_agent.webapp.DeepSeekChatClient") as client_type:
            client_type.return_value.generate.return_value = model_response
            result = app.review({"submission": submission, "mode": "review"})
            client_type.assert_called_once()
        self.assertNotIn("feedback", result)
        self.assertEqual("NEEDS_REVISION", result["coach"]["verdict"])
        self.assertEqual("FORWARD_POSTCONDITION", result["coach"]["issues"][0]["location"])

    def test_invalid_model_text_becomes_safe_structured_coach_feedback(self):
        coach = parse_coach_feedback("verdict: NEEDS_REVISION\nnext_step: try again")
        self.assertEqual("UNCERTAIN", coach["verdict"])
        self.assertEqual([], coach["correct_parts"])
        self.assertEqual("Agent 反馈格式异常", coach["issues"][0]["category"])
        self.assertNotIn("verdict:", json.dumps(coach, ensure_ascii=False))

    def test_web_ui_renders_structured_coach_cards_not_raw_feedback(self):
        project_root = Path(__file__).resolve().parent.parent
        script = (project_root / "web" / "app.js").read_text(encoding="utf-8")
        page = (project_root / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function renderCoach(coach)", script)
        self.assertIn("renderCoach(data.coach)", script)
        self.assertIn("if(cases.length){$('consistency-demo').classList.remove('hidden')", script)
        self.assertIn('id="consistency-demo" class="panel demo-box hidden"', page)
        self.assertNotIn("data.feedback", script)

    def test_student_prompt_uses_public_feedback_contract_only(self):
        project_root = Path(__file__).resolve().parent.parent
        bundle = ExerciseBundle.load(project_root / "exercises" / "follow_user")
        submission = (project_root / "staff" / "fixtures" / "follow_user_complete.java").read_text(
            encoding="utf-8"
        )
        prompt = build_review_prompt(project_root, bundle, submission, "hint", [])
        self.assertIn("Public feedback contract", prompt)
        self.assertIn("Return only one valid JSON object.", prompt)
        self.assertNotIn("Return only the YAML review", prompt)
        self.assertNotIn("allowed_categories", prompt)
        self.assertNotIn("Hidden assessment rubric", prompt)
        self.assertNotIn("F01", prompt)

    def test_student_prompt_requests_direct_repair_direction_not_a_question(self):
        project_root = Path(__file__).resolve().parent.parent
        bundle = ExerciseBundle.load(project_root / "exercises" / "follow_user")
        submission = (project_root / "staff" / "fixtures" / "follow_user_complete.java").read_text(
            encoding="utf-8"
        )
        prompt = build_review_prompt(project_root, bundle, submission, "hint", [])
        self.assertIn("direct repair direction", prompt)
        self.assertIn("next_step", prompt)
        self.assertNotIn("reasoning question", prompt)
        self.assertNotIn("next_hint", prompt)

    def test_multiline_quantifier_is_not_truncated(self):
        from hw9_agent.parser import _clauses

        clauses = _clauses(
            "ensures (\\forall int i;\n  0 <= i && i < n;\n  a[i] == 0);",
            "ensures",
        )
        self.assertEqual(["(\\forall int i; 0 <= i && i < n; a[i] == 0)"], clauses)

    def test_parses_semicolonless_block_invariant(self):
        self.path.write_text(
            """public interface DemoInterface {
            /*@ invariant (\\forall int i; 0 <= i && i < items.length; items[i] != null)
              @*/
            //@ ensures \\result == true;
            public boolean ready();
            }""",
            encoding="utf-8",
        )
        interface = parse_interface(self.path)
        self.assertEqual(1, len(interface.invariants))
        self.assertIn("items.length", interface.invariants[0])

    def test_does_not_treat_jml_behavior_header_as_java_method(self):
        self.path.write_text(
            """public interface DemoInterface {
            /*@ public normal_behavior
              @ requires value >= 0;
              @*/
            public void add(int value);
            }""",
            encoding="utf-8",
        )
        interface = parse_interface(self.path)
        self.assertEqual(["add"], [method.name for method in interface.methods])

    def test_template_is_derived_from_complete_embedded_jml(self):
        plan = {
            "student_owned_blanks": [
                {"id": "PRE", "source_jml_selector": {"clause": "requires", "occurrence": 1}},
                {"id": "POST", "source_jml_selector": {"clause": "ensures", "occurrence": 1}},
                {"id": "ERR", "source_jml_selector": {"clause": "signals", "occurrence": 1}},
            ]
        }
        rendered = build_template(FIXTURE, "add", plan)
        self.assertIn("requires {{PRE}};", rendered)
        self.assertIn("ensures {{POST}};", rendered)
        self.assertIn("signals (IllegalArgumentException e) {{ERR}};", rendered)
        self.assertIn("assignable items;", rendered)

    def test_publish_exercise_generates_template_and_web_manifest_from_three_staff_inputs(self):
        requirement = Path(self.temp.name) / "requirement.md"
        requirement.write_text("# Add\n\nAdd one value.", encoding="utf-8")
        blank_plan = Path(self.temp.name) / "blank_plan.json"
        blank_plan.write_text(
            json.dumps(
                {
                    "status": "teacher_approved",
                    "method": "DemoInterface.add",
                    "student_owned_blanks": [
                        {"id": "PRE", "source_jml_selector": {"clause": "requires", "occurrence": 1}},
                        {"id": "POST", "source_jml_selector": {"clause": "ensures", "occurrence": 1}},
                        {"id": "ERR", "source_jml_selector": {"clause": "signals", "occurrence": 1}},
                    ],
                }
            ),
            encoding="utf-8",
        )
        exercise_dir = Path(self.temp.name) / "generated_exercise"

        build_exercise_package(self.path, requirement, blank_plan, exercise_dir)

        self.assertIn("requires {{PRE}};", (exercise_dir / "template.java").read_text(encoding="utf-8"))
        self.assertEqual(requirement.read_text(encoding="utf-8"), (exercise_dir / "requirement.md").read_text(encoding="utf-8"))
        config = json.loads((exercise_dir / "exercise.json").read_text(encoding="utf-8"))
        self.assertEqual("generated_exercise", config["id"])
        self.assertEqual("add", config["method"])
        self.assertEqual(["PRE", "POST", "ERR"], config["placeholders"])
        self.assertNotIn("semantic_suite", config)
        self.assertNotIn("samples", config)
        self.assertNotIn("interface", config)
        self.assertIn("items", config["allowed_symbols"])
        self.assertIn("IllegalArgumentException", config["allowed_symbols"])
        self.assertTrue((exercise_dir / "samples").is_dir())
        sample = exercise_dir / "samples" / "wrong-case.java"
        sample.write_text((exercise_dir / "template.java").read_text(encoding="utf-8"), encoding="utf-8")
        bundle = ExerciseBundle.load(exercise_dir)
        self.assertEqual("add", bundle.config["method"])
        self.assertEqual(
            [{"id": "wrong-case", "label": "样例：wrong case", "file": "samples/wrong-case.java"}],
            bundle.config["samples"],
        )

    def test_publish_exercise_binds_matching_semantic_suite_for_web(self):
        root = Path(self.temp.name)
        requirement = root / "requirement.md"
        requirement.write_text("# Add\n", encoding="utf-8")
        blank_plan = root / "blank_plan.json"
        blank_plan.write_text(
            json.dumps({
                "status": "teacher_approved",
                "method": "DemoInterface.add",
                "student_owned_blanks": [
                    {"id": "PRE", "source_jml_selector": {"clause": "requires", "occurrence": 1}},
                ],
            }),
            encoding="utf-8",
        )
        suite = root / "add.yaml"
        suite.write_text(json.dumps({"method": "add"}), encoding="utf-8")
        exercise_dir = root / "bound_exercise"

        build_exercise_package(self.path, requirement, blank_plan, exercise_dir, semantic_suite=suite)

        project_root = Path(__file__).resolve().parent.parent
        config = json.loads((exercise_dir / "exercise.json").read_text(encoding="utf-8"))
        self.assertEqual(suite.resolve(), (project_root / config["semantic_suite"]).resolve())
        app = ExerciseWebApp(project_root, exercise_dir, "deepseek-chat", "https://api.deepseek.com")
        self.assertEqual(suite.resolve(), app.semantic_suite)
        self.assertNotIn("semantic_suite", app.public_exercise())
        self.assertEqual([], app.public_exercise()["consistency_demo_cases"])

        suite.write_text(json.dumps({"method": "otherMethod"}), encoding="utf-8")
        mismatched_dir = root / "mismatched_exercise"
        with self.assertRaisesRegex(ValueError, "Semantic suite method must be add"):
            build_exercise_package(self.path, requirement, blank_plan, mismatched_dir, semantic_suite=suite)
        self.assertFalse(mismatched_dir.exists())

        missing_dir = root / "missing_suite_exercise"
        with self.assertRaisesRegex(FileNotFoundError, "Semantic suite does not exist"):
            build_exercise_package(
                self.path, requirement, blank_plan, missing_dir,
                semantic_suite=root / "not_found.yaml",
            )
        self.assertFalse(missing_dir.exists())


if __name__ == "__main__":
    unittest.main()
