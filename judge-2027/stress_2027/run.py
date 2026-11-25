"""Run independently labeled mock submissions through the production CLI."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
import json
import math
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

from case import Case
import common


ROOT = Path(__file__).resolve().parent
DEFAULT_JUDGE = ROOT.parent / "unit3" / "spec_judge"
EXERCISES = {
    "hw9": "firstDuplicateIndex",
    "hw10": "reserveSeats",
    "hw11": "longestFreeBlock",
}
EXPECTED_EXITS = {"PASS": 0, "FAIL": 1}


@dataclass(frozen=True)
class Submission:
    week: str
    suite: Path
    case: Case
    path: Path


def collect(judge: Path, weeks: list[str], output: Path) -> list[Submission]:
    submissions = []
    for week in weeks:
        method = EXERCISES[week]
        directory = judge / "suites" / "JML" / method
        reference = (directory / "reference.java").read_text(encoding="utf-8")
        cases = [*import_module(week).cases(reference), *common.cases(reference, method)]
        if not any(case.source == reference and case.expectation == "PASS" for case in cases):
            cases.insert(0, Case("official-reference", "PASS", "equivalent", "标准参考规格自评", reference))
        ids = set()
        sources = set()
        for case in cases:
            if not re.fullmatch(r"[a-z0-9_-]+", case.id) or case.id in ids:
                raise ValueError(f"{week} 的样例 ID 重复或无效：{case.id}")
            if case.expectation not in EXPECTED_EXITS or not case.source.strip() or case.source in sources:
                raise ValueError(f"{week}/{case.id} 的源码为空、重复或预期状态无效")
            ids.add(case.id)
            sources.add(case.source)
            path = output / "submissions" / week / case.id / "JML" / "JML.java"
            submissions.append(Submission(week, directory / "suite.yaml", case, path))
    return submissions


def check_payload(exit_code: int, payload, stderr: bytes, case: Case) -> tuple[str, str]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return "protocol_error", "stdout 须为一个 schema_version=1 的 JSON 对象"
    actual = payload.get("status")
    if actual == "ERROR" and exit_code == 2:
        return "judge_error", "评测器报告 ERROR"
    if not isinstance(actual, str) or EXPECTED_EXITS.get(actual) != exit_code or stderr:
        return "protocol_error", "退出码、状态或 stderr 不符合学生评测协议"
    score, passed, diagnostics = (payload.get(key) for key in ("score", "passed", "diagnostics"))
    if (type(score) is not int or not 0 <= score <= 100 or passed is not (actual == "PASS")
            or not isinstance(diagnostics, list) or any(
                not isinstance(item, dict) or not isinstance(item.get("code"), str)
                for item in diagnostics
            )):
        return "protocol_error", "score、passed 或 diagnostics 格式无效"
    if actual == "PASS" and (score != 100 or diagnostics):
        return "protocol_error", "PASS 必须给 100 分且没有失败诊断"
    if actual == "FAIL" and (score == 100 or not diagnostics):
        return "protocol_error", "FAIL 必须给低于 100 的成绩及诊断"
    if actual != case.expectation:
        outcome = "false_accept" if actual == "PASS" else (
            "unsupported" if case.category == "unsupported" else "false_reject"
        )
        return outcome, f"预期 {case.expectation}，实际 {actual}"
    if case.diagnostic and case.diagnostic not in {item["code"] for item in diagnostics}:
        return "diagnostic_mismatch", f"缺少预期诊断 {case.diagnostic}"
    return "match", ""


def run_case(judge: Path, submission: Submission, timeout: float, output: Path, trial: int) -> dict:
    case = submission.case
    argv = [
        sys.executable, "-B", str(judge / "semantic_check.py"), str(submission.path),
        "--suite", str(submission.suite), "--json",
    ]
    start = time.perf_counter()
    payload, exit_code = None, None
    try:
        result = subprocess.run(argv, cwd=output, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
        outcome, issue = "timeout", f"超过 {timeout:g} 秒"
    except OSError as exc:
        stdout, stderr = b"", str(exc).encode("utf-8")
        outcome, issue = "launch_error", "无法启动评测子进程"
    else:
        stdout, stderr, exit_code = result.stdout, result.stderr, result.returncode
        try:
            payload = json.loads(stdout)
        except (ValueError, UnicodeError):
            pass
        outcome, issue = check_payload(exit_code, payload, stderr, case)
    seconds = time.perf_counter() - start
    raw_dir = output / "feedback" / f"round-{trial:02d}" / submission.week / case.id
    raw_dir.mkdir(parents=True)
    (raw_dir / "stdout.json").write_bytes(stdout)
    (raw_dir / "stderr.txt").write_bytes(stderr)
    return {
        "id": case.id, "category": case.category, "reason": case.reason,
        "expectation": case.expectation, "expected_diagnostic": case.diagnostic,
        "week": submission.week, "method": submission.suite.parent.name, "round": trial,
        "file": submission.path.relative_to(output).as_posix(),
        "feedback": raw_dir.relative_to(output).as_posix(),
        "exit_code": exit_code, "seconds": round(seconds, 6), "outcome": outcome,
        "issue": issue, "result": payload,
    }


def breakdown(rows: list[dict]) -> dict:
    times = sorted(row["seconds"] for row in rows)
    return {
        "tested": len(rows),
        "expected": dict(Counter(row["expectation"] for row in rows)),
        "outcomes": dict(Counter(row["outcome"] for row in rows)),
        "p50_seconds": times[math.ceil(len(times) * .50) - 1],
        "p95_seconds": times[math.ceil(len(times) * .95) - 1],
        "max_seconds": times[-1],
    }


def summary_markdown(report: dict) -> str:
    lines = [
        "# 独立 JML 题压力测试结果", "",
        f"{report['count']} 份不同提交，共 {report['total']['tested']} 次调用，"
        f"并发 {report['jobs']}，总耗时 {report['wall_seconds']:.2f} 秒。", "",
        f"环境：{report['system']}，Python {report['python']}，单次超时 {report['timeout_seconds']:g} 秒。", "",
        "| 周次 | 调用数 | 预期 PASS / FAIL | 匹配 | 错放 | 错杀 | 超出支持子集 | 其他异常 | P95 / 最慢（秒） |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for week, counts in report["weeks"].items():
        outcomes = counts["outcomes"]
        matched, accepts, rejects, unsupported = (
            outcomes.get(key, 0) for key in ("match", "false_accept", "false_reject", "unsupported")
        )
        other = counts["tested"] - matched - accepts - rejects - unsupported
        lines.append(
            f"| {week.upper()} | {counts['tested']} | {counts['expected'].get('PASS', 0)} / "
            f"{counts['expected'].get('FAIL', 0)} | {matched} | {accepts} | {rejects} | "
            f"{unsupported} | {other} | {counts['p95_seconds']:.3f} / {counts['max_seconds']:.3f} |"
        )
    lines += ["", "## 与预期不符的案例", ""]
    mismatches = [row for row in report["cases"] if row["outcome"] != "match"]
    if not mismatches:
        lines.append("所有状态及要求核对的诊断均符合预期。")
    for row in mismatches:
        lines.append(
            f"- {row['week'].upper()} [{row['id']}]({row['file']}) 第 {row['round']} 轮，"
            f"{row['outcome']}。{row['issue']}。{row['reason'].rstrip('。')}。"
            f"[stdout]({row['feedback']}/stdout.json)"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge-dir", type=Path, default=DEFAULT_JUDGE)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--week", choices=EXERCISES, action="append", help="可重复传入，默认三周全部")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if args.jobs <= 0 or args.repeat <= 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("jobs、repeat、timeout 必须为正且有限")
    judge = args.judge_dir.resolve()
    output = (args.output_dir or ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")).resolve()
    weeks = list(dict.fromkeys(args.week or EXERCISES))
    try:
        if not (judge / "semantic_check.py").is_file():
            raise ValueError(f"评测入口不存在：{judge}")
        submissions = collect(judge, weeks, output)
        output.mkdir(parents=True)
        for submission in submissions:
            submission.path.parent.mkdir(parents=True)
            submission.path.write_bytes(submission.case.source.encode("utf-8"))
        start = time.perf_counter()
        rows = []
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for trial in range(1, args.repeat + 1):
                rows.extend(pool.map(
                    lambda submission: run_case(judge, submission, args.timeout, output, trial),
                    submissions,
                ))
                print(f"完成第 {trial}/{args.repeat} 轮，{len(rows)} 次 CLI 调用", flush=True)
        report = {
            "schema_version": 1, "judge": str(judge), "jobs": args.jobs, "repeat": args.repeat,
            "system": f"{platform.system()} {platform.machine()}", "python": platform.python_version(),
            "timeout_seconds": args.timeout, "count": len(submissions),
            "wall_seconds": round(time.perf_counter() - start, 6),
            "total": breakdown(rows),
            "weeks": {week: breakdown([row for row in rows if row["week"] == week]) for week in weeks},
            "cases": rows,
        }
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "report.md").write_text(summary_markdown(report), encoding="utf-8")
    except (OSError, ValueError, AssertionError) as exc:
        print(f"无法完成测试：{exc}", file=sys.stderr)
        return 2
    print(f"判定分布：{report['total']['outcomes']}。报告：{output / 'report.md'}")
    return 0 if all(row["outcome"] == "match" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
