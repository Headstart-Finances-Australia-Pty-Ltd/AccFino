# Setting up OpenFeed (live bank feeds) for AccFino

One-time platform setup by the AccFino administrator. Afterwards every organisation connects its own bank with a single "Connect my bank" button.

## 1. Deploy and configure
1. Copy the updated files, `pip install -r backend/requirements.txt`, rebuild the frontend (`npm run build`).
2. Set environment variables (production):
   - `APP_URL=https://<the address your users sign in at>`  (no trailing slash; must be https and public)
   - `FIELD_ENCRYPTION_KEY=<optional Fernet key>`  (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"). If unset, a key is derived from JWT_SECRET.
3. Restart the backend. It creates the tables `openfeed_flows` and `openfeed_connections` automatically.

## 2. Generate AccFino's keys
Sign in as the AccFino administrator > **Admin Console > API Keys > Open Banking** > OpenFeed card > **Generate keys**.
Copy the public key set (JSON) shown. The private keys stay on the server, encrypted. (Keys made by an older AccFino version have no key id: generate new ones.)

## 3. Register AccFino at OpenFeed
Go to https://app.openfeed.au/registered-apps/new (sign in with your email code). Enter:
- Name / description / website / logo URL: shown to people on the consent screen
- **Requested scopes:** tick only **Banking accounts and transactions** (`openfeed-au:data:banking:read`). Leave Energy unticked.
  `openid` and `offline_access` are NOT tick-boxes: AccFino asks for them automatically at every sign-in.
- **Public key source:** *Paste JWKS JSON* - paste the key set from step 2 (the whole `{ "keys": [...] }` document)
- **Redirect URIs:** nothing to register. OpenFeed's dashboard says redirect URIs are carried inside each sign-in request, and AccFino sends
  `https://<your domain>/open-banking/openfeed/callback` (shown on the AccFino card; it follows `APP_URL`). Use https on a live site.
- Post-logout redirect URI: optional
Press Save. OpenFeed shows two IDs (App ID, and Client ID starting with `app-`).

## 4. Paste the IDs back into AccFino
Same card, step 2:
- OAuth2 Client ID -> the value that starts with `app-`
- App ID -> the plain UUID
Save.

## 5. Test the set-up
Press **Test OpenFeed set-up** on the card. It makes a real request to OpenFeed and shows OpenFeed's own answer, e.g. `invalid_scope` (a scope is not ticked), `invalid_redirect_uri` (the redirect URI differs), or `invalid_client` (the public key pasted at OpenFeed is not the one AccFino signs with). Fix and test again until it says OpenFeed accepted the request.

## 6. Credits
OpenFeed charges you (not the client) about 10 cents per connected organisation per month (introductory). The first 10 credits are free. Top up in the OpenFeed dashboard before you pass 10 connected organisations; if credits run out, feeds pause (organisations see "paused") and recover automatically after a top-up.

## 7. Test with your own organisation
Sign in as an Organisation Admin > Settings > Open Banking > OpenFeed tab > **Connect my bank**. You will: confirm your email at OpenFeed, log in at your bank and approve, tick the accounts to share, and land back in AccFino. Then open Banking & Reconciliation, choose the OpenFeed account and pull a date range.
OpenFeed has no separate test environment (their "Path to production" guide: one live platform), so you test with your own real bank account. Only you are charged a credit; nothing can be paid out of an account.

## 8. Things to know
- Do not regenerate the keys once organisations are connected: their connections are tied to the old keys and every organisation would have to reconnect.
- If you use organisation web addresses (https://<org>.<domain>), people return from OpenFeed to the `APP_URL` address, so they may need to sign in again there.
- Company/trust accounts: the bank may require the person to be a nominated representative for data sharing. Ask OpenFeed which account types they support.
- Banks refresh about every 4 hours (balances about every 15 minutes).

## Troubleshooting: "invalid_client - client authentication failed"
OpenFeed could not verify AccFino's signed request. In order of likelihood:
1. **Old AccFino code on a server in an Australian time zone** signed requests 10-11 hours in the past (fixed in this release). Deploy the update.
2. **The key set at OpenFeed is not the one AccFino signs with.** Admin Console > API Keys > Open Banking > OpenFeed > **Show public key set** shows the current set, its key id (`accfino-xxxxxxxx`) and fingerprint.
   Paste exactly that into the app at OpenFeed (inline JWKS) and save. If you pressed Generate/Replace keys after registering, the set at OpenFeed is out of date.
3. **Wrong Client ID:** it must be the one starting with `app-`, not the plain App ID.
4. **Wrong authentication method:** the app must use `private_key_jwt`.
5. **Server clock out by more than about a minute:** the Test button reports this if it sees it.
Press **Test OpenFeed set-up** after each change; it lists these checks with your actual key id and fingerprint.

## Troubleshooting: "invalid_scope - requested scope is not allowed"
AccFino asks OpenFeed for `openid offline_access openfeed-au:data:banking:read`. **Test OpenFeed set-up** now asks for each scope on its own and shows a tick or cross for each:
- cross on `openfeed-au:data:banking:read` -> in the OpenFeed dashboard tick *Banking accounts and transactions* under Requested scopes and press **Save changes**.
- cross on `openid` / `offline_access` -> these are not boxes in the dashboard; OpenFeed itself is refusing them for this app, so ask OpenFeed (their Discord).

## Path to production (from OpenFeed's own guide - openfeed.au/resources/path-to-production)
- **Stage 1 - build and test:** you start with 10 free credits and up to **5 active user grants across all your apps**. In AccFino one connected organisation = one grant. The 6th organisation to try it sees a "sign-ups limited" screen.
- **Stage 2 - get verified (before onboarding more than 5 organisations):** self-service in the OpenFeed portal (entity type, legal and trading name, ABN/ACN, contact details), then a phone call from Biza - manual during their launch phase. Verification lifts the 5-grant cap and unlocks the public catalogue ("Public listing locked" on your app page means not verified yet).
- **Stage 3 - publish** (optional): one toggle once verified.
- **Stage 4 - Privacy Act duties for AccFino as the receiver of bank data:** a clear privacy policy, collect only what you need, encrypt at rest and in transit, delete on request, never log tokens or account numbers, keep refresh tokens server-side and encrypted (AccFino does).
  **APP 8 (cross-border):** if the database or any processing is outside Australia (a cloud region such as US East), equivalent protections must be in place BEFORE you store bank data there. Check where your production database runs.
- **Grants:** AccFino now sends `grant_management_action=create` for a first connect and `replace` + the existing grant id when an organisation changes the accounts it shares (OpenFeed's recommended usage). If OpenFeed ever refuses that, set `OPENFEED_GRANT_MANAGEMENT=0`; the Test button tells you.

## If the banking scope is refused although it is registered
**Test OpenFeed set-up** checks, in order: signature and Client ID, `openid`, `offline_access`, the banking scope on its own, the redirect address (loopback `127.0.0.1`, `localhost` and an https address), and the grant parameter.
- If only the https address works: run AccFino at https (your live site, or a Cloudflare Tunnel / ngrok to `localhost:8001`, with `APP_URL` set to that https address).
- If every check on AccFino's side passes but the banking scope is still refused, OpenFeed itself is refusing it for this app. Post the Test result (Client ID, which lines are ticks and crosses) in OpenFeed's Discord: discord.gg/jHYEd2MMHk.
- The Test also tries the banking scope with the resource named (`https://api.openfeed.au`) and without `openid`. If the resource variant works it says to set `OPENFEED_SEND_RESOURCE=1` (off by default; when on, AccFino sends it on the sign-in and token requests).

