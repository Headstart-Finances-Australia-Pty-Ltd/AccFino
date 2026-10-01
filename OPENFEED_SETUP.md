# Setting up OpenFeed (live bank feeds) for AccFino

One-time platform setup by the AccFino administrator. Afterwards every organisation connects its own bank with a single "Connect my bank" button.

## 1. Deploy and configure
1. Copy the updated files, `pip install -r backend/requirements.txt`, rebuild the frontend (`npm run build`).
2. Set environment variables (production):
   - `APP_URL=https://<the address your users sign in at>`  (no trailing slash; must be https and public)
   - `FIELD_ENCRYPTION_KEY=<optional Fernet key>`  (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"). If unset, a key is derived from JWT_SECRET.
3. Restart the backend. It creates the tables `openfeed_flows` and `openfeed_connections` automatically.

## 2. Generate AccFino's keys
Sign in as the AccFino administrator > **Admin Console > Open Banking** > OpenFeed card > **Generate keys**.
Copy the public key set (JSON) shown. The private keys stay on the server, encrypted.

## 3. Register AccFino at OpenFeed
Go to https://app.openfeed.au/registered-apps/new (sign in with your email code) and enter:
- Name / description: shown to people on the consent screen (e.g. "AccFino - accounting and bank reconciliation")
- Website URL: your public site
- Auth method: `private_key_jwt`
- App public key: paste the JSON from step 2 (inline JWKS)
- Scopes: `openfeed-au:data:banking:read` (add `openfeed-au:grant:self:revoke` so AccFino can withdraw access when an organisation disconnects)
- Post-logout redirect URI: `https://<your domain>/`  (trailing slash required)
No redirect URI is registered - OpenFeed takes it from each request.
Submit. OpenFeed shows two IDs.

## 4. Paste the IDs back into AccFino
Same Admin Console > Open Banking screen, step 2 of the OpenFeed card:
- OAuth2 Client ID -> the value that starts with `app-`
- App ID -> the plain UUID
Save. The panel should now say "Ready".

## 5. Credits
OpenFeed charges you (not the client) about 10 cents per connected organisation per month (introductory). The first 10 credits are free. Top up in the OpenFeed dashboard before you pass 10 connected organisations; if credits run out, feeds pause (organisations see "paused") and recover automatically after a top-up.

## 6. Test with your own organisation
Sign in as an Organisation Admin > Settings > Open Banking > OpenFeed tab > **Connect my bank**. You will: confirm your email at OpenFeed, log in at your bank and approve, tick the accounts to share, and land back in AccFino. Then open Banking & Reconciliation, choose the OpenFeed account and pull a date range.
If OpenFeed offers a sandbox, point AccFino at it first with `OPENFEED_ISSUER`, `OPENFEED_API_BASE` and `OPENFEED_CONSENT_BASE` (take the values from OpenFeed's docs).

## 7. Things to know
- Do not regenerate the keys once organisations are connected: their connections are tied to the old keys and every organisation would have to reconnect.
- If you use organisation web addresses (https://<org>.<domain>), people return from OpenFeed to the `APP_URL` address, so they may need to sign in again there.
- Company/trust accounts: the bank may require the person to be a nominated representative for data sharing. Ask OpenFeed which account types they support.
- Banks refresh about every 4 hours (balances about every 15 minutes).
