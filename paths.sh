#!/usr/bin/env bash
# Shared paths for Pastor-AI on RunPod (sourced by setup.sh and restart.sh).

WORKSPACE_ROOT="${WORKSPACE_ROOT:-/workspace/pastor-ai}"
REPO_DIR="$WORKSPACE_ROOT/Pastor-AI-Server"
APP_DIR="$REPO_DIR/Pastor-AI-main"
VENV_DIR="$WORKSPACE_ROOT/venv"
QDRANT_DIR="$WORKSPACE_ROOT/qdrant"
LORA_DIR="$WORKSPACE_ROOT/christianai-lora"
LOG_DIR="$WORKSPACE_ROOT/logs"
MARKER_FILE="$WORKSPACE_ROOT/.setup_complete"

export WORKSPACE_ROOT HF_HOME="${HF_HOME:-$WORKSPACE_ROOT/.cache/huggingface}"
export CHRISTIANAI_LORA_DIR="$LORA_DIR"

mkdir -p "$WORKSPACE_ROOT" "$LOG_DIR" "$LORA_DIR" "$QDRANT_DIR/storage" "$HF_HOME"
