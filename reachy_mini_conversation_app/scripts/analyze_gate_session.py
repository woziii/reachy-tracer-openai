#!/usr/bin/env python3
"""Analyse une session live Phase C (Intent Gate) à partir d'un fichier de log.

Usage typique :

    TRACE_COLLECT=1 INTENT_GATE=1 reachy-mini-conversation-app --gradio --debug 2>&1 | tee session.log
    python3 scripts/analyze_gate_session.py session.log
"""

from __future__ import annotations
import re
import ast
import sys
import argparse
from pathlib import Path
from statistics import mean
from collections import Counter
from dataclasses import field, dataclass


# Message après le séparateur « | » du format setup_logger (utils.py).
_LOG_MESSAGE_RE = re.compile(r"\|\s*(?P<message>.*)$")

_GATE_RE = re.compile(
    r"IntentGate (?P<gate>BYPASS|DEFER) "
    r"label=(?P<label>\S+) "
    r"decision=(?P<decision>\S+) "
    r"score=(?P<score>[\d.]+) "
    r"input=(?P<input>.+?)"
    r"(?:\s+\(below emotion floor\))?$"
)

_LATENCY_CREATED_RE = re.compile(
    r"Turn latency: response\.created (?P<ms>\d+) ms after user transcript"
)
_LATENCY_AUDIO_RE = re.compile(
    r"Turn latency: first audio delta (?P<ms>\d+) ms after user transcript"
)


@dataclass
class GateTurn:
    """Un tour routé par IntentGate."""

    index: int
    gate: str
    label: str
    decision: str
    score: float
    transcript: str
    below_floor: bool = False
    latency_created_ms: int | None = None
    latency_audio_ms: int | None = None


@dataclass
class SessionStats:
    """Statistiques agrégées d'une session."""

    turns: list[GateTurn] = field(default_factory=list)
    orphan_latencies_created: list[int] = field(default_factory=list)
    orphan_latencies_audio: list[int] = field(default_factory=list)


def _extract_message(line: str) -> str | None:
    match = _LOG_MESSAGE_RE.search(line)
    if match:
        return match.group("message").strip()
    if "IntentGate " in line or "Turn latency:" in line:
        return line.strip()
    return None


def _parse_input(raw: str) -> str:
    try:
        value = ast.literal_eval(raw.strip())
    except (SyntaxError, ValueError):
        return raw.strip()
    return str(value)


def parse_session_log(text: str) -> SessionStats:
    """Parse le contenu d'un fichier de log et associe latences aux tours DEFER."""
    stats = SessionStats()
    pending_created: list[int] = []
    pending_audio: list[int] = []

    for line in text.splitlines():
        message = _extract_message(line)
        if not message:
            continue

        gate_match = _GATE_RE.match(message)
        if gate_match:
            below_floor = "(below emotion floor)" in message
            turn = GateTurn(
                index=len(stats.turns) + 1,
                gate=gate_match.group("gate"),
                label=gate_match.group("label"),
                decision=gate_match.group("decision"),
                score=float(gate_match.group("score")),
                transcript=_parse_input(gate_match.group("input")),
                below_floor=below_floor,
            )
            stats.turns.append(turn)
            continue

        created_match = _LATENCY_CREATED_RE.search(message)
        if created_match:
            pending_created.append(int(created_match.group("ms")))
            continue

        audio_match = _LATENCY_AUDIO_RE.search(message)
        if audio_match:
            pending_audio.append(int(audio_match.group("ms")))

    _attach_latencies(stats, pending_created, pending_audio)
    return stats


def _attach_latencies(
    stats: SessionStats,
    pending_created: list[int],
    pending_audio: list[int],
) -> None:
    """Associe chaque latence au prochain tour DEFER sans mesure."""
    created_iter = iter(pending_created)
    audio_iter = iter(pending_audio)

    for turn in stats.turns:
        if turn.gate != "DEFER":
            continue
        if turn.latency_created_ms is None:
            try:
                turn.latency_created_ms = next(created_iter)
            except StopIteration:
                pass
        if turn.latency_audio_ms is None:
            try:
                turn.latency_audio_ms = next(audio_iter)
            except StopIteration:
                pass

    stats.orphan_latencies_created = list(created_iter)
    stats.orphan_latencies_audio = list(audio_iter)


def _avg(values: list[int | None]) -> float | None:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return mean(nums)


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0f} ms"


def _print_section(title: str) -> None:
    print()
    print(title)
    print("=" * len(title))


def format_report(stats: SessionStats) -> str:
    """Construit le rapport texte (utilisé pour tests et sortie console)."""
    lines: list[str] = []
    total = len(stats.turns)
    bypass_turns = [t for t in stats.turns if t.gate == "BYPASS"]
    defer_turns = [t for t in stats.turns if t.gate == "DEFER"]
    bypass_count = len(bypass_turns)
    defer_count = len(defer_turns)

    lines.append("Rapport session Intent Gate (Phase C)")
    lines.append("=" * 36)
    lines.append("")
    lines.append("Synthèse")
    lines.append("--------")
    lines.append(f"Tours routés (IntentGate) : {total}")
    lines.append(f"  BYPASS : {bypass_count}")
    lines.append(f"  DEFER  : {defer_count}")
    if total:
        lines.append(f"Bypass rate : {bypass_count / total * 100:.1f}% ({bypass_count}/{total})")
    else:
        lines.append("Bypass rate : n/a (aucun tour IntentGate dans le log)")

    lines.append("")
    lines.append("Répartition par label")
    lines.append("---------------------")
    by_label_bypass: Counter[str] = Counter()
    by_label_defer: Counter[str] = Counter()
    for turn in stats.turns:
        if turn.gate == "BYPASS":
            by_label_bypass[turn.label] += 1
        else:
            by_label_defer[turn.label] += 1

    all_labels = sorted(set(by_label_bypass) | set(by_label_defer))
    if not all_labels:
        lines.append("(aucun)")
    else:
        lines.append(f"{'Label':<28} {'BYPASS':>8} {'DEFER':>8}")
        lines.append(f"{'-' * 28} {'-' * 8} {'-' * 8}")
        for label in all_labels:
            lines.append(
                f"{label:<28} {by_label_bypass.get(label, 0):>8} {by_label_defer.get(label, 0):>8}"
            )

    lines.append("")
    lines.append("Latences moyennes (Turn latency)")
    lines.append("--------------------------------")
    lines.append(
        "BYPASS — response.created : "
        + _fmt_ms(_avg([t.latency_created_ms for t in bypass_turns]))
        + "  (attendu : n/a, pas de réponse LLM)"
    )
    lines.append(
        "BYPASS — first audio      : "
        + _fmt_ms(_avg([t.latency_audio_ms for t in bypass_turns]))
    )
    lines.append(
        "DEFER  — response.created : "
        + _fmt_ms(_avg([t.latency_created_ms for t in defer_turns]))
    )
    lines.append(
        "DEFER  — first audio      : "
        + _fmt_ms(_avg([t.latency_audio_ms for t in defer_turns]))
    )

    defer_with_created = sum(1 for t in defer_turns if t.latency_created_ms is not None)
    defer_with_audio = sum(1 for t in defer_turns if t.latency_audio_ms is not None)
    lines.append(
        f"  (DEFER avec mesure : {defer_with_created}/{defer_count} created, "
        f"{defer_with_audio}/{defer_count} audio)"
    )
    if stats.orphan_latencies_created or stats.orphan_latencies_audio:
        lines.append(
            f"  Latences orphelines : {len(stats.orphan_latencies_created)} created, "
            f"{len(stats.orphan_latencies_audio)} audio"
        )

    lines.append("")
    lines.append("Tours BYPASS — audit manuel")
    lines.append("---------------------------")
    if not bypass_turns:
        lines.append("(aucun bypass)")
    else:
        for turn in bypass_turns:
            floor_note = " [sous seuil émotion]" if turn.below_floor else ""
            lines.append(
                f"#{turn.index:02d}  label={turn.label}  score={turn.score:.3f}  "
                f"input={turn.transcript!r}{floor_note}"
            )

    lines.append("")
    lines.append("Tous les tours (ordre chronologique)")
    lines.append("------------------------------------")
    if not stats.turns:
        lines.append("(aucun)")
    else:
        for turn in stats.turns:
            lat_parts: list[str] = []
            if turn.latency_created_ms is not None:
                lat_parts.append(f"created={turn.latency_created_ms}ms")
            if turn.latency_audio_ms is not None:
                lat_parts.append(f"audio={turn.latency_audio_ms}ms")
            lat_str = f"  ({', '.join(lat_parts)})" if lat_parts else ""
            lines.append(
                f"#{turn.index:02d} {turn.gate:<6} label={turn.label:<24} "
                f"score={turn.score:.3f}  input={turn.transcript!r}{lat_str}"
            )

    lines.append("")
    lines.append(
        "Rappel faux bypass : compter uniquement un input non-émotionnel / non-commande "
        "exécuté à tort. Variation intra-famille (ex. irritated vs displeased) = OK."
    )
    return "\n".join(lines)


def print_report(stats: SessionStats) -> None:
    """Affiche le rapport sur stdout."""
    print(format_report(stats))


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée CLI."""
    parser = argparse.ArgumentParser(
        description="Analyse un log de session Intent Gate (Phase C TRACER).",
    )
    parser.add_argument(
        "log_file",
        type=Path,
        help="Fichier de log (ex. sortie de: ... --debug 2>&1 | tee session.log)",
    )
    args = parser.parse_args(argv)

    path = args.log_file
    if not path.is_file():
        print(f"Fichier introuvable : {path}", file=sys.stderr)
        return 1

    text = path.read_text(encoding="utf-8", errors="replace")
    stats = parse_session_log(text)
    print_report(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
