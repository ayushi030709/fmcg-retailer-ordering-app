#!/usr/bin/env bash
# Rebuild submission/Technical_Design_Document.pdf from docs/TDD.md.
# Needs: pandoc (3.x) and Node with Playwright + Chromium (`npm i -g playwright && npx playwright install chromium`).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
mkdir -p "$ROOT/submission"
cd "$ROOT/docs"
pandoc TDD.md -s -f markdown -t html5 --resource-path=. --embed-resources \
  --css=pdf/print.css --metadata pagetitle="Technical Design Document" -o "$TMP/tdd.html"
node pdf/render-pdf.cjs "$TMP/tdd.html" "$ROOT/submission/Technical_Design_Document.pdf"
echo "Wrote $ROOT/submission/Technical_Design_Document.pdf"
