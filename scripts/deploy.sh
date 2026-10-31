#!/usr/bin/env bash
# Runs on the VPS, piped over SSH by the CI deploy job:
# write the .env rendered from GitHub secrets, pull the freshly built image,
# restart, and wait until the bot reports healthy.
set -euo pipefail
: "${APP_DIR:?}" "${BOT_IMAGE:?}" "${ENV_FILE_B64:?}"
cd "$APP_DIR"

# Replace .env in one step; keep the previous one for a manual rollback.
umask 077
printf '%s' "$ENV_FILE_B64" | base64 -d > .env.new
[ -f .env ] && install -m 600 .env .env.bak
mv .env.new .env

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
