#!/usr/bin/env bash
# setup-config.sh — scaffold the out-of-repo family config + show env setup.
#
# The real family config holds household PII, so it lives OUTSIDE this (public)
# repo. This copies the committed example to the config dir (without clobbering
# an existing one) and prints the environment variables the app needs.
#
# Usage:  ./setup-config.sh
# Then edit the printed config path with your household + members, and export
# the two variables (add them to your shell profile to persist).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE="$REPO_DIR/family.example.toml"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ntake"
CONFIG_FILE="$CONFIG_DIR/family.toml"

if [[ ! -f "$EXAMPLE" ]]; then
  echo "error: $EXAMPLE not found (run from the repo root)." >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR"

if [[ -f "$CONFIG_FILE" ]]; then
  echo "Config already exists (not overwriting): $CONFIG_FILE"
else
  cp "$EXAMPLE" "$CONFIG_FILE"
  echo "Created $CONFIG_FILE from the example. Edit it with your household."
fi

# A per-install secret for hashing device tokens. Generate one if absent.
SECRET_HINT="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))' 2>/dev/null || echo 'run: python3 -c \"import secrets;print(secrets.token_urlsafe(32))\"')"

cat <<EOF

Next steps:
  1. Edit your household + members:
       \$EDITOR "$CONFIG_FILE"

  2. Export these in your shell (add to ~/.bashrc / ~/.zshrc to persist):
       export NTAKE_CONFIG="$CONFIG_FILE"
       export NTAKE_TOKEN_SECRET="$SECRET_HINT"

     (NTAKE_TOKEN_SECRET must stay constant — changing it invalidates all
     existing device tokens. Keep it secret; do not commit it.)

  3. Enroll a device (prints the token once):
       python -m app.manage gen-token "Adult One" --label "Pixel phone"

The real config and the token secret are never committed (see .gitignore).
EOF
