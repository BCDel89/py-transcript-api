#!/bin/bash
# Deploy py-transcript-api to Coolify
# Usage: ./scripts/deploy-coolify.sh <coolify_app_uuid>
#
# Requires:
#   COOLIFY_TOKEN  — Coolify API token (from Doppler or env)
#   COOLIFY_HOST   — e.g. http://100.85.168.42:8000

set -euo pipefail

APP_UUID="${1:-}"
if [[ -z "$APP_UUID" ]]; then
  echo "Usage: $0 <coolify_app_uuid>" >&2
  exit 1
fi

# Pull from Doppler if not set
if [[ -z "${COOLIFY_TOKEN:-}" ]]; then
  DOPPLER_BIN="${HOME}/.local/bin/doppler"
  DOPPLER="${DOPPLER_BIN:-doppler}"
  COOLIFY_TOKEN="$("$DOPPLER" secrets get COOLIFY_TOKEN --plain --project sage-server --config prd 2>/dev/null || true)"
fi

COOLIFY_HOST="${COOLIFY_HOST:-http://100.85.168.42:8000}"

if [[ -z "${COOLIFY_TOKEN:-}" ]]; then
  echo "Error: COOLIFY_TOKEN not set and not found in Doppler" >&2
  exit 1
fi

echo "Triggering Coolify deploy for app: $APP_UUID"
RESPONSE=$(curl -s -X POST \
  -H "Authorization: Bearer $COOLIFY_TOKEN" \
  -H "Content-Type: application/json" \
  "$COOLIFY_HOST/api/v1/deploy?uuid=$APP_UUID&force=false")

DEPLOY_UUID=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('deployment_uuid',''))" 2>/dev/null || true)

if [[ -z "$DEPLOY_UUID" ]]; then
  echo "Deploy response: $RESPONSE"
  echo "Error: could not parse deployment UUID" >&2
  exit 1
fi

echo "Deploy started: $DEPLOY_UUID"
echo ""
echo "Polling status..."

for i in $(seq 1 30); do
  sleep 5
  STATUS=$(curl -s \
    -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$COOLIFY_HOST/api/v1/deployments/$DEPLOY_UUID" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")

  echo "[$i] $STATUS"

  if [[ "$STATUS" == "finished" ]]; then
    echo "✅ Deploy complete"
    exit 0
  elif [[ "$STATUS" == "failed" || "$STATUS" == "error" ]]; then
    echo "❌ Deploy failed"
    exit 1
  fi
done

echo "⏱ Timed out waiting for deploy"
exit 1
