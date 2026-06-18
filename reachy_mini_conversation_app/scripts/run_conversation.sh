#!/usr/bin/env bash
# Lance reachy-mini-conversation-app en arrière-plan (Intent Gate TRACER).
# Le daemon Reachy est supposé déjà démarré séparément.
#
# Usage :
#   ./scripts/run_conversation.sh start --trace      # TRACE_COLLECT=1
#   ./scripts/run_conversation.sh start --no-trace   # TRACE_COLLECT=0
#   ./scripts/run_conversation.sh status
#   ./scripts/run_conversation.sh logs [-f]
#   ./scripts/run_conversation.sh stop

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_DIR="$ROOT/tracer_data/.run"
LOG_DIR="$ROOT/tracer_data/logs"
PID_FILE="$RUN_DIR/conversation.pid"
LATEST_LOG_LINK="$LOG_DIR/latest.log"
GRADIO_URL="http://127.0.0.1:7860/"
STARTUP_TIMEOUT_SEC="${STARTUP_TIMEOUT_SEC:-120}"

usage() {
  cat <<'EOF'
Usage:
  run_conversation.sh start --trace | --no-trace
  run_conversation.sh stop
  run_conversation.sh status
  run_conversation.sh logs [-f]

Options start:
  --trace       Active la collecte JSONL (TRACE_COLLECT=1)
  --no-trace    Désactive la collecte (TRACE_COLLECT=0)

L'app démarre en arrière-plan avec Intent Gate (INTENT_GATE=1), Gradio,
MediaPipe et logs dans tracer_data/logs/.
EOF
}

resolve_app_bin() {
  if [[ -x "$ROOT/.venv/bin/reachy-mini-conversation-app" ]]; then
    echo "$ROOT/.venv/bin/reachy-mini-conversation-app"
    return 0
  fi
  if command -v reachy-mini-conversation-app >/dev/null 2>&1; then
    command -v reachy-mini-conversation-app
    return 0
  fi
  echo "Binaire introuvable. Créez le venv : uv sync && uv pip install tracer-llm sentence-transformers" >&2
  return 1
}

# Charge .env (sans laisser python-dotenv écraser TRACE_COLLECT au runtime).
load_dotenv_exports() {
  local env_file="$ROOT/.env"
  if [[ ! -f "$env_file" ]]; then
    echo "Fichier .env introuvable : $env_file" >&2
    return 1
  fi
  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      value="${BASH_REMATCH[2]}"
      value="${value#\"}"
      value="${value%\"}"
      value="${value#\'}"
      value="${value%\'}"
      export "$key=$value"
    fi
  done <"$env_file"
}

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

wait_for_gradio() {
  local elapsed=0
  while (( elapsed < STARTUP_TIMEOUT_SEC )); do
    if curl -sf "$GRADIO_URL" >/dev/null 2>&1; then
      return 0
    fi
    if ! is_running; then
      echo "Le processus s'est arrêté pendant le démarrage. Voir : $LATEST_LOG_LINK" >&2
      return 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "Timeout (${STARTUP_TIMEOUT_SEC}s) en attendant Gradio sur $GRADIO_URL" >&2
  echo "Le processus tourne peut‑être encore — vérifiez : $LATEST_LOG_LINK" >&2
  return 1
}

cmd_start() {
  local trace_mode=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --trace) trace_mode=1; shift ;;
      --no-trace) trace_mode=0; shift ;;
      -h|--help) usage; exit 0 ;;
      *) echo "Option inconnue : $1" >&2; usage >&2; exit 1 ;;
    esac
  done

  if [[ -z "$trace_mode" ]]; then
    echo "Choisissez --trace ou --no-trace." >&2
    usage >&2
    exit 1
  fi

  if is_running; then
    echo "Déjà en cours (PID $(cat "$PID_FILE"))."
    echo "UI : $GRADIO_URL"
    exit 1
  fi

  local app_bin
  app_bin="$(resolve_app_bin)"

  mkdir -p "$RUN_DIR" "$LOG_DIR"
  local log_file="$LOG_DIR/session_$(date +%Y%m%d_%H%M%S).log"
  ln -sf "$(basename "$log_file")" "$LATEST_LOG_LINK"

  load_dotenv_exports
  export REACHY_MINI_SKIP_DOTENV=1
  export INTENT_GATE=1
  export TRACE_COLLECT="$trace_mode"

  echo "Démarrage en arrière-plan…"
  echo "  TRACE_COLLECT=$TRACE_COLLECT"
  echo "  INTENT_GATE=$INTENT_GATE"
  echo "  Log : $log_file"

  nohup "$app_bin" --gradio --head-tracker mediapipe --debug >>"$log_file" 2>&1 &
  echo $! >"$PID_FILE"

  if wait_for_gradio; then
    echo ""
    echo "Reachy Conversation App prête."
    echo "  UI   : $GRADIO_URL"
    echo "  PID  : $(cat "$PID_FILE")"
    echo "  Log  : $log_file"
    if [[ "$(uname -s)" == "Darwin" ]]; then
      open "$GRADIO_URL" >/dev/null 2>&1 || true
    fi
  else
    exit 1
  fi
}

cmd_stop() {
  if ! is_running; then
    rm -f "$PID_FILE"
    echo "Aucune instance en cours."
    exit 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  echo "Arret PID ${pid}..."
  kill "${pid}" 2>/dev/null || true
  for _ in $(seq 1 15); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "Arrete."
      return 0
    fi
    sleep 1
  done
  echo "SIGKILL..."
  kill -9 "${pid}" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "Arrete (force)."
}

cmd_status() {
  if is_running; then
    echo "En cours — PID $(cat "$PID_FILE")"
    echo "UI : $GRADIO_URL"
    if [[ -L "$LATEST_LOG_LINK" || -f "$LATEST_LOG_LINK" ]]; then
      echo "Log : $LATEST_LOG_LINK"
    fi
    if curl -sf "$GRADIO_URL" >/dev/null 2>&1; then
      echo "Gradio : OK"
    else
      echo "Gradio : pas encore accessible"
    fi
  else
    rm -f "$PID_FILE"
    echo "Arrêtée."
    exit 1
  fi
}

cmd_logs() {
  local follow=0
  if [[ "${1:-}" == "-f" ]]; then
    follow=1
  fi
  if [[ ! -e "$LATEST_LOG_LINK" ]]; then
    echo "Aucun log trouvé dans $LOG_DIR" >&2
    exit 1
  fi
  if (( follow )); then
    tail -f "$LATEST_LOG_LINK"
  else
    tail -n 80 "$LATEST_LOG_LINK"
  fi
}

main() {
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    start) cmd_start "$@" ;;
    stop) cmd_stop ;;
    status) cmd_status ;;
    logs) cmd_logs "$@" ;;
    ""|-h|--help|help) usage ;;
    *)
      echo "Commande inconnue : $cmd" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
