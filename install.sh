#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIQUE_ROOT="$(cd "$PROJECT_ROOT/../CliqueAI" && pwd)"
VENV_DIR="$PROJECT_ROOT/venv"
RUN_BENCHMARK=0

for arg in "$@"; do
    case "$arg" in
        --skip-benchmark) RUN_BENCHMARK=0 ;;
        --with-benchmark) RUN_BENCHMARK=1 ;;
    esac
done

echo "Installing model-upgrade miner stack for subnet 83..."
echo "Project root: $PROJECT_ROOT"
echo "CliqueAI root: $CLIQUE_ROOT"

if [ ! -d "$CLIQUE_ROOT" ]; then
    echo "CliqueAI repo not found at $CLIQUE_ROOT" >&2
    echo "Clone it beside model-upgrade:" >&2
    echo "  git clone https://github.com/toptensor/CliqueAI.git ../CliqueAI" >&2
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
pip install -e "$CLIQUE_ROOT"
pip install -e "$PROJECT_ROOT"

echo
echo "Install complete."
echo "  venv: $VENV_DIR"
echo "  activate: source venv/bin/activate"

if [ "$RUN_BENCHMARK" -eq 1 ]; then
    echo
    echo "Running benchmark..."
    python "$PROJECT_ROOT/scripts/benchmark.py"
fi
