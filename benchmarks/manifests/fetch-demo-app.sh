#!/usr/bin/env bash
# Fetch a benchmark demo app pinned by its manifest into a gitignored .demo-apps/ dir.
# These apps are intentionally NOT vendored in the tree (large third-party repos).
#
#   bash benchmarks/manifests/fetch-demo-app.sh [manifest.json] [dest-dir]
#
set -euo pipefail
MANIFEST="${1:-benchmarks/manifests/super-productivity.json}"
name=$(python3 -c "import json;print(json.load(open('$MANIFEST'))['name'])")
url=$(python3 -c "import json;print(json.load(open('$MANIFEST'))['upstream'])")
ref=$(python3 -c "import json;print(json.load(open('$MANIFEST'))['pinned_version'])")
DEST="${2:-.demo-apps/$name}"
if [ -d "$DEST" ]; then echo "already present: $DEST"; exit 0; fi
echo ">> cloning $name ($url @ $ref) -> $DEST"
git clone --depth 1 --branch "$ref" "$url" "$DEST"
echo ">> done: $DEST (build per the app's own README before running the demo scripts)"
