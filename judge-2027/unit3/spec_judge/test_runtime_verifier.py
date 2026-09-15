import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core.suite import load_suite
from profiles.registry import PROFILES
from runtime_verifier import (
    RuntimeExecutor,
    UnfollowUserCandidateGenerator,
    UnfollowUserExecutionAdapter,
    ViolationChecker,
    _state_from_dict,
)
from semantic_judge import parse_contract


class RuntimeVerifierTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[3]
        self.suite_path = (
            self.root / "judge-2027" / "unit3" / "spec_judge"
            / "suites" / "NetworkInterface" / "unfollowUser" / "suite.yaml"
        )
        self.fixture = (
            self.root / "judge-2027" / "unit3" / "spec_judge"
            / "examples" / "UnfollowUserRuntimeDemo.java"
        )
        self.suite = load_suite(self.suite_path, PROFILES)
        self.contract = parse_contract(
            self.suite.reference.read_text(encoding="utf-8"),
            self.suite.method,
            self.suite.profile,
        )

    def test_generator_is_deterministic_and_only_uses_applicable_states(self):
        first_generator = UnfollowUserCandidateGenerator()
        second_generator = UnfollowUserCandidateGenerator()
        first = first_generator.generate(self.contract, self.suite.profile)
        second = second_generator.generate(self.contract, self.suite.profile)
        self.assertEqual(first, second)
        self.assertEqual(3, first_generator.generated_count)
        self.assertEqual(3, first_generator.skipped_count + len(first))
        self.assertEqual(3, len(first))
        self.assertTrue(all(candidate.arguments == {"id1": 0, "id2": 1} for candidate in first))

    def test_adapter_roundtrip_source_contains_explicit_object_materialization(self):
        adapter = UnfollowUserExecutionAdapter()
        candidate = UnfollowUserCandidateGenerator(adapter).generate(
            self.contract, self.suite.profile
        )[0]
        runner = adapter.runner_source("Subject", candidate)
        self.assertIn("subject.users[0] = new Subject.User(0, 4);", runner)
        self.assertIn("subject.unfollowUser(0, 1);", runner)
        self.assertIn("BEFORE|users=", runner)
        self.assertIn("RESULT|users=", runner)

    def test_checker_identifies_missing_inverse_update(self):
        adapter = UnfollowUserExecutionAdapter()
        candidate = UnfollowUserCandidateGenerator(adapter).generate(
            self.contract, self.suite.profile
        )[0]
        post = candidate.pre.copy()
        post.following[0].remove(1)
        violations = ViolationChecker().check(
            self.contract, candidate, post, self.suite.profile
        )
        self.assertEqual(1, len(violations))
        self.assertEqual("POSTCONDITION_VIOLATION", violations[0].code)
        self.assertEqual(1, violations[0].clause_index)

    @patch("runtime_verifier.subprocess.run")
    def test_executor_parses_confirmed_clean_transition(self, run):
        outputs = iter((
            types.SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
            types.SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
            types.SimpleNamespace(
                returncode=0,
                stdout=(
                    b"BEFORE|users=0,1|following=0>1|followers=1>0\n"
                    b"RESULT|users=0,1|following=|followers=|exception=NONE\n"
                ),
                stderr=b"",
            ),
        ))
        run.side_effect = lambda *args, **kwargs: next(outputs)
        adapter = UnfollowUserExecutionAdapter()
        candidate = UnfollowUserCandidateGenerator(adapter).generate(
            self.contract, self.suite.profile
        )[0]
        result = RuntimeExecutor("openjml", timeout=2).execute(
            candidate,
            self.fixture,
            self.suite.reference,
            self.suite.method,
            adapter,
        )
        self.assertEqual("NOT_FOUND_WITHIN_BOUNDS", result.replay_status)
        self.assertFalse(result.rac_failure)
        self.assertEqual([0, 1], result.post_state["users"])
        self.assertEqual([], result.post_state["following"])
        self.assertEqual(3, run.call_count)

    def test_state_dict_roundtrip_keeps_relations(self):
        candidate = UnfollowUserCandidateGenerator().generate(
            self.contract, self.suite.profile
        )[2]
        from runtime_verifier import _state_dict
        self.assertEqual(candidate.pre, _state_from_dict(_state_dict(candidate.pre)))

    def test_wsl_commands_use_bash_for_non_executable_release_wrappers(self):
        compile_command, runner_command, run_command = RuntimeExecutor(
            "wsl:/home/ranye/.local/openjml-21.0.27/openjml"
        )._commands(
            Path(r"D:\tmp\bound.java"),
            Path(r"D:\tmp\runner.java"),
            Path(r"D:\tmp\classes"),
        )
        self.assertEqual(["wsl.exe", "bash"], compile_command[:2])
        self.assertIn("--rac", compile_command)
        self.assertIn("--rac-show-source=source", compile_command)
        self.assertEqual(["wsl.exe", "bash"], runner_command[:2])
        self.assertEqual(
            "/home/ranye/.local/openjml-21.0.27/openjml-java", run_command[2]
        )


if __name__ == "__main__":
    unittest.main()
