# Organisation web addresses (https://kutumb-accounting.accfino.com)

AccFino already understands these addresses: it reads the organisation name from the web address, shows that organisation's sign-in, and blocks anyone who is not a member.
What AccFino cannot do for you is the platform side (DNS, certificate, routing). It needs four things. **Admin Console > API Keys > Web Addresses > "Check my set-up"** tests each one and tells you which is missing.

## 1. Choose the base domain
`TENANT_BASE_DOMAIN=accfino.com` gives `kutumb-accounting.accfino.com` (the ERPNext style). The names `www`, `app`, `api`, `admin`, `mail`, `login`, `signup`, `support` and a few others are reserved, so
`www.accfino.com` (your marketing site) and any address you already use keep working. If you prefer to keep organisations apart from your main domain, use a sub-domain such as `app.accfino.com`
(addresses then look like `kutumb-accounting.app.accfino.com`) and replace `accfino.com` below with it.

## 2. Server setting
On the AccFino service (Northflank > accfino-app > Environment) add:
```
TENANT_BASE_DOMAIN=accfino.com
TENANT_SCHEME=https
```
and restart. (Every organisation already has a name for its address; the Organisation page shows it as soon as this is set.)

## 3. Wildcard DNS and wildcard certificate (Northflank)
From Northflank's documentation ("Wildcard domains and certificates"). Screen names can differ slightly; the idea is the same:
1. **Domains > accfino.com** (it is already added if www.accfino.com works): open the domain's settings.
2. **Certificate generation: "Wildcard via DCV".** Northflank shows a CNAME for `_acme-challenge` - add it at your DNS provider. After it verifies, every new sub-domain shares one wildcard certificate.
   (Alternative: import your own `*.accfino.com` certificate and key.)
3. **Add a wildcard sub-domain `*`** (this means `*.accfino.com`) and **link it to the AccFino service port** (the HTTP port, 8001). Northflank shows the DNS record to add.
4. At your DNS provider add the wildcard record Northflank gave you: a **CNAME** named `*` pointing at the value shown. Your existing `www` record stays as it is (an explicit record always wins over a wildcard).
5. **Cloudflare:** if your DNS is on Cloudflare, set the `*` record and the `_acme-challenge` record to **DNS only** (grey cloud). Proxying a wildcard record is generally limited to higher plans and would also hide the certificate Northflank issues.

## 4. Check
Open Admin Console > API Keys > **Web Addresses** > **Check my set-up**. Fix the first step with a cross, press the button again, repeat until all four are ticks:
1. Setting - TENANT_BASE_DOMAIN is set.
2. Wildcard DNS - a made-up name under the domain resolves.
3. Wildcard certificate - that address answers over HTTPS with a certificate browsers trust.
4. Routing - the answer is AccFino, and it read the organisation name from the address.

Then open `https://<organisation>.accfino.com` in a browser: the organisation's sign-in appears.

## Things to know
* **Each address keeps its own sign-in.** Someone signed in at `www.accfino.com` signs in once more at `kutumb-accounting.accfino.com` (browsers keep sign-ins per address). This is the same as separate ERPNext sites.
* **Unknown names** (`nothing.accfino.com`) show "This organisation address does not exist" - no organisation is revealed.
* A person who is not a member of the organisation cannot use its address, whatever they type (the server checks it on every request). Platform administrators can enter any address.
* **Bank connection and card payments** keep returning to the one main address (`APP_URL`); the pop-up window reports back to whichever address you started from.
* **Local testing without DNS:** `TENANT_BASE_DOMAIN=localhost:8001`, `TENANT_SCHEME=http`, build the frontend (`npm run build`) and open `http://kutumb-accounting.localhost:8001` (browsers resolve `*.localhost` to your own computer).
