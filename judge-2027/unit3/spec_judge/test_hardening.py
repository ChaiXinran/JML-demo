"""Focused CLI regressions for parser binding, grammar and resource limits."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import semantic_check


ROOT = Path(__file__).resolve().parent
CLI = ROOT / "semantic_check.py"
FOLLOW_SUITE = ROOT / "suites" / "NetworkInterface" / "followUser" / "suite.yaml"
FOLLOW_REFERENCE = FOLLOW_SUITE.parent / "reference.java"
COUNTER_SUITE = ROOT / "suites" / "CounterInterface" / "checkNonNegative" / "suite.yaml"
COUNTER_REFERENCE = COUNTER_SUITE.parent / "reference.java"
MAX_SUBMISSION_BYTES = 1024 * 1024


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONPATH", None)
    return env


def invoke_stdin(
    source: str,
    suite: Path = FOLLOW_SUITE,
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    if cwd is None:
        with tempfile.TemporaryDirectory() as directory:
            return invoke_stdin(source, suite, cwd=Path(directory))
    return subprocess.run(
        [sys.executable, str(CLI), "-", "--suite", str(suite), "--json"],
        cwd=cwd,
        env=child_env(),
        input=source,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def invoke_file(
    source: Path,
    suite: Path,
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), str(source), "--suite", str(suite), "--json"],
        cwd=cwd,
        env=child_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def payload_of(test: unittest.TestCase, process: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as error:
        test.fail(f"expected one JSON response, got stdout={process.stdout!r}, stderr={process.stderr!r}: {error}")


def assert_student_format_failure(
    test: unittest.TestCase,
    process: subprocess.CompletedProcess[str],
) -> dict:
    test.assertEqual(1, process.returncode, process.stderr)
    payload = payload_of(test, process)
    test.assertEqual("FAIL", payload.get("status"))
    test.assertIs(payload.get("passed"), False)
    test.assertTrue(payload.get("diagnostics"))
    test.assertEqual("JML_FORMAT_OR_SYMBOL", payload["diagnostics"][0].get("code"))
    return payload


def assert_server_configuration_error(
    test: unittest.TestCase,
    process: subprocess.CompletedProcess[str],
) -> dict:
    test.assertEqual(2, process.returncode, process.stderr)
    payload = payload_of(test, process)
    test.assertEqual("ERROR", payload.get("status"))
    test.assertNotIn("score", payload)
    test.assertNotIn("passed", payload)
    return payload


class ContractBindingHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.follow_reference = FOLLOW_REFERENCE.read_text(encoding="utf-8")
        cls.counter_reference = COUNTER_REFERENCE.read_text(encoding="utf-8")

    def test_detached_or_ambiguous_method_declarations_fail(self):
        source = self.follow_reference
        block = re.search(r"/\*@.*?@\*/", source, re.DOTALL)
        self.assertIsNotNone(block)
        detached = source[:block.start()] + source[block.end():]
        insert_at = detached.index("{") + 1
        detached = (
            detached[:insert_at]
            + "\n    " + block.group()
            + "\n    public void unrelated();\n"
            + detached[insert_at:]
        )

        duplicate = source.rsplit("}", 1)[0] + "    public void followUser(int id1, int id2);\n}\n"
        overloaded = source.rsplit("}", 1)[0] + "    public void followUser(long id1, int id2);\n}\n"
        cases = {
            "contract_attached_to_unrelated_method": detached,
            "duplicate_target": duplicate,
            "overloaded_target": overloaded,
        }
        for label, candidate in cases.items():
            with self.subTest(case=label):
                assert_student_format_failure(self, invoke_stdin(candidate))

    def test_signature_changes_fail(self):
        source = self.follow_reference
        throws = "throws UserIdNotFoundException, SelfSubscriptionException,\n               DuplicateSubscriptionException;"
        cases = {
            "return_type": source.replace("void followUser(", "boolean followUser(", 1),
            "parameter_type": source.replace("int id1, int id2", "long id1, int id2", 1),
            "parameter_name": source.replace("int id1, int id2", "int owner, int id2", 1),
            "parameter_order": source.replace("int id1, int id2", "int id2, int id1", 1),
            "static_modifier": source.replace("public /*@ safe @*/", "public static /*@ safe @*/", 1),
            "throws_removed": source.replace(throws, ";", 1),
            "throws_changed": source.replace("DuplicateSubscriptionException;", "IllegalArgumentException;", 1),
        }
        for label, candidate in cases.items():
            with self.subTest(signature=label):
                assert_student_format_failure(self, invoke_stdin(candidate))

    def test_fake_mentions_are_not_method_declarations(self):
        prefix = '''
    String fakeSignature = "public void followUser(int id1, int id2);";
    // public void followUser(int id1, int id2);
    /* ordinary comment: public void followUser(int id1, int id2); */
    default void helper() { followUser(1, 2); }
'''
        candidate = self.follow_reference.replace(
            "public interface NetworkInterface {",
            "public interface NetworkInterface {" + prefix,
            1,
        )
        process = invoke_stdin(candidate)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual("PASS", payload_of(self, process).get("status"))

    def test_supported_method_declaration_markers_pass(self):
        with self.subTest(marker="safe"):
            process = invoke_stdin(self.follow_reference)
            self.assertEqual(0, process.returncode, process.stderr)
            self.assertEqual("PASS", payload_of(self, process).get("status"))
        with self.subTest(marker="pure"):
            process = invoke_stdin(self.counter_reference, COUNTER_SUITE)
            self.assertEqual(0, process.returncode, process.stderr)
            self.assertEqual("PASS", payload_of(self, process).get("status"))

    def test_unsupported_or_malformed_contract_text_fails(self):
        source = self.follow_reference
        close = "      @*/"
        cases = {
            "signals_only": source.replace(
                "      @ assignable users[*];",
                "      @ signals_only DuplicateSubscriptionException;\n      @ assignable users[*];",
                1,
            ),
            "invariant": source.replace(
                "      @ assignable users[*];",
                "      @ invariant true;\n      @ assignable users[*];",
                1,
            ),
            "misspelled_clause": source.replace(
                "      @ assignable users[*];",
                "      @ requres true;\n      @ assignable users[*];",
                1,
            ),
            "trailing_text": source.replace(close, "      @ unexpected_tail\n" + close, 1),
            "empty_also_behavior": source.replace(
                close,
                "      @ also\n      @ public normal_behavior\n" + close,
                1,
            ),
            "adjacent_second_contract": source.replace(
                "    /*@ public normal_behavior",
                "    /*@ requires true; @*/\n    /*@ public normal_behavior",
                1,
            ),
            "line_contract_clause": source.replace(
                "    public /*@ safe @*/",
                "    //@ signals_only DuplicateSubscriptionException;\n    public /*@ safe @*/",
                1,
            ),
            "fake_jml_inside_line_comment": re.sub(
                r"/\*@.*?@\*/", lambda match: "// " + match.group().replace("\n", " "),
                source, count=1, flags=re.DOTALL,
            ),
        }
        for label, candidate in cases.items():
            with self.subTest(contract_input=label):
                assert_student_format_failure(self, invoke_stdin(candidate))

    def test_strengthened_requires_is_detected_in_normal_condition_region(self):
        for guard in ("id1 == 1", "id2 == 2", "id1 != 0"):
            with self.subTest(added_guard=guard):
                candidate = self.follow_reference.replace("@ requires", f"@ requires {guard} &&", 1)
                process = invoke_stdin(candidate)
                self.assertEqual(1, process.returncode, process.stderr)
                payload = payload_of(self, process)
                self.assertEqual("FAIL", payload.get("status"))
                self.assertIs(payload.get("passed"), False)
                self.assertIn(
                    "NORMAL_CONDITION_MISMATCH",
                    {diagnostic.get("code") for diagnostic in payload.get("diagnostics", [])},
                )


class ResourceBudgetHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = FOLLOW_REFERENCE.read_text(encoding="utf-8")

    def test_expression_budgets_and_flat_boolean_chain(self):
        needle = "requires containsUser(id1) && containsUser(id2)"
        too_many_tokens = self.reference.replace(needle, "requires true" + " && true" * 2100, 1)
        too_deep_parentheses = self.reference.replace(
            needle, "requires " + "(" * 40 + "true" + ")" * 40, 1
        )
        too_deep_unary = self.reference.replace(needle, "requires " + "!" * 2000 + "true", 1)
        too_deep_ast = self.reference.replace(
            needle, "requires " + " == ".join(["true"] * 140), 1
        )
        cases = {
            "token_budget": too_many_tokens,
            "parenthesis_nesting": too_deep_parentheses,
            "unary_nesting": too_deep_unary,
            "ast_depth": too_deep_ast,
            "integer_literal_digits": self.reference.replace(
                needle, "requires " + "9" * 4097 + " == 0", 1,
            ),
        }
        for label, candidate in cases.items():
            with self.subTest(expression_budget=label):
                assert_student_format_failure(self, invoke_stdin(candidate))

        long_flat = self.reference.replace(
            needle,
            needle + " && " + " && ".join(["true"] * 1000),
            1,
        )
        process = invoke_stdin(long_flat)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual("PASS", payload_of(self, process).get("status"))

    def test_submission_byte_limit_covers_stdin_and_files(self):
        oversized = self.reference + (" " * (MAX_SUBMISSION_BYTES + 1))
        with self.subTest(source="stdin"):
            assert_student_format_failure(self, invoke_stdin(oversized))

        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            student = cwd / "oversized.java"
            student.write_bytes(self.reference.encode("utf-8") + b" " * (MAX_SUBMISSION_BYTES + 1))
            with self.subTest(source="file"):
                assert_student_format_failure(self, invoke_file(student, FOLLOW_SUITE, cwd=cwd))

    def test_internal_resource_error_never_becomes_a_student_grade(self):
        arguments = [str(CLI), str(FOLLOW_REFERENCE), "--suite", str(FOLLOW_SUITE), "--json"]
        for target, exception in (
            ("read_submission", MemoryError),
            ("evaluate_sources", MemoryError),
            ("evaluate_sources", RecursionError),
        ):
            with self.subTest(stage=target, error=exception.__name__):
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.object(sys, "argv", arguments), patch.object(
                    semantic_check, target, side_effect=exception,
                ), redirect_stdout(stdout), redirect_stderr(stderr):
                    code = semantic_check.main()
                self.assertEqual(2, code)
                payload = json.loads(stdout.getvalue())
                self.assertEqual("ERROR", payload["status"])
                self.assertEqual("JUDGE_RESOURCE_ERROR", payload["diagnostics"][0]["code"])
                self.assertNotIn("score", payload)
                self.assertNotIn("passed", payload)

    def test_deep_reference_is_a_server_error_without_student_grade(self):
        needle = "requires containsUser(id1) && containsUser(id2)"
        deep_reference = self.reference.replace(
            needle, "requires " + "(" * 40 + "true" + ")" * 40, 1
        )
        config = json.loads(FOLLOW_SUITE.read_text(encoding="utf-8"))
        points = (FOLLOW_SUITE.parent / config["points"]).resolve()

        for label, reference in (
            ("nested", deep_reference),
            ("oversized", self.reference + " " * (MAX_SUBMISSION_BYTES + 1)),
        ):
            with self.subTest(reference=label), tempfile.TemporaryDirectory() as directory:
                cwd = Path(directory)
                reference_path = cwd / "reference.java"
                reference_path.write_text(reference, encoding="utf-8")
                config["reference"] = str(reference_path)
                config["points"] = str(points)
                suite = cwd / "suite.yaml"
                suite.write_text(json.dumps(config), encoding="utf-8")
                process = invoke_stdin(self.reference, suite, cwd=cwd)
                assert_server_configuration_error(self, process)


if __name__ == "__main__":
    unittest.main()
