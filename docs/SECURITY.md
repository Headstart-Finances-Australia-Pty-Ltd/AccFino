# Security & sign-in

## Sign-in methods (users choose one or more under Settings → Security)
| Method | What the user does | Strength | Notes |
|---|---|---|---|
| **Face or fingerprint (passkey)** | Face ID, Touch ID, Windows Hello, Android face/fingerprint, or a security key | Strongest, phishing-resistant | WebAuthn/FIDO2 with user verification required. Biometrics stay on the device; AccFino stores only a public key. Can also be used **instead of a password** ("Sign in with face or fingerprint"). |
| **Authenticator app passcode** | 6-digit code from Microsoft/Google Authenticator, 1Password, Authy | Strong | TOTP (RFC 6238). |
| **Code sent to phone (SMS)** | 6-digit code by text message | Moderate (SIM-swap risk) | AU and NZ mobiles by default (`SMS_ALLOWED_COUNTRY_CODES`). |
| **Email code** | 6-digit code by email | Moderate | Good backup method. |
| **Recovery codes** | One of 8 single-use codes | Backup only | Issued with the first method; can be regenerated. |

Codes: 6 digits, hashed at rest, expire in 5 minutes, 5 attempts, 30-second resend cooldown, 6 per hour.

## Identity administration (IAM step 2)
- **Your devices** (Security page): every sign-in is a session with device, IP, methods used and last activity; sign out
  any one device or all others. Logout ends only the current device.
- **Identity** (Admin → Platform Users, AccFino super admins): search users; disable/enable (signs out everywhere, blocks sign-in - the
  reason is audited); sign out everywhere; reset MFA (lost phone); unlock; require password change at next sign-in;
  end individual sessions; view organisations, methods and sign-in history.
- **Access policy** (Organisation page, owners/admins) - Conditional Access for the organisation:
  require two-step verification, accepted methods (e.g. passkey + authenticator only, no SMS), allowed networks
  (IP/CIDR), require signing in again after N hours, scope (all members or owners/admins only).
  States: Off, **Report only** (logs `ca.report_only`, doesn't block), On. An enforced policy that would block the
  person saving it is refused (lock-out protection). Platform administrators are exempt (break-glass).
- Users who are blocked are sent to the Security page with the reason, and can always reach it to fix the problem.

- **Organisation Identity** (Settings → Identity, organisation owners/admins): member status, MFA, last sign-in;
  suspend/restore access to the organisation; for home members also sign-out, reset MFA, require password change.

## Client IP addresses behind proxies
`PROXY_HOPS` = number of reverse proxies in front of AccFino that append to `X-Forwarded-For`
(Northflank only: `1`; Cloudflare + Northflank: `2`; exposed directly: `0`). Only the address added by your own
proxy is trusted, so clients can't fake their IP to get around login throttling or IP allow-lists.

## Configuration
```
# Passkeys - pin to your production domain
WEBAUTHN_RP_ID=accfino.com.au
WEBAUTHN_ORIGINS=https://app.accfino.com.au
# SMS
SMS_PROVIDER=messagemedia            # or twilio; "console" = development only (logs codes)
MESSAGEMEDIA_API_KEY=...  MESSAGEMEDIA_API_SECRET=...
# TWILIO_ACCOUNT_SID=...  TWILIO_AUTH_TOKEN=...  TWILIO_FROM=+61...
# Email codes (same as password reset)
SMTP_HOST=...  SMTP_PORT=587  SMTP_USER=...  SMTP_PASSWORD=...  FROM_EMAIL=no-reply@accfino.com.au
# Policy
MFA_ENFORCED=true                    # every user must enrol at least one method
PROXY_HOPS=1                         # see above
SESSION_CACHE_SECONDS=15             # how quickly revocations/policy changes apply on each worker
```
Passkeys require HTTPS in production (browsers allow http://localhost for development).
The admin checklist (Security page, admin only) flags any of these that are missing.

## Secrets
Never commit secrets. Local development reads `.env` (see `.env.example`); production uses Northflank secrets.
**Action required:** the previous `app.cmd` contained the production Neon password and is in the public git
history - rotate the Neon password.
