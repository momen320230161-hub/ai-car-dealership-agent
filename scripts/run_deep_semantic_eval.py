"""Run repeatable live semantic evaluations against the configured agent LLM."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.agent.llm import GeminiAgentLLM
from app.agent.schemas import RequestUnderstanding, sanitize_understanding


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("data/evals/chat_semantic_cases.json"),
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--model", default=None)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--retry-provider-failures", type=Path, default=None)
    parser.add_argument("--cooldown-seconds", type=float, default=0.0)
    parser.add_argument("--output-dir", type=Path, default=Path(".artifacts/deep-eval"))
    return parser.parse_args()


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(actual) - float(expected)) < 1
    if isinstance(expected, str):
        return str(actual or "").casefold() == expected.casefold()
    return actual == expected


def _evaluate(result: RequestUnderstanding, expected: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    intents = expected.get("intents", [])
    if intents and result.intent not in intents:
        failures.append(f"intent={result.intent!r}, expected one of {intents!r}")

    preferences = result.preference_updates.model_dump(exclude_none=True)
    for name, value in expected.get("preferences", {}).items():
        if not _same(preferences.get(name), value):
            failures.append(f"preference.{name}={preferences.get(name)!r}, expected {value!r}")
    for name in expected.get("forbidden_preferences", []):
        if name in preferences:
            failures.append(f"preference.{name} must be absent, got {preferences[name]!r}")

    clears = set(result.preference_clears)
    for name in expected.get("clears_include", []):
        if name not in clears:
            failures.append(f"preference_clears missing {name!r}")
    for name in expected.get("clears_exclude", []):
        if name in clears:
            failures.append(f"preference_clears unexpectedly contains {name!r}")

    actions = expected.get("dialogue_actions", [])
    if actions and result.dialogue_action not in actions:
        failures.append(f"dialogue_action={result.dialogue_action!r}, expected one of {actions!r}")

    scalar_checks = {
        "pending_field_answer": result.pending_field_answer,
        "reference_scope": result.reference_target.scope,
        "car_reference": result.car_reference,
        "explicit_car_id": result.explicit_car_id,
    }
    for name, actual in scalar_checks.items():
        if name in expected and not _same(actual, expected[name]):
            failures.append(f"{name}={actual!r}, expected {expected[name]!r}")

    selector = result.visible_reference_selector.model_dump()
    for name, value in expected.get("selector", {}).items():
        if not _same(selector.get(name), value):
            failures.append(f"selector.{name}={selector.get(name)!r}, expected {value!r}")

    requested = set(result.requested_car_fields)
    for name in expected.get("requested_fields_include", []):
        if name not in requested:
            failures.append(f"requested_car_fields missing {name!r}")

    if "comparison_references" in expected:
        actual_references = [str(value) for value in result.comparison_references]
        expected_references = [str(value) for value in expected["comparison_references"]]
        if actual_references != expected_references:
            failures.append(
                f"comparison_references={actual_references!r}, expected {expected_references!r}"
            )

    if "condition_order" in expected:
        if result.condition_preference_order != expected["condition_order"]:
            failures.append(
                "condition_preference_order="
                f"{result.condition_preference_order!r}, expected {expected['condition_order']!r}"
            )
    return failures


def _run_once(
    llm: GeminiAgentLLM,
    case: dict[str, Any],
    repetition: int,
    cooldown_seconds: float,
) -> dict[str, Any]:
    if cooldown_seconds > 0:
        time.sleep(cooldown_seconds)
    started = time.perf_counter()
    try:
        raw = llm.understand_with_context(
            case["message"],
            recent_messages=case.get("recent_messages", []),
            preferences=case.get("preferences", {}),
            conversation_context=case.get("context", {}),
        )
        result = sanitize_understanding(raw, case["message"])
        failures = _evaluate(result, case["expected"])
        return {
            "case_id": case["id"],
            "category": case["category"],
            "repetition": repetition,
            "passed": not failures,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "failures": failures,
            "result": result.model_dump(mode="json", exclude_none=True),
        }
    except Exception as exc:  # Evaluation must record provider failures and continue.
        chain: list[str] = []
        current: BaseException | None = exc
        while current is not None and len(chain) < 4:
            chain.append(f"{type(current).__name__}: {current}")
            current = current.__cause__
        return {
            "case_id": case["id"],
            "category": case["category"],
            "repetition": repetition,
            "passed": False,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "failures": [" <- ".join(chain)],
            "result": None,
        }


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# AutoDrive Deep Semantic Evaluation",
        "",
        f"- Timestamp: `{report['timestamp']}`",
        f"- Model: `{report['model']}`",
        f"- Cases: **{summary['cases']}**",
        f"- Repetitions: **{summary['repetitions']}**",
        f"- Run pass rate: **{summary['run_pass_rate']:.1%}**",
        f"- Stable case pass rate: **{summary['stable_case_pass_rate']:.1%}**",
        f"- Median latency: **{summary['latency_p50_ms']:.0f} ms**",
        f"- P95 latency: **{summary['latency_p95_ms']:.0f} ms**",
        "",
        "## Category scores",
        "",
        "| Category | Passed runs | Total runs | Pass rate |",
        "|---|---:|---:|---:|",
    ]
    for category, values in sorted(report["categories"].items()):
        lines.append(
            f"| {category} | {values['passed']} | {values['total']} | {values['pass_rate']:.1%} |"
        )
    lines.extend(["", "## Unstable or failing cases", ""])
    if not report["case_failures"]:
        lines.append("All cases passed every repetition.")
    else:
        for item in report["case_failures"]:
            lines.append(
                f"### {item['case_id']} — {item['passed_runs']}/{item['total_runs']} runs passed"
            )
            lines.append("")
            for failure, count in item["failure_counts"].items():
                lines.append(f"- `{count}x` {failure}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = _arguments()
    if args.repetitions < 1 or args.workers < 1:
        raise SystemExit("repetitions and workers must be positive")
    if args.cooldown_seconds < 0:
        raise SystemExit("cooldown-seconds cannot be negative")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.retry_provider_failures:
        previous = json.loads(args.retry_provider_failures.read_text(encoding="utf-8"))
        retry_ids = {
            result["case_id"]
            for result in previous.get("results", [])
            if any("AgentLLMError" in failure for failure in result.get("failures", []))
        }
        cases = [case for case in cases if case["id"] in retry_ids]
    if args.case_id:
        requested = set(args.case_id)
        cases = [case for case in cases if case["id"] in requested]
        missing = requested - {case["id"] for case in cases}
        if missing:
            raise SystemExit(f"Unknown case IDs: {sorted(missing)}")
    if not cases:
        raise SystemExit("No evaluation cases selected")
    app = create_app()
    model = args.model or app.config["AGENT_LLM_MODEL"]
    llm = GeminiAgentLLM(
        api_key=app.config.get("GEMINI_API_KEY"),
        model_name=model,
        temperature=float(app.config.get("AGENT_LLM_TEMPERATURE", 0.1)),
    )

    jobs = [(case, repetition) for case in cases for repetition in range(1, args.repetitions + 1)]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _run_once,
                llm,
                case,
                repetition,
                args.cooldown_seconds,
            ): (case["id"], repetition)
            for case, repetition in jobs
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            print(
                f"[{completed:03d}/{len(jobs):03d}] {status} "
                f"{result['case_id']} run={result['repetition']} "
                f"latency_ms={result['duration_ms']:.1f}",
                flush=True,
            )

    results.sort(key=lambda item: (item["case_id"], item["repetition"]))
    durations = sorted(float(item["duration_ms"]) for item in results)
    passed_runs = sum(bool(item["passed"]) for item in results)
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for result in results:
        by_case[result["case_id"]].append(result)
        category_counts[result["category"]]["total"] += 1
        if result["passed"]:
            category_counts[result["category"]]["passed"] += 1

    stable_cases = sum(all(item["passed"] for item in items) for items in by_case.values())
    case_failures = []
    for case_id, items in sorted(by_case.items()):
        if all(item["passed"] for item in items):
            continue
        failure_counts = Counter(failure for item in items for failure in item.get("failures", []))
        case_failures.append(
            {
                "case_id": case_id,
                "passed_runs": sum(bool(item["passed"]) for item in items),
                "total_runs": len(items),
                "failure_counts": dict(failure_counts),
            }
        )

    p95_index = min(len(durations) - 1, max(0, int(len(durations) * 0.95) - 1))
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "model": model,
        "summary": {
            "cases": len(cases),
            "repetitions": args.repetitions,
            "total_runs": len(results),
            "passed_runs": passed_runs,
            "run_pass_rate": passed_runs / len(results),
            "stable_cases": stable_cases,
            "stable_case_pass_rate": stable_cases / len(cases),
            "latency_p50_ms": statistics.median(durations),
            "latency_p95_ms": durations[p95_index],
        },
        "categories": {
            category: {
                "passed": counts["passed"],
                "total": counts["total"],
                "pass_rate": counts["passed"] / counts["total"],
            }
            for category, counts in category_counts.items()
        },
        "case_failures": case_failures,
        "results": results,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "semantic-results.json"
    markdown_path = args.output_dir / "semantic-report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    print(json.dumps(report["summary"], indent=2))
    return 0 if stable_cases == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
