#!/usr/bin/env bash
# Runs on the VPS, piped over SSH by the CI deploy job:
# write the .env rendered from GitHub secrets, pull the freshly built image,
# make the database password match it, restart, and wait until the bot reports healthy.
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

# The Postgres image applies POSTGRES_PASSWORD only when the volume is first created,
# so set it explicitly: GitHub stays the single source of truth and rotating it is just
# editing the secret. psql uses the container's local socket, which needs no password,
# and the statement goes over stdin so the password never appears in argv.
docker compose up -d --wait db
# shellcheck source=/dev/null
db_password=$(. ./.env && printf '%s' "$POSTGRES_PASSWORD")
case "$db_password" in
  "" | *"'"*) echo "❌ POSTGRES_PASSWORD is empty or contains a single quote" >&2; exit 1 ;;
esac
printf "ALTER USER planner PASSWORD '%s';\n" "$db_password" |
  docker compose exec -T db psql -U planner -d planner -v ON_ERROR_STOP=1 -q
unset db_password
echo "database password in sync"

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
