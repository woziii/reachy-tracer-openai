# Phase C — Fiche de relevé test live (§10.2)

Session : ____________________  
Date : ____________________  
Opérateur : ____________________  
Commande : `TRACE_COLLECT=1 INTENT_GATE=1 reachy-mini-conversation-app --gradio --head-tracker mediapipe --debug`  
Log session : `tee session.log` → analyse : `python3 scripts/analyze_gate_session.py session.log`

---

## Définition du faux bypass (§10.3 raffinée)

**Faux bypass = O** uniquement si un input **non-émotionnel** et **non-commande** a été exécuté en bypass alors qu'une réponse du LLM était attendue.

**Ne pas compter comme faux bypass** :
- variation intra-famille émotionnelle (ex. `irritated` au lieu de `displeased` sur « Tu es insupportable ») ;
- émotion ou commande plausible mais pas celle que vous auriez choisie ;
- score ≥ 0.90 sur une émotion nette.

En cas de doute, noter le commentaire et trancher après relecture du JSONL (`routed_by: "tracer"`).

---

## Relevé des 10 tours

| # | Input vocal (§10.2) | Décision attendue | Décision observée (log) | Robot : parle / silence | Latence (ms) | Faux bypass O/N | Commentaire |
|---|---------------------|-------------------|-------------------------|-------------------------|--------------|-----------------|-------------|
| 1 | Bonjour, comment tu vas ? | DEFER | | | | | |
| 2 | Regarde-moi | BYPASS (`head_tracking:on`) | | | | | |
| 3 | Pourquoi tu me regardes ? | DEFER (LLM connaît le contexte injecté) | | | | | |
| 4 | Danse ! | BYPASS (`dance`) | | | | | |
| 5 | Stop | BYPASS (`stop`, 2 tools) | | | | | |
| 6 | Je déteste les lundis mais bon | DEFER (piège non-émotionnel) | | | | | |
| 7 | Fais le triste | BYPASS (`play_emotion:sad`, si score ≥ 0.90) | | | | | |
| 8 | C'est quoi le head tracking ? | DEFER (piège lexical) | | | | | |
| 9 | Regarde à gauche | BYPASS (`move_head:left`) | | | | | |
| 10 | Tu peux me décrire ce que tu vois ? | DEFER (camera → LLM) | | | | | |

**Latence** : noter `first audio` ou `response.created` depuis les logs `Turn latency` (tours DEFER) ; les tours BYPASS n'ont en principe pas de latence LLM.

---

## Métriques de fin de session (§10.3)

À remplir après `python3 scripts/analyze_gate_session.py session.log` :

| Métrique | Valeur | Cible / note |
|----------|--------|--------------|
| Bypass rate | _____ % (___/___) | modeste, ~30–50 % au début |
| Faux bypass (manuel) | _____ | **0** |
| Latence moyenne DEFER (audio) | _____ ms | baseline conversation |
| Latence commande BYPASS | _____ ms | transcription + <50 ms (pas de vocal LLM) |
| Tours DEFER sans latence mesurée | _____ | vérifier si gate actif |

---

## Notes libres

_Espace pour anomalies, régressions, idées de traces à ajouter au prochain merge :_

```




```
