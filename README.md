# Reachy Tracer OpenAI

Intégration de **TRACER** (Intent Gate) dans l'application de conversation Reachy Mini avec le backend OpenAI Realtime.

## Contenu du dépôt

- [`SPEC_TRACER_REACHY.md`](SPEC_TRACER_REACHY.md) — spécification technique du projet
- [`reachy_mini_conversation_app/`](reachy_mini_conversation_app/) — application conversationnelle Reachy Mini, forkée depuis [pollen-robotics/reachy_mini_conversation_app](https://github.com/pollen-robotics/reachy_mini_conversation_app) avec les modules TRACER

## Démarrage rapide

```bash
cd reachy_mini_conversation_app
cp .env.example .env   # renseigner OPENAI_API_KEY
# voir reachy_mini_conversation_app/README.md pour l'installation complète
```

## Modules TRACER ajoutés

- `intent_gate.py` — classification d'intention via embeddings TRACER
- `trace_collector.py` — collecte des traces de conversation
- `scripts/fit_tracer.py` — entraînement du modèle TRACER
