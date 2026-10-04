#!/bin/bash
# Run LLM worker with dynamic Windows host IP for Ollama.
#
# Usage: ./scripts/run-llm-worker.sh

set -e

cd "$(dirname "$0")/../apps/llm-worker"

# Get Windows host IP from WSL
WINDOWS_IP=$(ip route | grep default | awk '{print $3}')

if [ -z "$WINDOWS_IP" ]; then
    echo "ERROR: cannot determine Windows host IP"
    exit 1
fi

export OLLAMA_ENDPOINT="http://${WINDOWS_IP}:11434"

echo "Windows host IP: $WINDOWS_IP"
echo "Ollama endpoint: $OLLAMA_ENDPOINT"

# Verify Ollama reachable
if ! curl -s --max-time 3 "${OLLAMA_ENDPOINT}/api/tags" > /dev/null; then
    echo ""
    echo "ERROR: Ollama is not reachable at $OLLAMA_ENDPOINT"
    echo ""
    echo "Make sure:"
    echo "  1. Ollama is running on Windows"
    echo "  2. OLLAMA_HOST=0.0.0.0:11434 is set (allows connections from WSL)"
    echo "  3. Windows Firewall allows port 11434"
    exit 1
fi

echo "Ollama OK"
echo ""

# Run worker
exec uv run python -m llm_worker.main