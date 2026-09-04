#!/usr/bin/env bash
# Vendor the locally served EventCalendar standalone assets.
#
# Runtime never needs npm: the minified JS/CSS are committed under
# app/static/event-calendar/. This script is only for intentional dependency
# upgrades. Keep VERSION pinned; review the resulting static diff and update
# THIRD_PARTY_NOTICES.md (including the npm shasum) before committing.
#
# Usage: scripts/vendor_event_calendar.sh

set -euo pipefail

VERSION="5.12.2"
PACKAGE="@event-calendar/build@${VERSION}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$REPO_DIR/app/static/event-calendar"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

command -v npm >/dev/null || {
  echo "npm is required only to vendor/update EventCalendar assets." >&2
  exit 1
}

cd "$TMP"
TARBALL="$(npm pack --silent "$PACKAGE")"
tar -xzf "$TARBALL"
mkdir -p "$DEST"
cp package/dist/event-calendar.min.js "$DEST/"
cp package/dist/event-calendar.min.css "$DEST/"

echo "Vendored $PACKAGE assets to $DEST"
echo "Review the diff and update $DEST/THIRD_PARTY_NOTICES.md before committing."
