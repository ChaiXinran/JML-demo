"""End-to-end regression coverage for the 2027 independent JML exercises."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from core.profile import ProfileError
from core.suite import load_suite
from profiles.registry import PROFILES
from semantic_judge import evaluate_sources


JUDGE_ROOT = Path(__file__).resolve().parent
SUITE_ROOT = JUDGE_ROOT / "suites" / "JML"
EXERCISES = ("firstDuplicateIndex", "reserveSeats", "longestFreeBlock")


def _suite(name: str):
    return load_suite(SUITE_ROOT / name / "suite.yaml", PROFILES)


def _replace_contract(source: str, body: str) -> str:
    return re.sub(r"/\*@.*?@\*/", lambda match: body, source, count=1, flags=re.DOTALL)


def _replace_contract_with_line_comments(source: str, lines: list[str]) -> str:
    block = re.search(r"/\*@.*?@\*/", source, flags=re.DOTALL)
    if block is None:
        raise AssertionError("reference has no block JML contract")
    return source[:block.start()] + "\n".join(lines) + source[block.end():]


def _assert_pass(test: unittest.TestCase, result) -> None:
    test.assertTrue(result.passed, result.to_dict())
    test.assertEqual(100, result.score, result.to_dict())


def _assert_student_fail(test: unittest.TestCase, result) -> None:
    test.assertFalse(result.passed, result.to_dict())
    test.assertEqual("FAIL", result.to_dict()["status"])


class JML2027ExerciseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suites = {name: _suite(name) for name in EXERCISES}
        cls.references = {
            name: suite.reference.read_text(encoding="utf-8")
            for name, suite in cls.suites.items()
        }

    def evaluate(self, name: str, candidate: str):
        suite = self.suites[name]
        return evaluate_sources(
            self.references[name], candidate, suite.method, suite.profile
        )

    def test_all_three_official_reference_contracts_score_full_marks(self):
        for name in EXERCISES:
            with self.subTest(exercise=name):
                _assert_pass(self, self.evaluate(name, self.references[name]))

    def test_hw9_accepts_consecutive_line_comments_and_equivalent_result_split(self):
        # Replace A <==> B by the equivalent pair (A ==> B) && (B ==> A).
        body = [
            "//@ requires ids != null;",
            "//@ assignable \\nothing;",
            "//@ ensures (\\result == -1) ==> (\\forall int i, j; 0 <= i && i < j && j < ids.length; ids[i] != ids[j]);",
            "//@ ensures (\\forall int i, j; 0 <= i && i < j && j < ids.length; ids[i] != ids[j]) ==> (\\result == -1);",
            "//@ ensures \\result != -1 ==> 0 <= \\result && \\result < ids.length",
            "//@     && (\\exists int i; 0 <= i && i < \\result; ids[i] == ids[\\result])",
            "//@     && (\\forall int i, j; 0 <= i && i < j && j < \\result; ids[i] != ids[j]);",
        ]
        candidate = _replace_contract_with_line_comments(
            self.references["firstDuplicateIndex"], body
        )
        _assert_pass(self, self.evaluate("firstDuplicateIndex", candidate))

    def test_hw9_accepts_i_plus_one_quantifier_boundary(self):
        candidate = self.references["firstDuplicateIndex"].replace(
            "i < j && j < ids.length",
            "i + 1 <= j && j < ids.length",
            1,
        )
        self.assertNotEqual(self.references["firstDuplicateIndex"], candidate)
        _assert_pass(self, self.evaluate("firstDuplicateIndex", candidate))

    def test_hw9_accepts_bounded_additive_solution_count(self):
        # There are exactly two (i, j) pairs in the stated finite range for
        # i + i - j == -1: (0, 1) and (1, 3).
        candidate = self.references["firstDuplicateIndex"].replace(
            r"assignable \nothing;",
            r"assignable \nothing;" + "\n"
            + r"      @ ensures (\num_of int i, j; "
              r"0 <= i && i <= 1 && 0 <= j && i + i - j == -1; true) == 2;",
            1,
        )
        _assert_pass(self, self.evaluate("firstDuplicateIndex", candidate))

    def test_hw10_accepts_whitespace_equivalent_array_frame(self):
        candidate = self.references["reserveSeats"].replace(
            "assignable occupied[start .. start + count - 1];",
            "assignable occupied [ start .. start + count - 1 ];",
            1,
        )
        self.assertNotEqual(self.references["reserveSeats"], candidate)
        _assert_pass(self, self.evaluate("reserveSeats", candidate))

    def test_hw11_accepts_reordered_ensures_clauses(self):
        source = self.references["longestFreeBlock"]
        block = re.search(r"/\*@(?P<body>.*?)@\*/", source, flags=re.DOTALL)
        self.assertIsNotNone(block)
        body = block.group("body")
        starts = list(re.finditer(r"(?m)^\s*@\s*ensures\b", body))
        self.assertEqual(3, len(starts), "one ensures in behavior 1 and two in behavior 2")
        spans = []
        for start_match in starts:
            depth = 0
            end = None
            for index in range(start_match.end(), len(body)):
                if body[index] == "(":
                    depth += 1
                elif body[index] == ")":
                    depth -= 1
                elif body[index] == ";" and depth == 0:
                    end = index + 1
                    break
            self.assertIsNotNone(end, "each ensures clause must terminate")
            spans.append((start_match.start(), end))
        selected = spans[1:]
        reordered = "\n".join(
            body[start:end].strip() for start, end in reversed(selected)
        )
        candidate_body = body[:selected[0][0]] + reordered + body[selected[-1][1]:]
        candidate = _replace_contract(
            source, "/*@" + candidate_body + "@*/"
        )
        candidate = candidate.replace(
            r"(\forall int i; 0 <= i && i < occupied.length; occupied[i]);",
            r"(\num_of int i; 0 <= i && i < occupied.length; !occupied[i]) == 0;",
            1,
        )
        self.assertNotEqual(source, candidate)
        _assert_pass(self, self.evaluate("longestFreeBlock", candidate))

    def test_hw11_accepts_additive_quantifier_boundary(self):
        candidate = self.references["longestFreeBlock"].replace(
            "length <= occupied.length - start",
            "start + length <= occupied.length",
            1,
        )
        self.assertNotEqual(self.references["longestFreeBlock"], candidate)
        _assert_pass(self, self.evaluate("longestFreeBlock", candidate))

    def test_stress_witnesses_reject_previous_false_accepts(self):
        cases = (
            ("firstDuplicateIndex", r"\result != -1 ==>", r"\result > -1 ==>"),
            ("reserveSeats", r"\result && occupied == \old(occupied);",
             r"\result && occupied == \old(occupied) && count <= 2;"),
            ("longestFreeBlock", r"\result.length == 2", r"\result.length >= 2"),
        )
        for name, old, new in cases:
            with self.subTest(exercise=name):
                reference = self.references[name]
                candidate = reference.replace(old, new)
                self.assertNotEqual(reference, candidate)
                result = self.evaluate(name, candidate)
                _assert_student_fail(self, result)
                self.assertIn("POSTCONDITION_MISMATCH", {item.code for item in result.diagnostics})

    def test_typical_wrong_contract_behavior_is_rejected_for_each_exercise(self):
        hw9 = self.references["firstDuplicateIndex"].replace(
            "ids[i] != ids[j]", "ids[i] == ids[j]", 1
        )
        hw10 = self.references["reserveSeats"].replace(
            "ensures !\\result;", "ensures \\result;", 1
        )
        hw11 = self.references["longestFreeBlock"].replace(
            "\\result[0] <= start", "\\result[0] >= start", 1
        )
        for name, candidate in (
            ("firstDuplicateIndex", hw9),
            ("reserveSeats", hw10),
            ("longestFreeBlock", hw11),
        ):
            with self.subTest(exercise=name):
                _assert_student_fail(self, self.evaluate(name, candidate))

    def test_hw10_wrong_exception_type_is_rejected(self):
        candidate = self.references["reserveSeats"].replace(
            "signals_only IllegalArgumentException;",
            "signals_only NullPointerException;",
            1,
        )
        result = self.evaluate("reserveSeats", candidate)
        _assert_student_fail(self, result)
        self.assertIn("EXCEPTION_PARTITION_MISMATCH", {item.code for item in result.diagnostics})

    def test_undefined_array_and_invalid_quantifier_are_student_failures(self):
        reference = self.references["firstDuplicateIndex"]
        bad_array = reference.replace("ids[i]", "unknown[i]", 1)
        bad_quantifier = reference.replace(
            r"\forall int i, j;", r"\forall boolean i, j;", 1
        )
        unbounded = reference.replace("0 <= i && i < j && j < ids.length", "i < j", 1)
        out_of_bounds = reference.replace("ids[i] != ids[j]", "ids[2147483647] != ids[j]", 1)
        for candidate in (bad_array, bad_quantifier, unbounded, out_of_bounds):
            with self.subTest(candidate=candidate):
                result = self.evaluate("firstDuplicateIndex", candidate)
                self.assertFalse(result.passed, result.to_dict())
                self.assertEqual(0, result.score)
                self.assertEqual("FAIL", result.to_dict()["status"])
                self.assertEqual("JML_FORMAT_OR_SYMBOL", result.diagnostics[0].code)

    def test_result_is_rejected_outside_ensures(self):
        hw9 = self.references["firstDuplicateIndex"].replace(
            "requires ids != null;", r"requires \result >= 0;", 1
        )
        hw10 = self.references["reserveSeats"].replace(
            "signals_only IllegalArgumentException;",
            "signals_only IllegalArgumentException;\n"
            r"      @ signals (IllegalArgumentException e) \result;",
            1,
        )
        for name, candidate in (
            ("firstDuplicateIndex", hw9),
            ("reserveSeats", hw10),
        ):
            with self.subTest(exercise=name):
                result = self.evaluate(name, candidate)
                self.assertFalse(result.passed, result.to_dict())
                self.assertEqual(0, result.score)
                self.assertEqual("JML_FORMAT_OR_SYMBOL", result.diagnostics[0].code)

    def test_invalid_reference_is_a_configuration_error(self):
        suite = self.suites["firstDuplicateIndex"]
        bad_reference = self.references["firstDuplicateIndex"].replace(
            "requires ids != null;", "requires ids == null;", 1
        )
        with self.assertRaisesRegex(ProfileError, "自检判定不一致"):
            evaluate_sources(
                bad_reference, self.references["firstDuplicateIndex"],
                suite.method, suite.profile,
            )

    def test_mislabeled_reference_observation_is_a_configuration_error(self):
        original = self.suites["firstDuplicateIndex"]
        points_path = original.reference.parent / "points.yaml"
        document = json.loads(points_path.read_text(encoding="utf-8"))
        point = next(
            item for item in document["points"]
            if item["kind"] == "post" and item["reference_accepts"] is True
        )
        point["reference_accepts"] = False

        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            shutil.copyfile(original.reference, temp_root / "reference.java")
            (temp_root / "suite.yaml").write_text(
                json.dumps({
                    "schema_version": 1,
                    "name": original.name,
                    "profile": "array_v1",
                    "method": original.method,
                    "parameters": dict(original.parameters),
                    "result_type": "int",
                    "contract_shape": {
                        "requires": {"min": 0},
                        "ensures": {"min": 0},
                        "signals": {"min": 0},
                    },
                    "grading": dict(original.grading),
                    "solver": {"mode": "off", "timeout_ms": 1000},
                    "reference": "reference.java",
                    "points": "points.yaml",
                }),
                encoding="utf-8",
            )
            (temp_root / "points.yaml").write_text(
                json.dumps(document), encoding="utf-8"
            )
            mislabeled = load_suite(temp_root / "suite.yaml", PROFILES)

        with self.assertRaisesRegex(ProfileError, "自检判定不一致"):
            evaluate_sources(
                self.references["firstDuplicateIndex"],
                self.references["firstDuplicateIndex"],
                mislabeled.method,
                mislabeled.profile,
            )


if __name__ == "__main__":
    unittest.main()
