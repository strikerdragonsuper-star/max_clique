#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIQUE_ROOT="$(cd "$SCRIPT_DIR/../CliqueAI" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
MINER_NAME="${MINER_NAME:-miner-cliqueAI-sn83}"

if [ -f "$SCRIPT_DIR/miner.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/miner.env"
    set +a
fi

INSTALL_ARGS=(--skip-benchmark)
case "${MODEL_UPGRADE_USE_RUST:-}" in
    1|true|TRUE|yes|YES|on|ON|enabled|ENABLED)
        INSTALL_ARGS+=(--with-rust)
        ;;
esac

echo "Installing/updating miner dependencies..."
"$SCRIPT_DIR/install.sh" "${INSTALL_ARGS[@]}"

if [ ! -d "$CLIQUE_ROOT" ]; then
    echo "CliqueAI repo not found at $CLIQUE_ROOT" >&2
    exit 1
fi

: "${WALLET_NAME:?Set WALLET_NAME in miner.env}"
: "${WALLET_HOTKEY:?Set WALLET_HOTKEY in miner.env}"
: "${AXON_IP:?Set AXON_IP in miner.env}"
: "${AXON_PORT:?Set AXON_PORT in miner.env}"

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

MINER_ARGS=(
    --wallet.name "$WALLET_NAME"
    --wallet.hotkey "$WALLET_HOTKEY"
    --subtensor.network "${SUBTENSOR_NETWORK:-finney}"
    --netuid "${NETUID:-83}"
    --logging.info
    --axon.ip "$AXON_IP"
    --axon.port "$AXON_PORT"
    --blacklist.force_validator_permit
)

if [ -n "${MINER_EXTRA_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    EXTRA=( ${MINER_EXTRA_ARGS} )
    MINER_ARGS+=("${EXTRA[@]}")
fi

if [ "$#" -gt 0 ]; then
    MINER_ARGS+=("$@")
fi

cd "$CLIQUE_ROOT"

if command -v pm2 >/dev/null 2>&1; then
    if pm2 list | grep -q "$MINER_NAME"; then
        pm2 delete "$MINER_NAME" 2>/dev/null || true
    fi
    pm2 start "$VENV_DIR/bin/python" --name "$MINER_NAME" --update-env -- \
        -m model_upgrade.miner \
        "${MINER_ARGS[@]}"
    pm2 save
    echo
    echo "Miner started with PM2 as '$MINER_NAME'"
    echo "  pm2 logs $MINER_NAME"
    echo "  pm2 status"
else
    echo "pm2 not found; running miner in foreground..."
    exec python -m model_upgrade.miner "${MINER_ARGS[@]}"
fi
