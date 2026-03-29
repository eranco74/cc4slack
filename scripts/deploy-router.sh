#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="jira-unfurl-bot--runtime-ext"
IMAGE="quay.io/rh-ee-ovishlit/assisted-bot:latest"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== cc4slack router deployment ==="
echo "Namespace: $NAMESPACE"
echo "Image: $IMAGE"
echo ""

if [ -z "${SLACK_BOT_TOKEN:-}" ] || [ -z "${SLACK_SIGNING_SECRET:-}" ]; then
    echo "ERROR: Set these environment variables before running:"
    echo "  export SLACK_BOT_TOKEN=xoxb-..."
    echo "  export SLACK_SIGNING_SECRET=..."
    exit 1
fi

echo "Step 1: Build and push router image"
podman build -f "$PROJECT_DIR/Dockerfile.router" -t "$IMAGE" "$PROJECT_DIR"
podman push "$IMAGE"

echo ""
echo "Step 2: Switch to namespace"
oc project "$NAMESPACE"

echo ""
echo "Step 3: Deploy Redis (with PVC)"
oc apply -f "$PROJECT_DIR/deploy/01_redis.yaml"
echo "Waiting for Redis..."
oc rollout status deployment/cc4slack-redis --timeout=60s

echo ""
echo "Step 4: Create/update secrets"
REDIS_URL="redis://cc4slack-redis:6379/0"
oc create secret generic cc4slack-secrets \
    --from-literal=slack-bot-token="$SLACK_BOT_TOKEN" \
    --from-literal=slack-signing-secret="$SLACK_SIGNING_SECRET" \
    --from-literal=redis-url="$REDIS_URL" \
    --dry-run=client -o yaml | oc apply -f -

echo ""
echo "Step 5: Deploy router"
oc apply -f "$PROJECT_DIR/deploy/03_deployment.yaml"
oc apply -f "$PROJECT_DIR/deploy/04_service.yaml"
oc apply -f "$PROJECT_DIR/deploy/05_route.yaml"

echo ""
echo "Step 6: Restart router to pick up new image"
oc rollout restart deployment/assisted-bot
echo "Waiting for router..."
oc rollout status deployment/assisted-bot --timeout=60s

echo ""
echo "Step 7: Verify"
oc get pods -l app=cc4slack-redis
oc get pods -l app=assisted-bot
ROUTE=$(oc get route assisted-bot -o jsonpath='{.spec.host}')
echo ""
echo "Router URL: https://$ROUTE"
echo "Agent WebSocket: wss://$ROUTE/ws/agent"
echo ""
echo "=== Deployment complete ==="
