from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class CaseLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parent.parent
        cls.library = cls.project_root / "case_library"
        cls.manifest = json.loads(
            (cls.library / "manifest.json").read_text(encoding="utf-8")
        )
        cls.semantic_check = (
            cls.project_root.parent
            / "judge-2027"
            / "unit3"
            / "spec_judge"
            / "semantic_check.py"
        )

    def test_every_manifest_case_is_a_complete_upload_pair(self) -> None:
        self.assertEqual(1, self.manifest["schema_version"])
        self.assertTrue(self.manifest["contract_version"])
        case_ids: set[str] = set()
        for item in self.manifest["cases"]:
            with self.subTest(case=item["id"]):
                self.assertNotIn(item["id"], case_ids)
                case_ids.add(item["id"])
                directory = self.library / item["directory"]
                for key in ("nl", "jml", "java"):
                    path = directory / item[key]
                    self.assertTrue(path.is_file(), path)
                    self.assertTrue(path.read_text(encoding="utf-8").strip())
                jml = (directory / item["jml"]).read_text(encoding="utf-8")
                java = (directory / item["java"]).read_text(encoding="utf-8")
                self.assertIn(item["method"] + "(", jml)
                self.assertIn(item["method"] + "(", java)

    def test_manifest_jml_matches_declared_nl_chain_result(self) -> None:
        for item in self.manifest["cases"]:
            with self.subTest(case=item["id"]):
                directory = self.library / item["directory"]
                suite = (self.library / item["suite"]).resolve()
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(self.semantic_check),
                        str(directory / item["jml"]),
                        "--suite",
                        str(suite),
                        "--json",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                    check=False,
                )
                self.assertNotEqual(2, completed.returncode, completed.stderr)
                result = json.loads(completed.stdout)
                expected = item["expected"]["nl_jml"]
                self.assertEqual(expected == "PASS", result["passed"], result)
                if item["id"] in {
                    "follow-user-a-correct",
                    "follow-user-c-wrong-code",
                    "unfollow-user-a-correct",
                    "unfollow-user-c-wrong-code",
                }:
                    self.assertEqual(100, result["score"], result)


if __name__ == "__main__":
    unittest.main()
