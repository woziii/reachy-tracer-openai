#!/usr/bin/env python3
"""Compare IntentGate routing between two TRACER artifacts (ex. TA 0.95 vs 0.92)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EMBEDDER = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

sys.path.insert(0, str(ROOT / "src"))

from reachy_mini_conversation_app.intent_gate import (  # noqa: E402
    EMOTION_BYPASS_FLOOR,
    EXCLUDED_EMOTIONS,
    _build_silent_policy,
)

_GATE_INPUT_RE = re.compile(r"input=(?P<input>.+?)(?:\s+\(below emotion floor\))?$")

BOUNDARY_PHRASES = [
    "Fais danser.",
    "Montre-moi tes pas.",
    "Observe-moi.",
    "Tourne-toi vers moi.",
    "Arrête de danser.",
    "Arrête de pleuvoir.",
    "Relâche le suivi.",
    "Fixe en bas.",
    "Fais l'affectueux.",
    "Écoute cette musique.",
    "Tu pourrais danser un peu ?",
    "Haut avec la tête.",
]

TRAP_PHRASES = [
    "J'ai peur de rater mon examen.",
    "Regarde ce qu'il y a dans ma boîte, c'est dégueulasse.",
    "T'es sûr de ce que tu dis là?",
    "Pourquoi tu me regardes?",
    "Montre-moi ce que la caméra voit.",
]


def _extract_session_phrases(log_paths: list[Path]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in log_paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "IntentGate " not in line:
                continue
            match = _GATE_INPUT_RE.search(line)
            if not match:
                continue
            raw = match.group("input").strip()
            try:
                import ast

                text = str(ast.literal_eval(raw))
            except (SyntaxError, ValueError):
                text = raw
            if text and text not in seen:
                seen.add(text)
                ordered.append(text)
    return ordered


def _gate_route(
    router: object,
    policy: dict[str, list[tuple[str, str]]],
    text: str,
) -> tuple[str, str | None, float, str | None]:
    """Même logique que IntentGate.route sans recharger l'embedder."""
    try:
        out = router.predict(text)  # type: ignore[attr-defined]
    except Exception:
        return "defer", None, 0.0, None

    label = out.get("label")
    decision_raw = out.get("decision")
    score = float(out.get("accept_score", 0.0) or 0.0)

    if decision_raw != "handled" or label == "chat" or label not in policy:
        return "defer", label, score, decision_raw

    if isinstance(label, str) and label.startswith("play_emotion:"):
        intent = label.split(":", 1)[1]
        if intent in EXCLUDED_EMOTIONS or score < EMOTION_BYPASS_FLOOR:
            return "defer", label, score, decision_raw

    return "bypass", label, score, decision_raw


class GatePair:
    """Deux routeurs TRACER partageant un seul embedder."""

    def __init__(self, before_dir: Path, after_dir: Path, embedder_name: str) -> None:
        import tracer
        from tracer import Embedder

        self._policy = _build_silent_policy()
        embedder = Embedder.from_sentence_transformers(embedder_name)
        self.before = tracer.load_router(before_dir, embedder=embedder)
        self.after = tracer.load_router(after_dir, embedder=embedder)

    def route_before(self, text: str) -> tuple[str, str | None, float, str | None]:
        return _gate_route(self.before, self._policy, text)

    def route_after(self, text: str) -> tuple[str, str | None, float, str | None]:
        return _gate_route(self.after, self._policy, text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare deux artifacts TRACER via IntentGate.")
    parser.add_argument("--before", type=Path, default=ROOT / "tracer_data" / ".tracer_ta095")
    parser.add_argument("--after", type=Path, default=ROOT / "tracer_data" / ".tracer")
    parser.add_argument(
        "--session-logs",
        type=Path,
        nargs="*",
        default=[
            ROOT / "tracer_data" / "session_live_phase_c.log",
            ROOT / "tracer_data" / "session_live_phase_c_s2.log",
        ],
    )
    parser.add_argument("--embedder", default=DEFAULT_EMBEDDER)
    args = parser.parse_args(argv)

    # Valide embedder.txt (même check que IntentGate au runtime).
    fitted = (args.after / "embedder.txt").read_text(encoding="utf-8").strip()
    if fitted != args.embedder.strip():
        raise SystemExit(f"Embedder mismatch: artifact {fitted!r} vs {args.embedder!r}")

    gates = GatePair(args.before, args.after, args.embedder)

    phrases = _extract_session_phrases(args.session_logs)
    extra = [p for p in BOUNDARY_PHRASES + TRAP_PHRASES if p not in phrases]
    all_phrases = phrases + extra

    changed: list[tuple[str, str, str, str | None, str | None, float, float]] = []
    before_bypass = 0
    after_bypass = 0

    print("Comparaison IntentGate — refit TRACER")
    print(f"  Avant : {args.before}")
    print(f"  Après : {args.after}")
    print()

    for text in all_phrases:
        b_dec, b_label, b_score, b_raw = gates.route_before(text)
        a_dec, a_label, a_score, a_raw = gates.route_after(text)
        if b_dec == "bypass":
            before_bypass += 1
        if a_dec == "bypass":
            after_bypass += 1
        if (b_dec, b_label) != (a_dec, a_label):
            changed.append((text, b_dec, a_dec, b_label, a_label, b_score, a_score))

    print("Synthèse")
    print("--------")
    print(f"Phrases testées : {len(all_phrases)}")
    print(f"BYPASS avant : {before_bypass} ({before_bypass / len(all_phrases) * 100:.1f}%)")
    print(f"BYPASS après : {after_bypass} ({after_bypass / len(all_phrases) * 100:.1f}%)")
    print(f"Changements decision/label : {len(changed)}")
    print()

    if changed:
        print("Différences (avant → après)")
        print("---------------------------")
        for text, b_dec, a_dec, b_label, a_label, b_score, a_score in changed:
            print(
                f"  {text!r}\n"
                f"    {b_dec} {b_label} ({b_score:.3f}, {b_raw}) → "
                f"{a_dec} {a_label} ({a_score:.3f}, {a_raw})"
            )
    else:
        print("Aucun changement de routage sur ce jeu de phrases.")

    print()
    print("Pièges et limites (après refit)")
    print("-------------------------------")
    for text in TRAP_PHRASES + BOUNDARY_PHRASES:
        a_dec, a_label, a_score, a_raw = gates.route_after(text)
        flag = " ⚠️" if a_dec == "bypass" and text in TRAP_PHRASES else ""
        print(f"  {a_dec:<6} {a_label or '-':<24} {a_score:.3f}  {text!r}{flag}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
