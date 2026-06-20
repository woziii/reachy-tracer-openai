"""Shared helpers for gate policy preview and offline derivation (Phase 1/2)."""

from __future__ import annotations

from typing import Any

HEAD_TRACKING_ON = ("head_tracking", '{"start": true}')

# Default thresholds for derive_gate_policy.py (human review required before runtime use).
DEFAULT_MIN_SAMPLES = 3
DEFAULT_MIN_RATIO = 0.60


def resolve_phase2_actions(
    teacher: str,
    *,
    also_chat: bool = False,
    also_head_tracking: bool = False,
) -> list[tuple[str, str]]:
    """Build ordered tool actions for Phase 2 runtime preview (not executed in Phase 1)."""
    actions: list[tuple[str, str]] = []
    if also_head_tracking and not teacher.startswith("head_tracking:"):
        actions.append(HEAD_TRACKING_ON)
    if teacher == "chat":
        if also_head_tracking:
            actions.append(HEAD_TRACKING_ON)
        return actions
    if teacher == "head_tracking:on":
        actions.append(HEAD_TRACKING_ON)
        return actions
    if teacher == "head_tracking:off":
        return [("head_tracking", '{"start": false}')]
    if teacher == "dance":
        actions.append(("dance", "{}"))
        return actions
    if teacher == "stop":
        return [
            ("stop_dance", '{"dummy": true}'),
            ("stop_emotion", '{"dummy": true}'),
        ]
    if teacher.startswith("move_head:"):
        direction = teacher.split(":", 1)[1]
        actions.append(("move_head", f'{{"direction": "{direction}"}}'))
        return actions
    if teacher.startswith("dance:"):
        move = teacher.split(":", 1)[1]
        actions.append(("dance", f'{{"move": "{move}"}}'))
        return actions
    if teacher.startswith("play_emotion:"):
        intent = teacher.split(":", 1)[1]
        actions.append(("play_emotion", f'{{"emotion": "{intent}"}}'))
        return actions
    return actions


def preview_phase2_runtime(
    teacher: str,
    *,
    also_chat: bool = False,
    also_head_tracking: bool = False,
) -> dict[str, Any]:
    """Describe expected Phase 2 gate behaviour for annotation UI preview."""
    actions = resolve_phase2_actions(
        teacher,
        also_chat=also_chat,
        also_head_tracking=also_head_tracking,
    )
    action_labels = [f"{name}({args})" for name, args in actions]

    if teacher == "chat" and not also_head_tracking:
        mode = "defer"
        summary = "Defer → LLM + TTS (chat pur)"
    elif also_chat and actions:
        mode = "hybrid"
        summary = f"Hybrid Phase 2 : {', '.join(action_labels)} + voix LLM"
    elif actions:
        mode = "bypass"
        summary = f"Bypass Phase 2 : {', '.join(action_labels)} (silencieux)"
    else:
        mode = "defer"
        summary = "Defer → LLM + TTS"

    return {
        "teacher": teacher,
        "also_chat": also_chat,
        "also_head_tracking": also_head_tracking,
        "mode": mode,
        "actions": action_labels,
        "summary": summary,
    }


def aggregate_annotation_flags(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate also_chat / also_head_tracking recurrence per teacher label."""
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        teacher = str(row.get("teacher", "chat"))
        bucket = stats.setdefault(
            teacher,
            {
                "count": 0,
                "also_chat": 0,
                "also_head_tracking": 0,
            },
        )
        bucket["count"] += 1
        if row.get("also_chat"):
            bucket["also_chat"] += 1
        if row.get("also_head_tracking"):
            bucket["also_head_tracking"] += 1

    for teacher, bucket in stats.items():
        n = bucket["count"]
        bucket["also_chat_ratio"] = bucket["also_chat"] / n if n else 0.0
        bucket["also_head_tracking_ratio"] = bucket["also_head_tracking"] / n if n else 0.0
    return stats


def suggest_policy_from_stats(
    stats: dict[str, dict[str, Any]],
    *,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    min_ratio: float = DEFAULT_MIN_RATIO,
) -> dict[str, Any]:
    """Suggest ENRICHMENT_RULES and HYBRID_EMOTIONS from aggregated annotation stats."""
    enrichment: list[str] = []
    hybrid: list[str] = []

    for teacher, bucket in sorted(stats.items()):
        if bucket["count"] < min_samples:
            continue
        if teacher.startswith("play_emotion:") or teacher == "chat":
            if bucket["also_head_tracking_ratio"] >= min_ratio:
                enrichment.append(teacher)
            if bucket["also_chat_ratio"] >= min_ratio:
                hybrid.append(teacher)

    return {
        "min_samples": min_samples,
        "min_ratio": min_ratio,
        "enrichment_candidates": enrichment,
        "hybrid_candidates": hybrid,
    }
