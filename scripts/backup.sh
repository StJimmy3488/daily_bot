#!/usr/bin/env bash
# Nightly Postgres dump to an S3-compatible bucket (Cloudflare R2 etc.).
# Needs the aws CLI configured with R2 credentials on the host.
# Cron:  15 3 * * *  cd /opt/planner && ./scripts/backup.sh >> backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; source .env; set +a
: "${R2_BUCKET:?set R2_BUCKET in .env}"
: "${R2_ENDPOINT:?set R2_ENDPOINT in .env}"

file="planner-$(date -u +%Y%m%d-%H%M%S).sql.gz"
docker compose exec -T db pg_dump -U planner --clean --if-exists planner | gzip > "/tmp/$file"
aws s3 cp "/tmp/$file" "s3://$R2_BUCKET/backups/$file" --endpoint-url "$R2_ENDPOINT"
rm "/tmp/$file"
echo "$(date -u +%FT%TZ) uploaded $file"
