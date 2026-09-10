#!/usr/bin/env bash
#
# Install the local llamafile runtime plus one tested ntake GGUF model.
#
# Usage:
#   bash scripts/install_local_llm.sh            # Llama 3.1 8B baseline
#   bash scripts/install_local_llm.sh --model qwen  # Qwen2.5 14B A/B candidate
#
# The script downloads 9 GB of model weights over HTTPS into
# ~/.local/share/ntake/llm. It does not start a server or modify the repository.
# It writes ~/.local/share/ntake/llm/run-local-llm.sh, a no-environment-variable
# launcher for the installed model.

set -euo pipefail

LLM_DIR="$HOME/.local/share/ntake/llm"
LLAMAFILE_VERSION="0.10.1"
LLAMAFILE_URL="https://huggingface.co/mozilla-ai/llamafile_0.10/resolve/main/llamafile_0.10.1"
MODEL="llama"

usage() {
  cat <<'EOF'
Usage: bash scripts/install_local_llm.sh [--model llama|qwen] [--help]

Downloads the llamafile 0.10.1 runtime and one external GGUF model into:
  ~/.local/share/ntake/llm

Models:
  llama  Llama 3.1 8B Instruct Q8_0 (baseline, about 8.5 GB)
  qwen   Qwen2.5 14B Instruct Q4_K_M (quality A/B candidate, about 9 GB)

The script is resumable and creates run-local-llm.sh in the install directory.
That launcher starts the selected model on 127.0.0.1:8080 without requiring you
to set environment variables. The installer does not start the server itself.
EOF
}

die() {
  echo "install-local-llm: $*" >&2
  exit 2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --model)
      [ "$#" -ge 2 ] || die "--model requires llama or qwen"
      MODEL="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

case "$MODEL" in
  llama)
    MODEL_FILE="llama-3.1-8b-instruct.Q8_0.gguf"
    MODEL_URL="https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q8_0.gguf"
    MODEL_DESCRIPTION="Llama 3.1 8B Instruct Q8_0"
    ;;
  qwen)
    MODEL_FILE="qwen2.5-14b-instruct-q4_k_m.gguf"
    MODEL_URL="https://huggingface.co/TheRains/Qwen2.5-14B-Instruct-Q4_K_M-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf"
    MODEL_DESCRIPTION="Qwen2.5 14B Instruct Q4_K_M"
    ;;
  *)
    die "Unsupported model: $MODEL (choose llama or qwen)"
    ;;
esac

for command in curl shasum chmod; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done

LLAMAFILE_PATH="$LLM_DIR/llamafile"
MODEL_PATH="$LLM_DIR/$MODEL_FILE"
RUNNER_PATH="$LLM_DIR/run-local-llm.sh"
SOURCES_PATH="$LLM_DIR/SOURCES.txt"

mkdir -p "$LLM_DIR"

download() {
  local url="$1"
  local destination="$2"
  local label="$3"

  echo "Downloading $label to $destination"
  curl --fail --location --proto '=https' --tlsv1.2 --retry 5 --continue-at - \
    --output "$destination" "$url"
}

download "$LLAMAFILE_URL" "$LLAMAFILE_PATH" "llamafile $LLAMAFILE_VERSION"
download "$MODEL_URL" "$MODEL_PATH" "$MODEL_DESCRIPTION"
chmod 755 "$LLAMAFILE_PATH"

{
  printf 'runtime=llamafile %s\n' "$LLAMAFILE_VERSION"
  printf 'runtime_url=%s\n' "$LLAMAFILE_URL"
  printf 'model=%s\n' "$MODEL_DESCRIPTION"
  printf 'model_url=%s\n' "$MODEL_URL"
  shasum -a 256 "$LLAMAFILE_PATH" "$MODEL_PATH"
} > "$SOURCES_PATH"

{
  printf '%s\n' '#!/usr/bin/env bash'
  printf 'exec %q --server --host 127.0.0.1 --port 8080 -m %q "$@"\n' \
    "$LLAMAFILE_PATH" "$MODEL_PATH"
} > "$RUNNER_PATH"
chmod 755 "$RUNNER_PATH"

cat <<EOF

Installed $MODEL_DESCRIPTION.

Source record and local SHA-256 values:
  $SOURCES_PATH

Start the local-only model server (foreground; Ctrl-C stops it):
  $RUNNER_PATH

In a separate terminal, run the repository's disposable live-model UI:
  make ui-demo

For an A/B comparison, stop the server, then run this installer with the other
model choice. The script creates a model-specific launcher each time; previously
downloaded model files remain in $LLM_DIR.
EOF
