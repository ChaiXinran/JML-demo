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
