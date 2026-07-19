#!/bin/sh
# 数据备份：PostgreSQL 全量 pg_dump + MinIO 对象镜像，保留近 30 天（docs/08 §3.2）。
# 用法（生产服务器，建议 cron 每日）：sh scripts/backup.sh
# cron 例：0 3 * * *  cd /opt/youdoo && sh scripts/backup.sh >> /var/log/youdoo-backup.log 2>&1
set -e

BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS="${RETENTION_DAYS:-30}"
# compose 网络名 = <项目名>_default，项目名默认取部署目录名。
# 手册部署在 /opt/youdoo → youdoo_default。若你的目录名不同请用 COMPOSE_NETWORK 覆盖，
# 或先 `docker network ls | grep default` 查实际名。
NETWORK="${COMPOSE_NETWORK:-youdoo_default}"
mkdir -p "$BACKUP_DIR/pg" "$BACKUP_DIR/minio"

# 读取 MinIO 凭证（.env.production）
if [ -f .env.production ]; then
  # shellcheck disable=SC1091
  . ./.env.production
fi

echo "[backup] pg_dump -> $BACKUP_DIR/pg/youdoo_$STAMP.sql.gz"
docker exec youdoo-postgres pg_dump -U postgres youdoo | gzip > "$BACKUP_DIR/pg/youdoo_$STAMP.sql.gz"

echo "[backup] minio mirror -> $BACKUP_DIR/minio"
docker run --rm --network "$NETWORK" \
  -v "$(pwd)/$BACKUP_DIR/minio:/backup" \
  --entrypoint sh minio/mc -c "
    mc alias set src http://minio:9000 '${MINIO_ACCESS_KEY}' '${MINIO_SECRET_KEY}' &&
    mc mirror --overwrite --remove src/${MINIO_BUCKET:-youdoo} /backup
  "

echo "[backup] 清理 ${RETENTION_DAYS} 天前的 pg 备份"
find "$BACKUP_DIR/pg" -name '*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete

echo "[backup] 完成 $STAMP"
