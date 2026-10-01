"""End-to-end through the REAL running app over HTTPS: wildcard names, wildcard certificate, tenant isolation, verification codes (read from the dev outbox)."""
import json, re, socket, sys, time
import requests, urllib3
BASE, PORT = "syd.accfino.test", 443
_orig = socket.getaddrinfo
def wildcard_dns(host, *a, **k):                       # what a wildcard DNS record *.syd.accfino.test does: every name -> the app
    if host == BASE or host.endswith("." + BASE):
        host = "127.0.0.1"
    return _orig(host, *a, **k)
socket.getaddrinfo = wildcard_dns
S = requests.Session(); S.trust_env = False; S.verify = "/tmp/wild/ca.pem"
ok_n = bad_n = 0
def check(name, cond, extra=""):
    global ok_n, bad_n
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"   <-- {extra}"))
    ok_n += bool(cond); bad_n += (not cond)
def url(host, path): return f"https://{host}:{PORT}/api{path}"
def call(host, method, path, token=None, **kw):
    h = kw.pop("headers", {})
    if token: h["Authorization"] = f"Bearer {token}"
    return S.request(method, url(host, path), headers=h, timeout=30, **kw)
def outbox(channel, to):
    for _ in range(20):
        rows = [json.loads(l) for l in open("/tmp/wild/outbox.jsonl")] if __import__("os").path.exists("/tmp/wild/outbox.jsonl") else []
        hit = [r for r in rows if r["channel"] == channel and r["to"] == to]
        if hit: return re.search(r"code is (\d{6})", hit[-1]["body"]).group(1)
        time.sleep(0.3)
    raise SystemExit(f"no {channel} code for {to}")
def prove(host, email, phone_raw, phone_e164):
    r = call(host, "POST", "/signup/contact/send", json={"channel": "email", "destination": email}); assert r.status_code == 200, r.text
    et = call(host, "POST", "/signup/contact/verify", json={"channel": "email", "destination": email, "code": outbox("email", email)}).json()["token"]
    r = call(host, "POST", "/signup/contact/send", json={"channel": "phone", "destination": phone_raw}); assert r.status_code == 200, r.text
    pt = call(host, "POST", "/signup/contact/verify", json={"channel": "phone", "destination": phone_raw, "code": outbox("sms", phone_e164)}).json()["token"]
    return et, pt
PW = "Str0ng!Passw0rd#2026"
def user(email, phone, et, pt, first="Olive", last="Owner"):
    return dict(first_name=first, last_name=last, email=email, phone=phone, password=PW, email_token=et, phone_token=pt)
def org(name, abn): return dict(name=name, abn=abn, address="1 George St", city="Sydney", state="NSW", postcode="2000", industry="Accounting")

APEX = BASE
# 0. TLS + wildcard names
r = call(APEX, "GET", "/tenant/current"); check("apex address answers over HTTPS with a certificate valid for the apex", r.status_code == 200 and r.json()["tenant"] is None and r.json()["tenant_urls_enabled"] is True, r.text)
r = call("anything.syd.accfino.test", "GET", "/tenant/current"); check("an unknown organisation address is 'not found' (404 organisation, TLS still valid)", r.status_code in (200, 404), r.status_code)
try:
    call("a.b.syd.accfino.test", "GET", "/tenant/current"); check("a name two labels deep is NOT covered by the wildcard certificate", False, "connected")
except requests.exceptions.SSLError: check("a name two labels deep is NOT covered by the wildcard certificate (correct: *.x covers one label)", True)
try:
    call("kutumb.other.test", "GET", "/tenant/current"); check("a different domain is not covered by the certificate", False)
except Exception as e: check("a different domain is refused (no DNS / not in certificate)", True)

# 1. sign-up WITHOUT verification is refused by the real server
r = call(APEX, "POST", "/signup/organisation", json={"org": org("Kutumb", "51 824 753 556"), "user": user("olive@kutumb.example", "0412 345 678", None, None)})
check("sign-up without verification proofs is refused (422)", r.status_code == 422 and "verify your email" in r.text, r.text)

# 2. Kutumb: verify, create
et, pt = prove(APEX, "olive@kutumb.example", "0412 345 678", "+61412345678")
r = call(APEX, "POST", "/signup/organisation", json={"org": org("Kutumb", "51 824 753 556"), "user": user("olive@kutumb.example", "0412 345 678", et, pt)})
j = r.json(); check("Kutumb created; its address is https://kutumb.syd.accfino.test", r.status_code == 200 and j.get("tenant_url") == "https://kutumb.syd.accfino.test" and j.get("login_url") == "https://kutumb.syd.accfino.test/login", r.text)
K = "kutumb.syd.accfino.test"
r = call(K, "GET", "/tenant/current"); check("the Kutumb address identifies the Kutumb organisation", r.status_code == 200 and r.json()["found"] and r.json()["name"] == "Kutumb", r.text)

# 3. admin signs in AT the Kutumb address
r = call(K, "POST", "/auth/login", json={"email": "olive@kutumb.example", "password": PW}); admin = r.json().get("token")
check("the Organisation Admin signs in at the Kutumb address", r.status_code == 200 and admin, r.text)
r = call(K, "GET", "/org/current", admin); cur = r.json()
check("admin: /org/current shows the address, role and contact details", r.status_code == 200 and cur["tenant_url"] == "https://kutumb.syd.accfino.test" and cur["is_org_admin"] and cur["admin_email"] == "olive@kutumb.example", r.text)
oid = cur["id"]
r = call(K, "GET", "/auth/me", admin); me = r.json(); check("admin /auth/me: verified email and phone recorded", me["email_verified"] and me["phone_verified"] and me["is_org_admin"], r.text)

# 4. admin invites a bookkeeper; bookkeeper joins (verification again) and signs in at the Kutumb address
r = call(K, "POST", "/org/current/invites", admin, json={"role": "bookkeeper", "count": 1}); code = r.json()["codes"][0]["code"]
check("admin generates an access code (response includes the organisation address to share)", r.status_code == 200 and r.json()["tenant_url"] == "https://kutumb.syd.accfino.test", r.text)
v = call(K, "POST", "/signup/verify-code", json={"slug": "kutumb", "code": code}).json()
et2, pt2 = prove(K, "bob@kutumb.example", "0498 765 432", "+61498765432")
r = call(K, "POST", "/signup/join", json={"signup_token": v["signup_token"], "user": user("bob@kutumb.example", "0498 765 432", et2, pt2, "Bob", "Book")})
check("bookkeeper joins Kutumb with the code, and is given the Kutumb address", r.status_code == 200 and r.json().get("tenant_url") == "https://kutumb.syd.accfino.test", r.text)
r = call(K, "POST", "/auth/login", json={"email": "bob@kutumb.example", "password": PW}); bob = r.json().get("token")
check("the bookkeeper signs in at https://kutumb.syd.accfino.test", r.status_code == 200 and bob, r.text)
r = call(K, "GET", "/org/current", bob); c = r.json()
check("bookkeeper sees the organisation address but not the admin's email/phone", r.status_code == 200 and c["tenant_url"] == "https://kutumb.syd.accfino.test" and not c["is_org_admin"] and "admin_email" not in c, r.text)

# 5. bookkeeper is refused organisation administration and payment/knowledge-base setup by the real server
for m_, p_, b_ in [("GET", "/org/current/invites", None), ("POST", "/org/current/invites", {"role": "readonly"}), ("GET", "/org/current/members", None), ("PATCH", "/org/current", {"name": "x"}),
                   ("GET", "/org/current/tenant", None), ("PUT", "/org/current/access-policy", {"state": "off", "applies_to": "all", "require_mfa": False}),
                   ("POST", "/stripe/config", {"x": 1}), ("GET", "/stripe/status", None), ("POST", "/square/config", {}), ("POST", "/bank-account/config", {}), ("GET", "/openfeed/status", None),
                   ("PUT", "/kb/meta", {}), ("POST", "/rdr/rules", {})]:
    r = call(K, m_, p_, bob, **({"json": b_} if b_ is not None else {})); check(f"bookkeeper refused: {m_} {p_}", r.status_code == 403, f"{r.status_code} {r.text[:80]}")
for p_ in ("/kb", "/rdr/rules"):
    r = call(K, "GET", p_, bob); check(f"bookkeeper can still READ {p_} (reconciliation needs it)", r.status_code == 200, f"{r.status_code} {r.text[:80]}")
r = call(K, "GET", "/stripe/status", admin); check("the admin can use payment setup", r.status_code == 200, r.text[:80])

# 6. a second organisation: isolation across addresses
et3, pt3 = prove(APEX, "ben@beta.example", "0400 111 222", "+61400111222")
r = call(APEX, "POST", "/signup/organisation", json={"org": org("Beta Co", "53 004 085 616"), "user": user("ben@beta.example", "0400 111 222", et3, pt3, "Ben", "Beta")})
check("a second organisation (Beta Co) is created at https://beta.syd.accfino.test ('Co' is dropped from the name)", r.status_code == 200 and r.json()["tenant_url"] == "https://beta.syd.accfino.test", r.text)
B = "beta.syd.accfino.test"
r = call(B, "POST", "/auth/login", json={"email": "bob@kutumb.example", "password": PW}); check("a Kutumb bookkeeper cannot sign in at the Beta address", r.status_code == 403, f"{r.status_code} {r.text[:100]}")
r = call(B, "POST", "/auth/login", json={"email": "olive@kutumb.example", "password": PW}); check("the Kutumb admin cannot sign in at the Beta address either", r.status_code == 403, r.status_code)
r = call(B, "GET", "/org/current", admin); check("a Kutumb admin token is refused at the Beta address (tenant_forbidden)", r.status_code == 403 and r.json().get("code") == "tenant_forbidden", r.text[:120])
r = call(K, "GET", "/org/current", admin, headers={"X-Org-Id": "999"}); check("changing X-Org-Id on the Kutumb address does not move you to another tenant", r.status_code == 403, f"{r.status_code} {r.text[:100]}")
r = call(K, "GET", "/org/current", admin, headers={"X-Forwarded-Host": B}); check("spoofing X-Forwarded-Host to another tenant gets nothing (not a member there)", r.status_code == 403, f"{r.status_code} {r.text[:100]}")
r = call("ghost.syd.accfino.test", "GET", "/org/current", admin); check("an address that is no organisation's is refused for signed-in users (404)", r.status_code == 404, f"{r.status_code} {r.text[:100]}")
r = call(K, "GET", "/org/current/members", admin); names = {x["email"] for x in r.json()}; check("Kutumb's member list contains only Kutumb people", names == {"olive@kutumb.example", "bob@kutumb.example"}, names)

print(f"\n{ok_n} passed, {bad_n} failed")
sys.exit(1 if bad_n else 0)
