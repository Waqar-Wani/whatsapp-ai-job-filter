#!/bin/zsh

set -euo pipefail

PROJECT_DIR="/Users/waqar/GitHub/Job Scrapping - Whatsapp"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
MAIN_FILE="$PROJECT_DIR/main.py"
LOG_FILE="$PROJECT_DIR/logs/automation.log"
LOCK_FILE="$PROJECT_DIR/data/.main_cron.lock"

cd "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/data"

# Prevent overlapping runs if a previous execution is still active.
if [[ -f "$LOCK_FILE" ]]; then
  exit 0
fi

trap 'rm -f "$LOCK_FILE"' EXIT
touch "$LOCK_FILE"

{
  echo "$(date '+%Y-%m-%d %H:%M:%S') | INFO | CRON | Starting scheduled main.py run"
  LOG_TO_STDOUT=false "$VENV_PYTHON" "$MAIN_FILE"
  echo "$(date '+%Y-%m-%d %H:%M:%S') | INFO | CRON | Completed scheduled main.py run"
} >> "$LOG_FILE" 2>&1
