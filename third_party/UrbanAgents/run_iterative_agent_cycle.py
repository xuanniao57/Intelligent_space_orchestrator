"""
Iterative Agent Cycle Runner

用于反复迭代测试 DeGIM / Urban Agent 主链路：
- 按配置执行测试用例
- 记录每轮耗时、退出码、stdout/stderr 摘要
- 自动检测产物缺失
- 生成 JSON + Markdown 报告
- 基于失败模式输出改进建议
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List


DEFAULT_CONFIG = "docs/plans/iterative_test_plan.json"
DEFAULT_OUTPUT_DIR = "results/iterative_cycles"


@dataclass
class TestResult:
    iteration: int
    test_name: str
    command: str
    status: str
    exit_code: int
    duration_seconds: float
    missing_artifacts: List[str]
    stdout_tail: str
    stderr_tail: str
    error_type: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run iterative DeGIM/UrbanAgent test cycles")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Path to test plan JSON")
    parser.add_argument("--iterations", type=int, default=3, help="Number of iterative cycles")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory to save reports")
    parser.add_argument("--cooldown", type=float, default=2.0, help="Seconds between tests")
    parser.add_argument("--stop-on-fail", action="store_true", help="Stop the whole cycle immediately on first failure")
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands only")
    return parser.parse_args()


def load_plan(config_path: Path) -> Dict:
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def tail_text(text: str, max_lines: int = 40) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])


def classify_error(exit_code: int, stdout: str, stderr: str, missing_artifacts: List[str]) -> str:
    combined = f"{stdout}\n{stderr}".lower()

    if exit_code == 0 and not missing_artifacts:
        return "NONE"
    if missing_artifacts:
        return "ARTIFACT_MISSING"
    if "timeout" in combined or "timed out" in combined:
        return "TIMEOUT"
    if "401" in combined or "403" in combined or "api key" in combined or "unauthorized" in combined:
        return "AUTH"
    if "429" in combined or "rate limit" in combined:
        return "RATE_LIMIT"
    if "modulenotfounderror" in combined or "importerror" in combined:
        return "DEPENDENCY"
    if "connection" in combined or "network" in combined or "dns" in combined:
        return "NETWORK"
    return "RUNTIME"


def run_one_test(iteration: int, test_case: Dict, workspace: Path) -> TestResult:
    name = test_case["name"]
    command = test_case["command"]
    timeout_seconds = int(test_case.get("timeout_seconds", 600))
    required_artifacts = test_case.get("required_artifacts", [])

    start = time.perf_counter()

    try:
        process = subprocess.run(
            command,
            cwd=str(workspace),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        exit_code = process.returncode
        stdout = process.stdout or ""
        stderr = process.stderr or ""
    except subprocess.TimeoutExpired as e:
        duration = time.perf_counter() - start
        stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
        stderr = (e.stderr or "") if isinstance(e.stderr, str) else ""
        return TestResult(
            iteration=iteration,
            test_name=name,
            command=command,
            status="failed",
            exit_code=124,
            duration_seconds=round(duration, 2),
            missing_artifacts=[],
            stdout_tail=tail_text(stdout),
            stderr_tail=tail_text(stderr + "\nCommand timed out."),
            error_type="TIMEOUT",
        )

    duration = time.perf_counter() - start
    missing_artifacts: List[str] = []

    for artifact in required_artifacts:
        artifact_path = workspace / artifact
        if not artifact_path.exists():
            missing_artifacts.append(artifact)

    error_type = classify_error(exit_code, stdout, stderr, missing_artifacts)
    status = "passed" if exit_code == 0 and not missing_artifacts else "failed"

    return TestResult(
        iteration=iteration,
        test_name=name,
        command=command,
        status=status,
        exit_code=exit_code,
        duration_seconds=round(duration, 2),
        missing_artifacts=missing_artifacts,
        stdout_tail=tail_text(stdout),
        stderr_tail=tail_text(stderr),
        error_type=error_type,
    )


def build_recommendations(results: List[TestResult]) -> List[str]:
    if not results:
        return ["没有可用结果，先执行至少一轮测试。"]

    total = len(results)
    failed = [item for item in results if item.status == "failed"]
    fail_rate = len(failed) / total

    by_error: Dict[str, int] = {}
    for item in failed:
        by_error[item.error_type] = by_error.get(item.error_type, 0) + 1

    recs: List[str] = []

    if fail_rate <= 0.1:
        recs.append("当前回归通过率较高，可将快速回归集扩展到 CityBench 标准集并提高样本量。")

    if by_error.get("DEPENDENCY", 0) > 0:
        recs.append("发现依赖/导入类失败：建议锁定环境（requirements + conda env），在流水线增加 preflight 检查。")

    if by_error.get("AUTH", 0) > 0:
        recs.append("发现鉴权失败：建议统一 secrets 注入方式，新增 API Key 健康检查脚本并在测试前执行。")

    if by_error.get("RATE_LIMIT", 0) > 0:
        recs.append("发现限流：建议给 LLM/MCP 调用增加指数退避重试、并发上限与任务级熔断。")

    if by_error.get("TIMEOUT", 0) > 0:
        recs.append("发现超时：建议对感知/推理/工具调用分段设置超时，并记录耗时分位数用于瓶颈定位。")

    if by_error.get("ARTIFACT_MISSING", 0) > 0:
        recs.append("存在产物缺失：建议统一输出契约（每个任务必须写入标准 JSON/HTML/SVG），并做 schema 校验。")

    if by_error.get("NETWORK", 0) > 0:
        recs.append("出现网络失败：建议把外部调用经由统一客户端层，加入可配置代理、重试和降级路径。")

    if fail_rate > 0.3:
        recs.append("失败率偏高：优先收敛到单一 Agent 主干与单一 Tool Runtime，避免双入口导致行为漂移。")

    recs.append("建议将 Action 工具调用统一接入 MCP Tool Runtime，消除 `mcp_tools.py` 与 `action.py` 的重复实现。")
    recs.append("建议在任务上下文增加 trace_id，并贯穿感知→推理→决策→工具调用日志。")

    return recs


def render_markdown(
    suite_name: str,
    started_at: str,
    finished_at: str,
    iterations: int,
    results: List[TestResult],
    recommendations: List[str],
) -> str:
    passed = sum(1 for item in results if item.status == "passed")
    total = len(results)
    success_rate = (passed / total * 100.0) if total else 0.0

    lines = [
        f"# Iterative Test Report - {suite_name}",
        "",
        f"- Started: {started_at}",
        f"- Finished: {finished_at}",
        f"- Iterations: {iterations}",
        f"- Cases: {total}",
        f"- Passed: {passed}",
        f"- Success Rate: {success_rate:.2f}%",
        "",
        "## Case Results",
        "",
        "| Iteration | Case | Status | Exit | Duration(s) | Error Type |",
        "|---|---|---|---:|---:|---|",
    ]

    for item in results:
        lines.append(
            f"| {item.iteration} | {item.test_name} | {item.status} | {item.exit_code} | {item.duration_seconds:.2f} | {item.error_type} |"
        )

    lines.extend(["", "## Improvement Suggestions", ""])
    for rec in recommendations:
        lines.append(f"- {rec}")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    workspace = Path(__file__).resolve().parent
    config_path = (workspace / args.config).resolve()

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    plan = load_plan(config_path)
    suite_name = plan.get("suite_name", "iterative_suite")
    tests = plan.get("tests", [])

    if not tests:
        raise ValueError("No tests found in config")

    if args.dry_run:
        print(f"[DRY RUN] suite={suite_name}, iterations={args.iterations}")
        for index in range(1, args.iterations + 1):
            for case in tests:
                print(f"iter={index} case={case['name']} cmd={case['command']}")
        return 0

    out_dir = (workspace / args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now().isoformat()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    all_results: List[TestResult] = []

    print(f"[INFO] Start iterative cycle: suite={suite_name}, iterations={args.iterations}")

    for iteration in range(1, args.iterations + 1):
        print(f"\n[INFO] Iteration {iteration}/{args.iterations}")
        for case in tests:
            print(f"[RUN] {case['name']}: {case['command']}")
            result = run_one_test(iteration, case, workspace)
            all_results.append(result)
            print(
                f"[DONE] {result.test_name} status={result.status} exit={result.exit_code} "
                f"duration={result.duration_seconds:.2f}s"
            )

            if result.missing_artifacts:
                print(f"[WARN] Missing artifacts: {', '.join(result.missing_artifacts)}")

            if args.stop_on_fail and result.status == "failed":
                print("[STOP] stop-on-fail enabled, aborting remaining tests.")
                break

            time.sleep(max(0.0, args.cooldown))

        if args.stop_on_fail and all_results and all_results[-1].status == "failed":
            break

    finished_at = datetime.now().isoformat()

    recommendations = build_recommendations(all_results)

    payload = {
        "suite_name": suite_name,
        "started_at": started_at,
        "finished_at": finished_at,
        "iterations": args.iterations,
        "results": [asdict(item) for item in all_results],
        "recommendations": recommendations,
    }

    json_path = out_dir / f"iterative_cycle_{run_id}.json"
    md_path = out_dir / f"iterative_cycle_{run_id}.md"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    markdown = render_markdown(
        suite_name=suite_name,
        started_at=started_at,
        finished_at=finished_at,
        iterations=args.iterations,
        results=all_results,
        recommendations=recommendations,
    )

    with md_path.open("w", encoding="utf-8") as f:
        f.write(markdown)

    total = len(all_results)
    passed = sum(1 for item in all_results if item.status == "passed")
    print("\n[SUMMARY]")
    print(f"Total={total}, Passed={passed}, Failed={total - passed}")
    print(f"JSON report: {json_path}")
    print(f"MD report:   {md_path}")

    return 0 if total == passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
