#!/bin/sh
# AI Calendar — Postgres → Yandex Object Storage backup script.
#
# Designed to run inside a tiny alpine container that has both `pg_dump`
# (postgresql-client) and `aws-cli`. See docker-compose.prod.yml → `backup`
# service for the cron sidecar.
#
# What it does:
#   1. pg_dump --format=custom of $POSTGRES_DB to /tmp.
#   2. gzip + sha256 the dump.
#   3. Upload to s3://$BACKUP_BUCKET/postgres/YYYY/MM/DD/<file>.dump.gz
#   4. Delete dumps in the bucket older than $BACKUP_RETAIN_DAYS days.
#   5. Log to stdout (docker logs catches it).
#
# Required env (all come from .env.prod):
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST, POSTGRES_PORT
#   BACKUP_BUCKET, BACKUP_S3_ENDPOINT, BACKUP_S3_REGION
#   BACKUP_S3_ACCESS_KEY, BACKUP_S3_SECRET_KEY
#   BACKUP_RETAIN_DAYS (default: 14)

set -eu

: "${POSTGRES_USER:?missing}"
: "${POSTGRES_PASSWORD:?missing}"
: "${POSTGRES_DB:?missing}"
: "${POSTGRES_HOST:?missing}"
: "${BACKUP_BUCKET:?missing}"
: "${BACKUP_S3_ENDPOINT:?missing}"
: "${BACKUP_S3_ACCESS_KEY:?missing}"
: "${BACKUP_S3_SECRET_KEY:?missing}"
: "${BACKUP_RETAIN_DAYS:=14}"

export AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_KEY"
export AWS_DEFAULT_REGION="${BACKUP_S3_REGION:-ru-central1}"
export PGPASSWORD="$POSTGRES_PASSWORD"

NOW=$(date -u +"%Y-%m-%dT%H-%M-%SZ")
YEAR=$(date -u +%Y)
MONTH=$(date -u +%m)
DAY=$(date -u +%d)

FILE="ai_calendar-${NOW}.dump.gz"
LOCAL="/tmp/${FILE}"
REMOTE="s3://${BACKUP_BUCKET}/postgres/${YEAR}/${MONTH}/${DAY}/${FILE}"

echo "[backup] $(date -u) starting → ${REMOTE}"

pg_dump \
  --host="$POSTGRES_HOST" \
  --port="${POSTGRES_PORT:-5432}" \
  --username="$POSTGRES_USER" \
  --dbname="$POSTGRES_DB" \
  --format=custom \
  --no-owner \
  --no-acl \
  | gzip -9 > "$LOCAL"

SIZE=$(wc -c < "$LOCAL")
echo "[backup] dump size: $SIZE bytes"

aws --endpoint-url="$BACKUP_S3_ENDPOINT" s3 cp "$LOCAL" "$REMOTE" --no-progress

rm -f "$LOCAL"
echo "[backup] uploaded ok"

# --- Retention: delete dumps older than $BACKUP_RETAIN_DAYS days. ---
CUTOFF=$(date -u -d "${BACKUP_RETAIN_DAYS} days ago" +%Y-%m-%d 2>/dev/null \
       || date -u -v -"${BACKUP_RETAIN_DAYS}d" +%Y-%m-%d)
echo "[backup] retention: deleting < ${CUTOFF}"

aws --endpoint-url="$BACKUP_S3_ENDPOINT" s3 ls "s3://${BACKUP_BUCKET}/postgres/" --recursive \
  | awk -v cutoff="$CUTOFF" '$1 < cutoff { print $4 }' \
  | while read -r key; do
      [ -z "$key" ] && continue
      echo "[backup]   delete: $key"
      aws --endpoint-url="$BACKUP_S3_ENDPOINT" s3 rm "s3://${BACKUP_BUCKET}/${key}" --quiet
    done

echo "[backup] done"
