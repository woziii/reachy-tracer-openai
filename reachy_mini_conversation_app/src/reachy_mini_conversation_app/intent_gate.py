"""Passerelle d'intention : route les transcripts entre bypass local et LLM."""

from __future__ import annotations
import json
import logging
from typing import Literal
from pathlib import Path
from dataclasses import dataclass


logger = logging.getLogger(__name__)

# Seuil minimal d'accept_score pour bypasser une émotion (collisions intra-famille OK en dessous).
EMOTION_BYPASS_FLOOR = 0.88

# label TRACER -> liste de (tool_name, args_json). "stop" mappe deux tools.
SILENT_POLICY_ACTIONS: dict[str, list[tuple[str, str]]] = {
    "head_tracking:on": [("head_tracking", '{"start": true}')],
    "head_tracking:off": [("head_tracking", '{"start": false}')],
    "dance": [("dance", "{}")],
    "stop": [
        ("stop_dance", '{"dummy": true}'),
        ("stop_emotion", '{"dummy": true}'),
    ],
    "move_head:left": [("move_head", '{"direction": "left"}')],
    "move_head:right": [("move_head", '{"direction": "right"}')],
    "move_head:up": [("move_head", '{"direction": "up"}')],
    "move_head:down": [("move_head", '{"direction": "down"}')],
    "move_head:front": [("move_head", '{"direction": "front"}')],
}

# Intents nus autorisés au bypass (clé policy = play_emotion:{intent}, soumis à EMOTION_BYPASS_FLOOR).
BYPASSED_EMOTIONS: frozenset[str] = frozenset(
    {
        "sad",
        "happy",
        "loving",
        "surprised",
        "excited",
        "tired",
        "greeting",
        "goodbye",
        "irritated",
        "displeased",
        "angry",
        "disgusted",
        "anxious",
        "embarrassed",
        "impatient",
        "sleepy",
        "scared",
        "welcoming",
        "success",
        "calming",
    }
)

# Intents nus exclus du bypass (jamais ajoutés à la policy, même si handled par TRACER).
EXCLUDED_EMOTIONS: frozenset[str] = frozenset(
    {
        "thinking",
        "attentive",
        "confused",
        "uncertain",
        "dying",
    }
)

GateDecision = Literal["bypass", "defer"]


@dataclass(frozen=True)
class RouteMeta:
    """Métadonnées de prédiction TRACER pour audit, UI et trace JSONL."""

    label: str | None
    accept_score: float
    decision: str | None


def _read_embedder_txt(artifact_dir: Path) -> str:
    path = artifact_dir / "embedder.txt"
    if not path.is_file():
        raise FileNotFoundError(f"Missing embedder.txt in {artifact_dir}")
    return path.read_text(encoding="utf-8").strip()


def _build_silent_policy() -> dict[str, list[tuple[str, str]]]:
    """Assemble la policy complète : actions + play_emotion:{intent} pour BYPASSED_EMOTIONS."""
    policy = dict(SILENT_POLICY_ACTIONS)
    for intent in sorted(BYPASSED_EMOTIONS):
        if intent in EXCLUDED_EMOTIONS:
            continue
        label = f"play_emotion:{intent}"
        policy[label] = [("play_emotion", json.dumps({"emotion": intent}, ensure_ascii=False))]
    return policy


class IntentGate:
    """Routeur TRACER pour bypass silencieux des commandes et émotions nettes."""

    def __init__(self, artifact_dir: str, embedder_name: str) -> None:
        """Charge l'artifact TRACER et valide la cohérence embedder fit/runtime."""
        import tracer
        from tracer import Embedder

        artifact_path = Path(artifact_dir)
        fitted_embedder = _read_embedder_txt(artifact_path)
        expected = embedder_name.strip()
        if fitted_embedder != expected:
            raise ValueError(
                f"Embedder mismatch: artifact has {fitted_embedder!r}, runtime expects {expected!r}"
            )

        embedder = Embedder.from_sentence_transformers(expected)
        self.router = tracer.load_router(artifact_path, embedder=embedder)
        self._policy = _build_silent_policy()

    def route(self, transcript: str) -> tuple[GateDecision, list[tuple[str, str]], RouteMeta]:
        """Décide bypass ou defer ; retourne toujours (decision, actions, RouteMeta)."""
        try:
            out = self.router.predict(transcript)
        except Exception:
            logger.exception("IntentGate prediction failed; deferring to LLM")
            return ("defer", [], RouteMeta(label=None, accept_score=0.0, decision=None))

        label = out.get("label")
        decision_raw = out.get("decision")
        score = float(out.get("accept_score", 0.0) or 0.0)
        meta = RouteMeta(label=label, accept_score=score, decision=decision_raw)

        if decision_raw != "handled" or label == "chat" or label not in self._policy:
            logger.info(
                "IntentGate DEFER label=%s decision=%s score=%.3f input=%r",
                label,
                decision_raw,
                score,
                transcript,
            )
            return ("defer", [], meta)

        if isinstance(label, str) and label.startswith("play_emotion:") and score < EMOTION_BYPASS_FLOOR:
            logger.info(
                "IntentGate DEFER label=%s decision=%s score=%.3f input=%r (below emotion floor)",
                label,
                decision_raw,
                score,
                transcript,
            )
            return ("defer", [], meta)

        logger.info(
            "IntentGate BYPASS label=%s decision=%s score=%.3f input=%r",
            label,
            decision_raw,
            score,
            transcript,
        )
        return ("bypass", self._policy[label], meta)
