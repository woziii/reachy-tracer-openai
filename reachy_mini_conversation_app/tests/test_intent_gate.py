"""Tests for TRACER intent gate routing (Phase C)."""

from __future__ import annotations
from unittest.mock import MagicMock, patch

import pytest

from reachy_mini_conversation_app.intent_gate import (
    BYPASSED_EMOTIONS,
    EXCLUDED_EMOTIONS,
    EMOTION_BYPASS_FLOOR,
    SILENT_POLICY_ACTIONS,
    RouteMeta,
    IntentGate,
    _build_silent_policy,
)


def _make_gate() -> IntentGate:
    gate = IntentGate.__new__(IntentGate)
    gate.router = MagicMock()
    gate._policy = _build_silent_policy()
    return gate


def test_build_silent_policy_includes_actions() -> None:
    """Include command actions from SILENT_POLICY_ACTIONS in the built policy."""
    policy = _build_silent_policy()
    assert policy["head_tracking:on"] == SILENT_POLICY_ACTIONS["head_tracking:on"]
    assert len(policy["stop"]) == 2


def test_build_silent_policy_prefixes_bypassed_emotions() -> None:
    """Map each bypassed intent to play_emotion:{intent} policy keys."""
    policy = _build_silent_policy()
    for intent in BYPASSED_EMOTIONS:
        label = f"play_emotion:{intent}"
        assert label in policy
        tool_name, args_json = policy[label][0]
        assert tool_name == "play_emotion"
        assert f'"{intent}"' in args_json


def test_excluded_emotions_absent_from_policy() -> None:
    """Never add play_emotion:{intent} for intents in EXCLUDED_EMOTIONS."""
    policy = _build_silent_policy()
    for intent in EXCLUDED_EMOTIONS:
        assert f"play_emotion:{intent}" not in policy


def test_stop_policy_maps_two_tools() -> None:
    """Map the stop label to stop_dance and stop_emotion."""
    policy = _build_silent_policy()
    stop_actions = policy["stop"]
    assert [name for name, _ in stop_actions] == ["stop_dance", "stop_emotion"]


@pytest.mark.parametrize(
    ("predict_out", "expected_decision", "expected_actions_len"),
    [
        (
            {"decision": "handled", "label": "head_tracking:on", "accept_score": 0.99},
            "bypass",
            1,
        ),
        (
            {"decision": "handled", "label": "play_emotion:happy", "accept_score": 0.92},
            "bypass",
            1,
        ),
        (
            {"decision": "handled", "label": "play_emotion:happy", "accept_score": 0.87},
            "defer",
            0,
        ),
        (
            {"decision": "handled", "label": "play_emotion:loving", "accept_score": 0.897},
            "bypass",
            1,
        ),
        (
            {"decision": "handled", "label": "play_emotion:surprised", "accept_score": 0.889},
            "bypass",
            1,
        ),
        (
            {"decision": "handled", "label": "play_emotion:thinking", "accept_score": 0.99},
            "defer",
            0,
        ),
        (
            {"decision": "handled", "label": "chat", "accept_score": 0.99},
            "defer",
            0,
        ),
        (
            {"decision": "handled", "label": "dance:side_to_side_sway", "accept_score": 0.99},
            "defer",
            0,
        ),
        (
            {"decision": "declined", "label": "dance", "accept_score": 0.99},
            "defer",
            0,
        ),
    ],
)
def test_route_decision_table(
    predict_out: dict[str, object],
    expected_decision: str,
    expected_actions_len: int,
) -> None:
    """Route handled predictions to bypass or defer per SILENT_POLICY rules."""
    gate = _make_gate()
    gate.router.predict.return_value = predict_out

    decision, actions, meta = gate.route("test input")

    assert decision == expected_decision
    assert len(actions) == expected_actions_len
    assert isinstance(meta, RouteMeta)
    assert meta.label == predict_out.get("label")
    assert meta.decision == predict_out.get("decision")


def test_route_emotion_floor_boundary() -> None:
    """Accept emotions at exactly EMOTION_BYPASS_FLOOR."""
    gate = _make_gate()
    gate.router.predict.return_value = {
        "decision": "handled",
        "label": "play_emotion:sad",
        "accept_score": EMOTION_BYPASS_FLOOR,
    }

    decision, actions, _ = gate.route("fais le triste")

    assert decision == "bypass"
    assert len(actions) == 1


def test_route_emotion_just_below_floor_defers() -> None:
    """Defer emotions strictly below EMOTION_BYPASS_FLOOR."""
    gate = _make_gate()
    gate.router.predict.return_value = {
        "decision": "handled",
        "label": "play_emotion:loving",
        "accept_score": EMOTION_BYPASS_FLOOR - 0.001,
    }

    decision, actions, _ = gate.route("fais-moi un bisou")

    assert decision == "defer"
    assert actions == []


def test_route_prediction_exception_defers() -> None:
    """Defer to the LLM when router prediction raises."""
    gate = _make_gate()
    gate.router.predict.side_effect = RuntimeError("boom")

    decision, actions, meta = gate.route("danse")

    assert decision == "defer"
    assert actions == []
    assert meta.label is None


def test_init_rejects_embedder_mismatch(tmp_path) -> None:
    """Reject loading when embedder.txt does not match runtime config."""
    artifact = tmp_path / ".tracer"
    artifact.mkdir()
    (artifact / "embedder.txt").write_text("model-a\n", encoding="utf-8")

    with patch("tracer.load_router"), patch("tracer.Embedder.from_sentence_transformers"):
        with pytest.raises(ValueError, match="Embedder mismatch"):
            IntentGate(str(artifact), "model-b")


def test_init_loads_router_when_embedder_matches(tmp_path) -> None:
    """Load TRACER router when embedder.txt matches runtime config."""
    artifact = tmp_path / ".tracer"
    artifact.mkdir()
    model = "sentence-transformers/test-model"
    (artifact / "embedder.txt").write_text(model + "\n", encoding="utf-8")

    mock_router = MagicMock()
    with (
        patch("tracer.load_router", return_value=mock_router) as load_router,
        patch("tracer.Embedder.from_sentence_transformers") as from_st,
    ):
        gate = IntentGate(str(artifact), model)

    from_st.assert_called_once_with(model)
    load_router.assert_called_once()
    assert gate.router is mock_router
    assert "play_emotion:happy" in gate._policy
