#!/usr/bin/env bash
# Commit and push personal data (inbox/, data/, output/, docs/) to the private repo that shares this folder.
set -euo pipefail
cd "$(dirname "$0")/.."
G="git --git-dir=.git-private --work-tree=."
$G add -A
$G add -f -- inbox data output docs vault ':!inbox/**/*.zip' ':!**/*.session' ':!**/*.env' ':!**/__pycache__/**'
$G diff --cached --quiet && { echo "nothing to sync"; exit 0; }
$G commit -q -m "${1:-chore: update personal data snapshot.}"
$G push -q origin main
$G log --oneline -1
