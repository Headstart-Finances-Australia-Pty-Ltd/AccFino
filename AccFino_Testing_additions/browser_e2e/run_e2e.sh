#!/bin/bash
cd /home/claude/AccFino/backend
export DATABASE_URL=postgresql+psycopg2://accfino:accfino@127.0.0.1:5432/accfino_wild JWT_SECRET=$(python3 -c "print('w'*64)") PYTHONPATH=. ADMIN_PASSWORD='Adm1n!Passw0rd#' TENANT_BASE_DOMAIN=syd.accfino.test TENANT_SCHEME=https PROXY_HOPS=0 CONTACT_VERIFICATION=both SMS_OUTBOX_FILE=/tmp/wild/outbox.jsonl ACCFINO_SCHEDULER=0 ACCFINO_NOTIFY_SYNC=1
su postgres -c "psql -q -c 'DROP DATABASE IF EXISTS accfino_wild' -c 'CREATE DATABASE accfino_wild OWNER accfino'" 2>/dev/null
rm -f /tmp/wild/outbox.jsonl
python -c "from db_app.init_db import init_db; init_db()" > /tmp/wild/init.log 2>&1
setsid python -m uvicorn main_app.react_api:app --host 127.0.0.1 --port 443 --ssl-keyfile /tmp/wild/srv.key --ssl-certfile /tmp/wild/srv.pem > /tmp/wild/app.log 2>&1 &
PID=$!
for i in $(seq 1 60); do curl -sk --max-time 2 https://127.0.0.1:443/api/tenant/current >/dev/null 2>&1 && break; sleep 1; done
cd /tmp/pup; "$@"
RC=$?
kill $PID 2>/dev/null
exit $RC
