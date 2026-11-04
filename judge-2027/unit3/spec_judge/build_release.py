"""Build a relocatable, standard-library JML–JML judge release."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from semantic_judge import RESULT_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parent
ENTRY_FILES = (
    "semantic_check.py", "semantic_judge.py", "validate_suite.py",
    "smt_counterexample.py", "requirements-smt.txt", "build_release.py",
    "run_tests.py", "test_semantic_judge.py", "test_cli.py", "test_hardening.py",
    "README.md", "USAGE.md", "INTEGRATION.md", "TODO.md", "ON_MACHINE.md",
)
TREES = {
    "core": {".py"},
    "profiles": {".py"},
    "suites": {".yaml", ".json", ".java", ".jml", ".md"},
    "tests/fixtures": {".java", ".jml"},
}


def release_files() -> list[Path]:
    files = {ROOT / name for name in ENTRY_FILES}
    for directory, suffixes in TREES.items():
        files.update(
            path for path in (ROOT / directory).rglob("*")
            if path.is_file() and path.suffix in suffixes
            and not any(part.startswith(".") or part == "__pycache__"
                        for part in path.relative_to(ROOT).parts)
        )
    for path in files:
        if not path.is_file():
            raise ValueError(f"发布文件不存在：{path.relative_to(ROOT)}")
        if not path.resolve().is_relative_to(ROOT):
            raise ValueError(f"发布文件指向组件外部：{path.relative_to(ROOT)}")
    for suite in (ROOT / "suites").glob("*/*/suite.yaml"):
        config = json.loads(suite.read_text(encoding="utf-8"))
        for field in ("reference", "points"):
            value = Path(config[field])
            target = (suite.parent / value).resolve()
            if value.is_absolute() or target not in files:
                raise ValueError(
                    f"{suite.relative_to(ROOT)} 的 {field} 必须指向发布包内的相对路径"
                )
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def _write_entry(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(f"spec_judge/{name}", date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, content)


def build(output: Path) -> dict:
    files = release_files()
    output = output.resolve()
    if output.exists():
        raise ValueError("输出文件已存在，请选择一个新的发布包路径")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "artifact": "unit3-jml-consistency",
        "release_schema_version": 1,
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "entrypoint": "semantic_check.py",
        "files": {},
    }
    with tempfile.TemporaryDirectory(prefix="jml-release-", dir=output.parent) as directory:
        pending = Path(directory) / "release.zip"
        with zipfile.ZipFile(pending, "w") as archive:
            for path in files:
                content = path.read_bytes()
                name = path.relative_to(ROOT).as_posix()
                manifest["files"][name] = hashlib.sha256(content).hexdigest()
                _write_entry(archive, name, content)
            _write_entry(archive, "release.json", (
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8"))
        pending.replace(output)
    return {
        "output": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "file_count": len(files) + 1,
        "result_schema_version": RESULT_SCHEMA_VERSION,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="构建独立 JML–JML 评测机发布包")
    parser.add_argument("--output", type=Path, required=True, help="新 ZIP 文件的路径")
    args = parser.parse_args()
    try:
        report = build(args.output)
    except (OSError, UnicodeError, ValueError, KeyError) as error:
        parser.exit(2, f"构建失败：{error}\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
