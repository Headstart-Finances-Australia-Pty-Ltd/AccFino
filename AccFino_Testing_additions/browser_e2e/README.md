# End-to-end tests against the REAL running app (organisation addresses + a real browser)

These start the actual backend over HTTPS on port 443 with `TENANT_BASE_DOMAIN=syd.accfino.test`, a throwaway wildcard certificate, and a clean PostgreSQL database
(`accfino_wild`, created and dropped by the script). They are NOT part of `pytest`/`vitest`; run them by hand when you change sign-up, tenancy, settings access or the sign-in pages.

| File | What it proves |
|---|---|
| `wildcard_api_e2e.py` | 38 checks over HTTPS by sub-domain: addresses, wildcard certificate coverage (one label only), verification codes, sign-in at the organisation address, isolation between organisations, admin-only API calls |
| `browser_journey.mjs` | 58 checks in headless Chrome with real clicks and typing: sign-up with email + phone verification, sign-in at `https://kutumb.syd.accfino.test`, Settings as admin, generating and using an access code, a bookkeeper's view (no Settings, redirected from every settings URL, 403 from the API), My Account, sidebar address visibility and contrast |

## Run
```bash
# once: PostgreSQL running with a superuser accfino/accfino; frontend built (cd frontend && npm ci && npx vite build)
./make_test_certs.sh
# browser dependencies (a Chromium that ships inside an npm package, handy where browser downloads are blocked):
mkdir -p /tmp/pup && cd /tmp/pup && npm i @sparticuz/chromium puppeteer-core && cd -
cp wildcard_api_e2e.py /tmp/wild/e2e.py ; cp browser_journey.mjs /tmp/pup/journey.mjs ; cp run_e2e.sh /tmp/wild/run.sh
/tmp/wild/run.sh python /tmp/wild/e2e.py            # API journey
/tmp/wild/run.sh node /tmp/pup/journey.mjs          # browser journey (screenshots in /tmp/wild/shots)
```
`run.sh` resets the database, starts the app, waits until it answers, runs the command you give it, then stops the app. Verification codes are read from the development outbox file (`SMS_OUTBOX_FILE`).

## What these do NOT cover
Your real public DNS, a certificate from a real authority, your reverse proxy / Cloudflare (header handling), real SMTP / SMS delivery, other browsers or phones.
