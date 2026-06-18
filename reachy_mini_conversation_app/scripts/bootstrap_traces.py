#!/usr/bin/env python3
"""Bootstrap synthetic TRACER traces (Phase B')."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from bootstrap_catalog import CHAT_TRAPS, MIN_CHAT_TRAPS, MIN_PARAPHRASES_PER_LABEL, PARAPHRASES
from tracer_dataset_utils import build_row

ROOT = Path(__file__).resolve().parents[1]
REAL_PATH = ROOT / "tracer_data" / "traces.jsonl"
SYNTH_PATH = ROOT / "tracer_data" / "traces_synthetic.jsonl"
ALL_PATH = ROOT / "tracer_data" / "traces_all.jsonl"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _normalize_input(text: str) -> str:
    return text.strip()


def load_real_inputs(path: Path | None = None) -> set[str]:
    real_path = path or REAL_PATH
    return {_normalize_input(row["input"]) for row in _load_jsonl(real_path)}


def generate_synthetic(*, exclude_real: bool = True) -> list[dict[str, Any]]:
    """Build synthetic rows from the catalog, deduped and optionally excluding real inputs."""
    real_inputs = load_real_inputs() if exclude_real else set()
    rows: list[dict[str, Any]] = []
    input_to_teacher: dict[str, str] = {}

    for teacher, phrases in PARAPHRASES.items():
        for phrase in phrases:
            key = _normalize_input(phrase)
            if not key or key in real_inputs:
                continue
            if key in input_to_teacher and input_to_teacher[key] != teacher:
                raise ValueError(
                    f"Cross-label duplicate: {key!r} -> {input_to_teacher[key]!r} and {teacher!r}"
                )
            if key in input_to_teacher:
                continue
            input_to_teacher[key] = teacher
            rows.append(build_row(key, teacher, source="bootstrap"))

    for phrase in CHAT_TRAPS:
        key = _normalize_input(phrase)
        if not key or key in real_inputs:
            continue
        if key in input_to_teacher and input_to_teacher[key] != "chat":
            # Command labels take priority over chat traps sharing vocabulary.
            continue
        if key in input_to_teacher:
            continue
        input_to_teacher[key] = "chat"
        rows.append(build_row(key, "chat", source="bootstrap"))

    return rows


def cmd_generate() -> int:
    rows = generate_synthetic()
    _write_jsonl(SYNTH_PATH, rows)
    counts = Counter(row["teacher"] for row in rows)
    print(f"Wrote {len(rows)} lines to {SYNTH_PATH}")
    print(f"  command labels: {sum(1 for k in counts if k != 'chat')}")
    print(f"  chat traps: {counts.get('chat', 0)}")
    return 0


def merge_traces(
    real_path: Path = REAL_PATH,
    synth_path: Path = SYNTH_PATH,
    out_path: Path = ALL_PATH,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Merge real + synthetic; real wins on input conflicts."""
    real_rows = [row for row in _load_jsonl(real_path) if row.get("routed_by") != "tracer"]
    synth_rows = _load_jsonl(synth_path)

    merged: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    conflicts = 0

    for row in real_rows:
        key = _normalize_input(row["input"])
        index[key] = row
        merged.append(row)

    synth_added = 0
    for row in synth_rows:
        key = _normalize_input(row["input"])
        if key in index:
            if index[key].get("teacher") != row.get("teacher"):
                conflicts += 1
            continue
        index[key] = row
        merged.append(row)
        synth_added += 1

    _write_jsonl(out_path, merged)
    stats = {
        "real": len(real_rows),
        "synthetic": len(synth_rows),
        "synthetic_added": synth_added,
        "merged": len(merged),
        "conflicts": conflicts,
    }
    return merged, stats


def cmd_merge() -> int:
    _, stats = merge_traces()
    print(f"Wrote {stats['merged']} lines to {ALL_PATH}")
    print(
        f"  real={stats['real']} synthetic={stats['synthetic']} "
        f"added={stats['synthetic_added']} conflicts={stats['conflicts']}"
    )
    return 0


def compute_stats(rows: list[dict[str, Any]], *, min_threshold: int = 10) -> dict[str, Any]:
    counts = Counter(row["teacher"] for row in rows)
    small = {k: v for k, v in sorted(counts.items()) if k != "chat" and v < min_threshold}
    return {
        "total": len(rows),
        "teachers": dict(counts.most_common()),
        "small_classes": small,
    }


def cmd_stats(path: Path) -> int:
    rows = _load_jsonl(path)
    if not rows:
        print(f"No rows in {path}")
        return 1
    stats = compute_stats(rows)
    print(f"Total: {stats['total']}")
    print("Teachers:")
    for teacher, count in stats["teachers"].items():
        print(f"  {count:4} {teacher}")
    if stats["small_classes"]:
        print("Classes below 10:")
        for teacher, count in stats["small_classes"].items():
            print(f"  {count:4} {teacher}")
    else:
        print("All command classes have >= 10 examples.")
    return 0


def validate_catalog() -> None:
    for teacher, phrases in PARAPHRASES.items():
        unique = {_normalize_input(p) for p in phrases}
        unique.discard("")
        if len(unique) < MIN_PARAPHRASES_PER_LABEL:
            raise ValueError(
                f"{teacher} has only {len(unique)} unique paraphrases "
                f"(min {MIN_PARAPHRASES_PER_LABEL})"
            )
    unique_traps = {_normalize_input(p) for p in CHAT_TRAPS}
    unique_traps.discard("")
    if len(unique_traps) < MIN_CHAT_TRAPS:
        raise ValueError(
            f"CHAT_TRAPS has only {len(unique_traps)} unique entries (min {MIN_CHAT_TRAPS})"
        )


def main() -> int:
    validate_catalog()
    parser = argparse.ArgumentParser(description="Bootstrap TRACER trace datasets.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate", help="Write tracer_data/traces_synthetic.jsonl")
    sub.add_parser("merge", help="Merge real + synthetic into traces_all.jsonl")
    stats_p = sub.add_parser("stats", help="Show teacher distribution for a JSONL file")
    stats_p.add_argument("path", nargs="?", default=str(ALL_PATH), type=Path)

    args = parser.parse_args()
    if args.command == "generate":
        return cmd_generate()
    if args.command == "merge":
        return cmd_merge()
    if args.command == "stats":
        return cmd_stats(args.path)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
