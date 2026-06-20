#!/usr/bin/env python3
"""Derive suggested gate policy rules from annotated traces (offline, Phase 1)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from gate_policy_utils import (  # noqa: E402
    DEFAULT_MIN_RATIO,
    DEFAULT_MIN_SAMPLES,
    aggregate_annotation_flags,
    suggest_policy_from_stats,
)

ROOT = _SCRIPTS_DIR.parent
DEFAULT_TRACES = ROOT / "tracer_data" / "traces.jsonl"


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Trace file not found: {path}")
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        row = json.loads(line)
        if "teacher" not in row:
            raise ValueError(f"Missing teacher at line {line_no} in {path}")
        rows.append(row)
    return rows


def format_python_snippet(suggestion: dict[str, Any]) -> str:
    enrichment = suggestion["enrichment_candidates"]
    hybrid = suggestion["hybrid_candidates"]
    lines = [
        "# Suggested policy snippets — validate manually before integrating intent_gate.py (Phase 2)",
        f"# Thresholds: min_samples={suggestion['min_samples']}, min_ratio={suggestion['min_ratio']}",
        "",
        "ENRICHMENT_HEAD_TRACKING = frozenset(",
        "    {",
    ]
    for label in enrichment:
        lines.append(f'        "{label}",')
    lines.extend(
        [
            "    }",
            ")",
            "",
            "HYBRID_ALSO_CHAT = frozenset(",
            "    {",
        ]
    )
    for label in hybrid:
        lines.append(f'        "{label}",')
    lines.extend(["    }", ")"])
    return "\n".join(lines) + "\n"


def cmd_report(
    traces_path: Path,
    *,
    min_samples: int,
    min_ratio: float,
    output_json: Path | None,
) -> int:
    rows = load_rows(traces_path)
    stats = aggregate_annotation_flags(rows)
    suggestion = suggest_policy_from_stats(stats, min_samples=min_samples, min_ratio=min_ratio)
    report = {
        "traces_path": str(traces_path),
        "n_rows": len(rows),
        "stats_by_teacher": stats,
        "suggestion": suggestion,
        "python_snippet": format_python_snippet(suggestion),
    }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(text + "\n", encoding="utf-8")
        print(f"\nWrote report to {output_json}", file=sys.stderr)
    print("\n--- Python snippet (manual review required) ---\n", file=sys.stderr)
    print(report["python_snippet"], file=sys.stderr)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Derive gate enrichment/hybrid candidates from annotated traces"
    )
    parser.add_argument(
        "--traces",
        type=Path,
        default=DEFAULT_TRACES,
        help=f"Annotated traces JSONL (default: {DEFAULT_TRACES})",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_MIN_SAMPLES,
        help=f"Minimum traces per teacher label (default: {DEFAULT_MIN_SAMPLES})",
    )
    parser.add_argument(
        "--min-ratio",
        type=float,
        default=DEFAULT_MIN_RATIO,
        help=f"Minimum ratio for flag promotion (default: {DEFAULT_MIN_RATIO})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write full JSON report",
    )
    args = parser.parse_args()
    raise SystemExit(
        cmd_report(
            args.traces.resolve(),
            min_samples=args.min_samples,
            min_ratio=args.min_ratio,
            output_json=args.output.resolve() if args.output else None,
        )
    )


if __name__ == "__main__":
    main()
