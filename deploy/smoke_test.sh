#!/bin/sh
# Post-deploy check:  sh deploy/smoke_test.sh https://your-app.code.run
# Verifies the app is up, the UI and landing page are served, and the new v2.0 routes are mounted (401 = mounted, login required).
BASE="${1:-http://localhost:8001}"; BASE="${BASE%/}"; fail=0
chk() { code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE$1"); if [ "$code" = "$2" ]; then echo "ok   $1 -> $code"; else echo "FAIL $1 -> $code (expected $2)"; fail=1; fi; }
chk /ready 200; chk / 200; chk /login 200; chk /index-marketing.html 200; chk /modules.json 200; chk /public/pricing 200
chk /practice/me 401; chk /practice/bulk/status 401; chk /lending/bulk 401
[ $fail = 0 ] && echo "SMOKE TEST PASSED" || { echo "SMOKE TEST FAILED"; exit 1; }
