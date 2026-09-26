#!/usr/bin/env bash
# .github/scripts/marketplace-payload.sh
#
# Reads NAME, DESC, REPO, VERSION, TAG (required) and CHANGELOG (optional)
# from the environment and prints the marketplace `client_payload` JSON on
# stdout, built entirely with `jq -n --arg` so every value round-trips
# byte-for-byte regardless of quotes, backticks, `$(...)`, backslashes,
# tabs or newlines. The `changelog` key is added only when CHANGELOG is a
# non-empty string; it is omitted entirely otherwise.
set -eo pipefail

# Git bash on Windows rewrites a leading-`/` argument into a Windows path
# before handing it to a native (non-MSYS) executable such as jq.exe. A
# changelog that legitimately starts with `/` (e.g. quoting a Unix path)
# must reach jq unrewritten.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

: "${NAME:?NAME is required}"
: "${DESC:?DESC is required}"
: "${REPO:?REPO is required}"
: "${VERSION:?VERSION is required}"
: "${TAG:?TAG is required}"

ICON="https://raw.githubusercontent.com/${REPO}/${TAG}/assets/icon.png"
DESCRIPTION_URL="https://raw.githubusercontent.com/${REPO}/${TAG}/description.md"

if [ -n "${CHANGELOG:-}" ]; then
  jq -n \
    --arg name "$NAME" \
    --arg description "$DESC" \
    --arg repo "$REPO" \
    --arg version "$VERSION" \
    --arg ref "$TAG" \
    --arg icon "$ICON" \
    --arg description_url "$DESCRIPTION_URL" \
    --arg changelog "$CHANGELOG" \
    '{
      event_type: "plugin-release",
      client_payload: {
        name: $name,
        description: $description,
        repo: $repo,
        category: "mcp",
        version: $version,
        ref: $ref,
        icon: $icon,
        description_url: $description_url,
        tags: ["visual", "environment"],
        changelog: $changelog
      }
    }'
else
  jq -n \
    --arg name "$NAME" \
    --arg description "$DESC" \
    --arg repo "$REPO" \
    --arg version "$VERSION" \
    --arg ref "$TAG" \
    --arg icon "$ICON" \
    --arg description_url "$DESCRIPTION_URL" \
    '{
      event_type: "plugin-release",
      client_payload: {
        name: $name,
        description: $description,
        repo: $repo,
        category: "mcp",
        version: $version,
        ref: $ref,
        icon: $icon,
        description_url: $description_url,
        tags: ["visual", "environment"]
      }
    }'
fi
