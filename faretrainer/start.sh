#!/usr/bin/env bash
# 培训沙箱一键启动（开发模式）：
#   1. 检查/启动本机 PostgreSQL（默认 /tmp:55432）
#   2. migrate + seed（虚构数据）
#   3. 构建前端到 frontend/dist
#   4. 启动 Django 于 :8000，同时托管 API 与 Vue 页面
#
# 仅培训用途：不连接任何真实订座/出票/支付系统。
set -euo pipefail

cd "$(dirname "$0")"

export PGHOST="${PGHOST:-/tmp}"
export PGPORT="${PGPORT:-55432}"
export PGUSER="${PGUSER:-fareuser}"
export PGDBNAME="${PGDBNAME:-farebook}"
PGHOME="${PGHOME:-$HOME/opt/pgsql}"
PGDATA="${PGDATA:-$HOME/pgdata}"

if [ -x "$PGHOME/bin/pg_ctl" ] && [ ! -S "$PGHOST/.s.PGSQL.$PGPORT" ]; then
  echo "[start] 初始化并启动 PostgreSQL ($PGHOME)"
  [ -d "$PGDATA" ] || "$PGHOME/bin/initdb" -D "$PGDATA" -U "$PGUSER" \
      --auth=trust --locale=C -E UTF8 >/dev/null
  "$PGHOME/bin/pg_ctl" -D "$PGDATA" -l "$PGDATA/server.log" \
      -o "-p $PGPORT -k $PGHOST" start >/dev/null
  sleep 2
fi

python3 - <<'PY'
import os, psycopg2
try:
    conn = psycopg2.connect(host=os.environ['PGHOST'], port=os.environ['PGPORT'],
                            user=os.environ['PGUSER'], dbname=os.environ['PGDBNAME'])
except psycopg2.OperationalError:
    admin = psycopg2.connect(host=os.environ['PGHOST'], port=os.environ['PGPORT'],
                             user=os.environ['PGUSER'], dbname='postgres')
    admin.autocommit = True
    admin.cursor().execute(
        f"CREATE DATABASE {os.environ['PGDBNAME']} ENCODING 'UTF8'")
    print('[start] 数据库已创建')
PY

python3 manage.py migrate
python3 manage.py seed

if [ ! -d frontend/dist ]; then
  echo '[start] 构建前端'
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

echo '[start] Django: http://127.0.0.1:8000/  （API 前缀 /api/）'
exec python3 manage.py runserver 0.0.0.0:8000
