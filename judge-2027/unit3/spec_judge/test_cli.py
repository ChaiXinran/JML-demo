"""Black-box tests for the student-facing CLI and relocatable release ZIP."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CLI = ROOT / "semantic_check.py"
BUILD_RELEASE = ROOT / "build_release.py"
SUITE = ROOT / "suites" / "NetworkInterface" / "followUser" / "suite.yaml"
REFERENCE = SUITE.parent / "reference.java"
WRONG_RELATION = ROOT / "tests" / "fixtures" / "followUser" / "wrong-relation-direction.java"
OLD_TEST_MODULES = {
    "test_consistency_judge.py",
    "test_runtime_verifier.py",
    "test_spec_judge.py",
}


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONPATH", None)
    return env


def run_cli(*args: object, cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *(str(arg) for arg in args)],
        cwd=cwd,
        env=child_env(),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def json_stdout(process: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"CLI stdout must be one JSON document; got {process.stdout!r}; "
            f"stderr={process.stderr!r}"
        ) from error


def assert_normal_result(
    test: unittest.TestCase,
    payload: dict,
    status: str,
    *,
    detailed: bool = True,
) -> None:
    test.assertEqual(1, payload.get("schema_version"))
    test.assertEqual(status, payload.get("status"))
    test.assertIsInstance(payload.get("score"), int)
    test.assertIsInstance(payload.get("passed"), bool)
    test.assertIsInstance(payload.get("diagnostics"), list)
    if detailed:
        test.assertIn("coverage", payload)
        test.assertIn("evaluation", payload)


def assert_error_result(test: unittest.TestCase, payload: dict) -> None:
    test.assertEqual(1, payload.get("schema_version"))
    test.assertEqual("ERROR", payload.get("status"))
    test.assertNotIn("score", payload)
    test.assertNotIn("passed", payload)


class SemanticCheckCliTests(unittest.TestCase):
    def invoke(self, *args: object, stdin: str | None = None):
        with tempfile.TemporaryDirectory() as directory:
            return run_cli(*args, cwd=Path(directory), stdin=stdin)

    def test_reference_passes_with_stable_json_schema_from_an_unrelated_cwd(self):
        process = self.invoke(str(REFERENCE), "--suite", str(SUITE), "--json")

        self.assertEqual(0, process.returncode, process.stderr)
        payload = json_stdout(process)
        assert_normal_result(self, payload, "PASS")
        self.assertTrue(payload["passed"])

    def test_reversed_relation_is_a_student_failure_with_json_diagnostics(self):
        process = self.invoke(str(WRONG_RELATION), "--suite", str(SUITE), "--json")

        self.assertEqual(1, process.returncode, process.stderr)
        payload = json_stdout(process)
        assert_normal_result(self, payload, "FAIL")
        self.assertFalse(payload["passed"])
        self.assertTrue(payload["diagnostics"])

    def test_illegal_jml_is_a_format_failure_with_suite_identity(self):
        source = REFERENCE.read_text(encoding="utf-8").replace("containsUser", "unknownQuery")
        process = self.invoke("-", "--suite", str(SUITE), "--json", stdin=source)
        self.assertEqual(1, process.returncode, process.stderr)
        payload = json_stdout(process)
        assert_normal_result(self, payload, "FAIL", detailed=False)
        self.assertEqual(0, payload["score"])
        self.assertEqual("NetworkInterface.followUser", payload["evaluation"]["suite"])
        self.assertEqual("JML_FORMAT_OR_SYMBOL", payload["diagnostics"][0]["code"])

    def test_bom_and_jml_suffix_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            student = cwd / "student.jml"
            student.write_bytes(b"\xef\xbb\xbf" + REFERENCE.read_bytes())

            process = run_cli(str(student), "--suite", str(SUITE), "--json", cwd=cwd)

        self.assertEqual(0, process.returncode, process.stderr)
        assert_normal_result(self, json_stdout(process), "PASS")

    def test_stdin_source_is_read_as_utf8_and_accepts_a_bom(self):
        source = "\ufeff" + REFERENCE.read_text(encoding="utf-8")
        process = self.invoke("-", "--suite", str(SUITE), "--json", stdin=source)

        self.assertEqual(0, process.returncode, process.stderr)
        assert_normal_result(self, json_stdout(process), "PASS")

    def test_invalid_utf8_submission_is_a_format_failure_not_a_server_error(self):
        with tempfile.TemporaryDirectory() as directory:
            student = Path(directory) / "invalid.java"
            student.write_bytes(b"public interface Student {\n\xff\n}")
            process = run_cli(str(student), "--suite", str(SUITE), "--json", cwd=Path(directory))

        self.assertEqual(1, process.returncode, process.stderr)
        payload = json_stdout(process)
        assert_normal_result(self, payload, "FAIL", detailed=False)
        self.assertEqual(
            "JML_FORMAT_OR_SYMBOL",
            payload["diagnostics"][0].get("code"),
        )

    def test_missing_submission_is_an_error_without_a_grade(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "not-submitted.java"
            process = run_cli(str(missing), "--suite", str(SUITE), "--json", cwd=Path(directory))

        self.assertEqual(2, process.returncode)
        payload = json_stdout(process)
        assert_error_result(self, payload)
        self.assertIn(str(missing), process.stderr)

    def test_json_argument_errors_are_machine_readable(self):
        cases = (
            ("--json",),
            ("--json", str(REFERENCE), "--suite", str(SUITE), "--reference", str(REFERENCE)),
            (str(REFERENCE), "--json"),
        )
        for args in cases:
            with self.subTest(args=args):
                process = self.invoke(*args)
                self.assertEqual(2, process.returncode)
                assert_error_result(self, json_stdout(process))

    @unittest.skipIf(importlib.util.find_spec("z3"), "requires a missing optional SMT backend")
    def test_missing_required_smt_backend_is_an_error_without_a_grade(self):
        config = json.loads(SUITE.read_text(encoding="utf-8"))
        config["reference"] = str(REFERENCE)
        config["points"] = str(SUITE.parent / "points.yaml")
        config["solver"] = {"mode": "required", "timeout_ms": 1000}
        with tempfile.TemporaryDirectory() as directory:
            suite = Path(directory) / "suite.yaml"
            suite.write_text(json.dumps(config), encoding="utf-8")
            process = run_cli(REFERENCE, "--suite", suite, "--json", cwd=Path(directory))
        self.assertEqual(2, process.returncode, process.stderr)
        assert_error_result(self, json_stdout(process))
        self.assertIn("SMT", process.stderr)

    def test_invalid_utf8_reference_is_a_sanitized_server_error(self):
        secret_contract = "requires private_reference_contract_canary;"
        private_reference = "private/reference-canary.jml"
        private_points = "private/points-canary.yaml"
        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            private_dir = temp_root / "private"
            private_dir.mkdir()
            reference_path = private_dir / "reference-canary.jml"
            reference_path.write_bytes(secret_contract.encode("utf-8") + b"\xff")
            (private_dir / "points-canary.yaml").write_bytes(
                (SUITE.parent / "points.yaml").read_bytes()
            )
            config = json.loads(SUITE.read_text(encoding="utf-8"))
            config["reference"] = private_reference
            config["points"] = private_points
            custom_suite = temp_root / "suite.yaml"
            custom_suite.write_text(json.dumps(config), encoding="utf-8")

            process = run_cli(
                str(REFERENCE), "--suite", str(custom_suite), "--json", cwd=temp_root
            )

        self.assertEqual(2, process.returncode)
        payload = json_stdout(process)
        assert_error_result(self, payload)
        self.assertNotIn(private_reference, process.stdout)
        self.assertNotIn(private_points, process.stdout)
        self.assertNotIn(secret_contract, process.stdout)
        self.assertIn("invalid start byte", process.stderr.lower())

    def test_invalid_utf8_suite_configuration_is_an_error_without_a_grade(self):
        with tempfile.TemporaryDirectory() as directory:
            suite = Path(directory) / "broken-suite.yaml"
            suite.write_bytes(b'{"schema_version": 1,\xff}')
            process = run_cli(str(REFERENCE), "--suite", str(suite), "--json", cwd=Path(directory))

        self.assertEqual(2, process.returncode)
        assert_error_result(self, json_stdout(process))
        self.assertIn("invalid start byte", process.stderr.lower())


class ReleaseArchiveTests(unittest.TestCase):
    def test_release_zip_is_whitelisted_relocatable_and_suite_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            archive = temp_root / "release.zip"
            build = subprocess.run(
                [sys.executable, str(BUILD_RELEASE), "--output", str(archive)],
                cwd=temp_root,
                env=child_env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(0, build.returncode, build.stderr)
            self.assertTrue(archive.is_file())

            extract_root = temp_root / "extracted"
            extract_root.mkdir()
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
                roots = {name.split("/", 1)[0] for name in names if name}
                self.assertEqual({"spec_judge"}, roots)
                bundle.extractall(extract_root)

            package = extract_root / "spec_judge"
            manifest = json.loads((package / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(1, manifest["result_schema_version"])
            for relative, digest in manifest["files"].items():
                self.assertEqual(digest, hashlib.sha256((package / relative).read_bytes()).hexdigest())
            self.assertTrue((package / "core").is_dir())
            self.assertTrue((package / "profiles").is_dir())
            self.assertTrue((package / "suites").is_dir())
            self.assertTrue((package / "tests").is_dir())
            self.assertTrue((package / "README.md").is_file())
            self.assertTrue((package / "USAGE.md").is_file())
            self.assertTrue((package / "semantic_check.py").is_file())
            self.assertTrue((package / "validate_suite.py").is_file())

            forbidden_names = (
                "Agent/",
                "consistency_judge.py",
                "runtime_verifier.py",
                "verification_evidence.py",
                "__pycache__/",
                ".venv/",
            )
            for name in names:
                for forbidden in forbidden_names:
                    self.assertNotIn(forbidden, name)
                self.assertFalse(name.endswith(".iml"), name)
                self.assertFalse(
                    name.startswith("spec_judge/")
                    and Path(name).name in OLD_TEST_MODULES,
                    name,
                )

            suite_files = sorted(package.glob("suites/*/*/suite.yaml"))
            self.assertTrue(suite_files, "release ZIP must contain declarative suites")
            with tempfile.TemporaryDirectory() as unrelated_cwd:
                cwd = Path(unrelated_cwd)
                for suite in suite_files:
                    with self.subTest(suite=suite.relative_to(package)):
                        config = json.loads(suite.read_text(encoding="utf-8"))
                        reference = (suite.parent / config["reference"]).resolve()
                        cli = subprocess.run(
                            [
                                sys.executable,
                                str(package / "semantic_check.py"),
                                str(reference),
                                "--suite",
                                str(suite),
                                "--json",
                            ],
                            cwd=cwd,
                            env=child_env(),
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            check=False,
                        )
                        self.assertEqual(0, cli.returncode, cli.stderr)
                        result = json_stdout(cli)
                        assert_normal_result(self, result, "PASS")

                        validation = subprocess.run(
                            [sys.executable, str(package / "validate_suite.py"), str(suite)],
                            cwd=cwd,
                            env=child_env(),
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            check=False,
                        )
                        self.assertEqual(0, validation.returncode, validation.stderr)
                        self.assertTrue(json.loads(validation.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
