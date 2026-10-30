#!/usr/bin/env bash
# Runs on the VPS, piped over SSH by the CI deploy job:
# pull the freshly built image, restart, and wait until the bot reports healthy.
set -euo pipefail
: "${APP_DIR:?}" "${BOT_IMAGE:?}"
cd "$APP_DIR"

if [ -n "${REGISTRY_TOKEN:-}" ]; then
  echo "$REGISTRY_TOKEN" | docker login ghcr.io -u "$REGISTRY_USER" --password-stdin >/dev/null
fi

export BOT_IMAGE
docker compose pull bot
docker compose up -d --remove-orphans

container=$(docker compose ps -q bot)
for _ in $(seq 1 36); do
  status=$(docker inspect --format '{{.State.Health.Status}}' "$container")
  if [ "$status" = "healthy" ]; then
    echo "✅ bot is healthy ($BOT_IMAGE)"
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 5
done

echo "❌ bot did not become healthy in 3 minutes"
docker compose logs --tail 80 bot
exit 1
