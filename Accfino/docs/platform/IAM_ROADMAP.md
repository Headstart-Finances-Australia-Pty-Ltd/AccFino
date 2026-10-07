# Identity & Access Management - Microsoft Entra ID parity map

Target: capabilities comparable to Microsoft Entra ID (formerly Azure AD) for an accounting SaaS.
Status as at Phase 0 rev 3 (Sep 2026) - IAM steps 1 and 2 complete.

| Entra capability | AccFino status | Plan |
|---|---|---|
| Username/password with lockout & smart throttling | ✅ Done | - |
| MFA: Authenticator app (TOTP) | ✅ Done | - |
| MFA: Passkeys / Windows Hello / FIDO2 (face, fingerprint) | ✅ Done | - |
| Passwordless sign-in (passkey) | ✅ Done | - |
| MFA: SMS / email one-time codes | ✅ Done | Voice call: not planned |
| Authentication methods policy (which methods are allowed) | ✅ Per-organisation (Conditional Access "accepted methods") + env-level | - |
| Self-service password reset | ✅ Existing (email link) | Require MFA before reset - IAM step 2 |
| Sign-in logs & audit logs | ✅ Done (append-only) | Export/stream to SIEM - IAM step 4 |
| Session management / revoke sessions | ✅ Per-device sessions (user + admin revoke), sign-in frequency | Token refresh / "keep me signed in" - IAM step 3 |
| Role-based access control (org roles) | ✅ 6 roles | Custom roles & granular permissions - IAM step 3 |
| Groups | ❌ | Security groups within an organisation - IAM step 3 |
| Admin user management (disable, reset MFA, force sign-out) | ✅ Disable/enable, sign out everywhere, reset MFA, unlock, require password change, devices, sign-in history | Bulk actions, CSV export - IAM step 3 |
| Conditional Access (require MFA, IP/country rules, device, risk) | ✅ Per-org: require MFA, accepted methods, IP allow-list, sign-in frequency, scope (all / admins), report-only, lock-out protection | Country rules (GeoIP), device compliance, multiple named policies - IAM step 4 |
| Identity Protection (risky sign-ins: new country, impossible travel) | ❌ | Risk scoring on sign-in + alerts - IAM step 4 |
| SSO / federation: sign in with Microsoft Entra ID, Google (OIDC) | ❌ | OIDC federation per organisation - **IAM step 3** |
| SAML 2.0 enterprise SSO | ❌ | IAM step 4 |
| SCIM user provisioning / de-provisioning | ❌ | SCIM 2.0 endpoint - IAM step 4 |
| Privileged Identity Management (just-in-time admin) | ❌ | Time-bound role elevation with approval - IAM step 5 |
| Access reviews | ❌ | Periodic member/role recertification - IAM step 5 |
| B2B guest access (external accountant) | ◐ Add existing user to org | Invitations by email, guest expiry - IAM step 3 |
| App registrations / API access (OAuth clients, API keys) | ❌ | OAuth2 client credentials for the public API (roadmap M22) - IAM step 5 |

**IAM step 2** ✅ done: admin user management, per-organisation Conditional Access & accepted-method policies,
device sessions with per-session revoke, forced password change, trusted client IP (anti-spoofing).
**IAM step 2 remaining item:** MFA before self-service password reset - moved to step 3.
**IAM step 3**: groups, custom roles, invitations/guests, Sign in with Microsoft / Google (OIDC).
**IAM step 4**: identity protection (risk-based sign-in), SAML, SCIM, SIEM export.
**IAM step 5**: PIM, access reviews, OAuth app registrations.
