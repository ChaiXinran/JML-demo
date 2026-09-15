import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from consistency_judge import (
    ChainResult,
    check_jml_java,
    check_nl_jml,
    combined_verdict,
    evaluate_consistency,
)


class ConsistencyJudgeTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[3]
        self.ir = self.root / "Agent" / "exercises" / "follow_user" / "requirement_ir.json"
        self.correct = self.root / "Agent" / "staff" / "fixtures" / "follow_user_complete.java"

    def test_teacher_approved_requirement_ir_accepts_matching_jml(self):
        result = check_nl_jml(self.ir, self.correct)
        self.assertEqual("PASS", result.verdict)
        self.assertEqual("teacher_approved_requirement_ir", result.evidence["basis"])

    def test_unapproved_requirement_ir_is_unknown_not_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ir.json"
            payload = json.loads(self.ir.read_text(encoding="utf-8"))
            payload["status"] = "draft"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = check_nl_jml(path, self.correct)
        self.assertEqual("UNKNOWN", result.verdict)
        self.assertEqual("REQUIREMENT_IR_INVALID", result.diagnostics[0]["code"])

    @patch("consistency_judge.subprocess.run")
    def test_openjml_success_means_java_satisfies_own_jml(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = ""
        run.return_value.stderr = ""
        result = check_jml_java(Path("Student.java"))
        self.assertEqual("PASS", result.verdict)
        self.assertEqual("OpenJML ESC", result.evidence["engine"])

    @patch("consistency_judge.subprocess.run")
    def test_openjml_verification_exit_is_fail(self, run):
        run.return_value.returncode = 6
        run.return_value.stdout = "verification failure"
        run.return_value.stderr = ""
        result = check_jml_java(Path("Student.java"))
        self.assertEqual("FAIL", result.verdict)

    @patch("consistency_judge.subprocess.run")
    def test_openjml_parse_error_is_unknown(self, run):
        run.return_value.returncode = 1
        run.return_value.stdout = "parse error"
        run.return_value.stderr = ""
        result = check_jml_java(Path("Student.java"))
        self.assertEqual("UNKNOWN", result.verdict)
        self.assertEqual("OPENJML_ANALYSIS_ERROR", result.diagnostics[0]["code"])

    def test_submitted_jml_is_bound_to_target_before_openjml(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            student_jml = root / "NetworkInterface.java"
            student_jml.write_text(self.correct.read_text(encoding="utf-8"), encoding="utf-8")
            student_java = root / "Student.java"
            student_java.write_text(
                "public class Student {\n"
                "  public void followUser(int id1, int id2) { }\n"
                "}\n",
                encoding="utf-8",
            )
            observed = {}

            def run(command, **_kwargs):
                observed["command"] = command
                observed["source"] = Path(command[-1]).read_text(encoding="utf-8")
                class Completed:
                    returncode = 0
                    stdout = ""
                    stderr = ""
                return Completed()

            with patch("consistency_judge.subprocess.run", side_effect=run):
                result = check_jml_java(
                    student_java,
                    student_jml_path=student_jml,
                    method_name="followUser",
                )
        self.assertEqual("PASS", result.verdict)
        self.assertEqual("injected_contract", result.evidence["binding"]["mode"])
        self.assertIn("--method=followUser", observed["command"])
        self.assertIn("requires containsUser(id1)", observed["source"])
        self.assertIn("public void followUser(int id1, int id2)", observed["source"])
        binding = result.evidence["binding"]
        self.assertEqual("id1", binding["parameter_mapping"][0]["java_name"])
        self.assertEqual("student_java", binding["source_map"]["target_java_method"]["source"])
        self.assertEqual("bound_java", binding["source_map"]["bound_contract"]["source"])

    def test_binding_failure_is_unknown_and_does_not_run_openjml(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            student_jml = root / "NetworkInterface.java"
            student_jml.write_text(self.correct.read_text(encoding="utf-8"), encoding="utf-8")
            student_java = root / "Student.java"
            student_java.write_text("public class Student {}\n", encoding="utf-8")
            with patch("consistency_judge.subprocess.run") as run:
                result = check_jml_java(
                    student_java,
                    student_jml_path=student_jml,
                    method_name="followUser",
                )
        self.assertEqual("UNKNOWN", result.verdict)
        self.assertEqual("JML_JAVA_BINDING_ERROR", result.diagnostics[0]["code"])
        run.assert_not_called()

    def test_consistency_result_contains_reproducible_session_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            java = root / "Student.java"
            java.write_text("public class Student { public void followUser(int a, int b) {} }", encoding="utf-8")
            with patch("consistency_judge.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = ""
                run.return_value.stderr = ""
                result = evaluate_consistency(self.ir, self.correct, java)
        self.assertIn("session", result)
        self.assertEqual("followUser", result["session"]["method"])
        self.assertEqual(64, len(result["session"]["inputs"]["student_jml_sha256"]))
        self.assertEqual([], result["overall_evidence"]["known_failures"])

    @patch("consistency_judge.subprocess.run")
    def test_wsl_openjml_converts_windows_source_path(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = ""
        run.return_value.stderr = ""
        check_jml_java(
            Path(r"D:\course\Student.java"),
            "wsl:/home/student/openjml/openjml",
        )
        command = run.call_args.args[0]
        self.assertEqual("wsl.exe", command[0])
        self.assertEqual("/home/student/openjml/openjml", command[1])
        self.assertTrue(command[-1].endswith("/course/Student.java"))

    @patch("consistency_judge.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_openjml_is_unknown(self, _run):
        result = check_jml_java(Path("Student.java"))
        self.assertEqual("UNKNOWN", result.verdict)

    def test_bad_spec_can_pass_implementation_without_overall_pass(self):
        self.assertEqual(
            "SPECIFICATION_INCORRECT",
            combined_verdict(ChainResult("FAIL"), ChainResult("PASS")),
        )


if __name__ == "__main__":
    unittest.main()
