"""Submit the shipped student answers to an extracted judge and check feedback."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def contained_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"测试材料不存在或超出目录：{relative}")
    return path


def load_cases(judge: Path) -> tuple[dict, list[tuple[dict, Path, Path]]]:
    manifest = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("不支持的模拟提交清单版本")
    release = contained_file(judge, "release.json")
    actual_hash = hashlib.sha256(release.read_bytes()).hexdigest()
    if actual_hash != manifest["judge"]["release_manifest_sha256"]:
        raise ValueError("评测器版本与本套预期反馈不一致；请使用配套的原始发布 ZIP")
    contained_file(judge, "semantic_check.py")
    contained_file(judge, manifest["suite"])
    ids = set()
    cases = []
    for case in manifest["cases"]:
        case_id = case["id"]
        if not re.fullmatch(r"[0-9]{2}_[a-z_]+", case_id) or case_id in ids:
            raise ValueError(f"测试 ID 无效或重复：{case_id}")
        ids.add(case_id)
        source = contained_file(ROOT, case["file"])
        expected = contained_file(ROOT, case["expected_stdout"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != case["source_sha256"]:
            raise ValueError(f"{case_id} 的输入已修改；固定预期不再适用，请用单次 CLI 观察新答案")
        cases.append((case, source, expected))
    if not cases:
        raise ValueError("模拟提交清单为空")
    return manifest, cases


def comparable(payload: dict) -> dict:
    # The optional SMT audit can change solver details and guarantee_scope,
    # while fixed-point scoring and public diagnostics remain the baseline.
    return {
        key: payload.get(key)
        for key in ("schema_version", "status", "score", "passed", "diagnostics", "coverage")
    }


def check(judge: Path, output: Path, timeout: float) -> dict:
    manifest, cases = load_cases(judge)
    output.mkdir(parents=True, exist_ok=False)
    actual_dir = output / "actual"
    actual_dir.mkdir()
    suite = contained_file(judge, manifest["suite"])
    rows = []
    for case, source, expected_path in cases:
        case_id = case["id"]
        command = [sys.executable, str(judge / "semantic_check.py"), str(source),
                   "--suite", str(suite), "--json"]
        stdout, stderr, returncode, problem = "", "", None, None
        try:
            process = subprocess.run(
                command, cwd=judge, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout, check=False,
            )
            stdout, stderr, returncode = process.stdout, process.stderr, process.returncode
        except subprocess.TimeoutExpired as error:
            problem = f"评测超时（{timeout:g} 秒）"
            stdout = error.stdout or ""
            stderr = error.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
        except OSError as error:
            problem = f"无法启动评测器：{error}"
        (actual_dir / f"{case_id}.stdout.json").write_text(stdout, encoding="utf-8")
        (actual_dir / f"{case_id}.stderr.txt").write_text(stderr, encoding="utf-8")
        (actual_dir / f"{case_id}.exitcode.txt").write_text(
            str(returncode) + "\n", encoding="utf-8",
        )
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        payload = None
        if problem is None:
            try:
                payload = json.loads(stdout)
                if not isinstance(payload, dict):
                    raise ValueError("JSON 顶层不是对象")
            except (json.JSONDecodeError, ValueError) as error:
                problem = f"标准输出不是有效结果：{error}"
        matched = (
            problem is None and returncode == case["expected_exit_code"]
            and comparable(payload) == comparable(expected)
        )
        row = {
            "id": case_id, "label": case["label"], "matched": matched,
            "expected_exit_code": case["expected_exit_code"], "actual_exit_code": returncode,
            "expected_status": expected["status"],
            "actual_status": payload.get("status") if isinstance(payload, dict) else None,
            "expected_score": expected.get("score"),
            "actual_score": payload.get("score") if isinstance(payload, dict) else None,
            "diagnostics": payload.get("diagnostics", []) if isinstance(payload, dict) else [],
            "problem": problem,
            "stdout_file": f"actual/{case_id}.stdout.json",
            "stderr_file": f"actual/{case_id}.stderr.txt",
            "exitcode_file": f"actual/{case_id}.exitcode.txt",
        }
        rows.append(row)
        print(f"{'MATCH' if matched else 'MISMATCH':8} {case_id:30} "
              f"status={row['actual_status']}/{row['expected_status']} "
              f"score={row['actual_score']}/{row['expected_score']} "
              f"exit={returncode}/{row['expected_exit_code']}")
    report = {
        "schema_version": 1,
        "judge": manifest["judge"],
        "suite": manifest["suite"],
        "python": sys.version,
        "judge_directory": str(judge),
        "total": len(rows),
        "matched": sum(row["matched"] for row in rows),
        "all_matched": all(row["matched"] for row in rows),
        "cases": rows,
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="模拟学生提交并核对公开评分反馈")
    parser.add_argument("--judge-dir", type=Path, required=True, help="配套发布包解压后的 spec_judge 目录")
    parser.add_argument("--output-dir", type=Path, required=True, help="新建的实际反馈输出目录，不覆盖旧结果")
    parser.add_argument("--timeout", type=float, default=30, help="每份答案的秒数上限，默认 30")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout 必须是正数")
    judge, output = args.judge_dir.resolve(), args.output_dir.resolve()
    try:
        report = check(judge, output, args.timeout)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"模拟提交配置错误：{error}\n")
    print(f"反馈符合预期：{report['matched']}/{report['total']}；报告：{output / 'report.json'}")
    return 0 if report["all_matched"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
