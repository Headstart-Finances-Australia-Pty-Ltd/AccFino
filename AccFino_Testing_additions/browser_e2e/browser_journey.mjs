import chromium from '@sparticuz/chromium'
import puppeteer from 'puppeteer-core'
import fs from 'fs'
const BASE = 'syd.accfino.test', PW = 'Str0ng!Passw0rd#2026'
const results = []; const consoleErrors = []
const check = (name, cond, extra = '') => { results.push(cond); console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond ? '' : '   <-- ' + extra)) }
const sleep = ms => new Promise(r => setTimeout(r, ms))
const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: 'shell',
  args: [...chromium.args.filter(a => !/single-process|no-zygote/.test(a)), '--no-sandbox', '--ignore-certificate-errors', `--host-resolver-rules=MAP *.${BASE} 127.0.0.1, MAP ${BASE} 127.0.0.1`], defaultViewport: { width: 1360, height: 900 } })
async function newSession() {                                  // a fresh browser context = a different person's browser (own cookies / localStorage)
  const ctx = await browser.createBrowserContext(); const page = await ctx.newPage()
  page.on('console', m => { if (m.type() === 'error' && !/favicon|Failed to load resource: the server responded with a status of (401|403|404|422|429)/.test(m.text())) consoleErrors.push(m.text().slice(0, 160)) })
  page.on('response', async r => { if (r.status() === 400 || (r.url().includes('/auth/me/profile'))) console.log('   [net]', r.request().method(), r.url().replace(/https:\/\/[^/]+/, ''), r.status(), (await r.text().catch(() => '')).slice(0, 160)) })
  page.on('pageerror', e => consoleErrors.push('PAGEERROR ' + String(e).slice(0, 160)))
  return page
}
const shot = (page, n) => page.screenshot({ path: `/tmp/wild/shots/${n}.png` })
// visible text WITHOUT css text-transform (labels are upper-cased by the stylesheet, which innerText reports)
const text = page => page.evaluate(() => { const out = []; const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  while (w.nextNode()) { const n = w.currentNode, el = n.parentElement; if (el && el.offsetParent !== null && !/^(SCRIPT|STYLE)$/.test(el.tagName) && n.textContent.trim()) out.push(n.textContent.trim()) }
  return out.join(' ') })
async function clickText(page, label, tag = 'button,a,[role=tab]') {
  const ok = await page.evaluate((label, tag) => {
    const el = [...document.querySelectorAll(tag)].find(e => e.offsetParent !== null && (e.innerText || '').replace(/\s+/g, ' ').trim().toLowerCase().includes(label.toLowerCase()))
    if (!el) return false; el.click(); return true
  }, label, tag)
  if (!ok) throw new Error('no clickable "' + label + '". Page says: ' + (await text(page)).slice(0, 300))
}
async function fill(page, aria, value) {
  const sel = `[aria-label="${aria}"]`
  await page.waitForSelector(sel, { timeout: 8000 })
  await page.$eval(sel, e => { e.focus(); e.select() }); await page.keyboard.press('Backspace'); await page.type(sel, value)
}
async function waitText(page, t, ms = 10000) { try { await page.waitForFunction(x => document.body.innerText.toLowerCase().includes(x.toLowerCase()), { timeout: ms }, t) } catch (e) { await shot(page, 'FAILED-waiting-for-' + t.replace(/\W+/g, '_')); throw new Error('waiting for "' + t + '"; page shows: ' + (await text(page)).slice(0, 500)) } }
function outboxCode(channel, to) {
  for (let i = 0; i < 30; i++) {
    const rows = fs.existsSync('/tmp/wild/outbox.jsonl') ? fs.readFileSync('/tmp/wild/outbox.jsonl', 'utf8').trim().split('\n').filter(Boolean).map(l => JSON.parse(l)) : []
    const hit = rows.filter(r => r.channel === channel && r.to === to).pop()
    if (hit) return hit.body.match(/code is (\d{6})/)[1]
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 300)
  }
  throw new Error('no ' + channel + ' code for ' + to)
}
async function verifyContact(page, channel, word, label, dest) {
  const box = `[data-testid="verify-${channel}"]`
  await page.waitForSelector(box)
  await page.evaluate(b => [...document.querySelector(b).querySelectorAll('button')].find(x => /Send code/.test(x.innerText)).click(), box)
  await page.waitForSelector(`[aria-label="${label} verification code"]`)
  await fill(page, `${label} verification code`, outboxCode(channel === 'email' ? 'email' : 'sms', dest))
  await page.evaluate(b => [...document.querySelector(b).querySelectorAll('button')].find(x => x.innerText.trim() === 'Verify').click(), box)
  await page.waitForFunction(b => /verified/.test(document.querySelector(b).innerText), { timeout: 8000 }, box)
}
async function accountForm(page, { first, last, email, phone, e164 }) {
  await fill(page, 'First Name', first); await fill(page, 'Last Name', last); await fill(page, 'Email Address', email); await fill(page, 'Phone Number', phone)
  await fill(page, 'Password', PW); await fill(page, 'Confirm Password', PW)
}
async function signIn(page, host, email) {
  await page.goto(`https://${host}/login`, { waitUntil: 'networkidle2' })
  await page.waitForSelector('input[type=password]')
  const u = await page.$('input[type=text]'); await u.click({ clickCount: 3 }); await u.type(email)
  await page.type('input[type=password]', PW); await page.keyboard.press('Enter')
  await page.waitForFunction(() => !location.pathname.startsWith('/login'), { timeout: 15000 })
  await sleep(1500)
}

// ============================================================================ 1. Sign up: create the Kutumb organisation
const admin = await newSession()
await admin.goto(`https://${BASE}/login`, { waitUntil: 'networkidle2' })
await shot(admin, '01-login')
check('login page loads over HTTPS on the apex address', (await text(admin)).length > 50)
await clickText(admin, 'start free'); await sleep(500)
check('the choice screen explains the Organisation Admin role', /Organisation Admin/.test(await text(admin)))
await clickText(admin, 'Create a New Organisation'); await sleep(500)
await fill(admin, 'Organisation name', 'Kutumb'); await fill(admin, 'ABN', '51 824 753 556'); await fill(admin, 'Address', '1 George St'); await fill(admin, 'City or suburb', 'Sydney')
await shot(admin, '02-org-details')
await clickText(admin, 'Continue'); await waitText(admin, 'First Name')
check('the proposed organisation address is shown at sign-up', /kutumb\.syd\.accfino\.test/.test(await text(admin)), (await text(admin)).slice(0, 400))
const t = await text(admin)
for (const l of ['First Name *', 'Last Name *', 'Email Address *', 'Phone Number *', 'Password *', 'Confirm Password *']) check(`form shows "${l}"`, t.includes(l))
await accountForm(admin, { first: 'Olive', last: 'Owner', email: 'olive@kutumb.example', phone: '0412 345 678' })
await clickText(admin, 'Create Account'); await sleep(600)
check('Create Account is refused until email AND phone are verified', /Please verify your email address\./.test(await text(admin)) && /Please verify your phone number\./.test(await text(admin)))
await shot(admin, '03-must-verify')
await verifyContact(admin, 'email', 'email address', 'Email', 'olive@kutumb.example')
await verifyContact(admin, 'phone', 'phone number', 'Phone', '+61412345678')
await shot(admin, '04-verified')
check('once verified, the "please verify" errors are gone', !/Please verify your (email address|phone number)\./.test(await text(admin)) && !/Please correct the highlighted fields/.test(await text(admin)), (await text(admin)).slice(0, 300))
await clickText(admin, 'Create Account'); await waitText(admin, 'Kutumb is ready')
const done = await text(admin)
check('the confirmation shows the organisation address https://kutumb.syd.accfino.test', done.includes('https://kutumb.syd.accfino.test'), done.slice(0, 300))
await shot(admin, '05-created')

// ============================================================================ 2. The Organisation Admin signs in at the organisation's OWN address
await clickText(admin, 'Go to Kutumb'); await admin.waitForFunction(() => location.hostname.startsWith('kutumb.'), { timeout: 10000 })
check('the "Go to Kutumb and sign in" button takes the person to https://kutumb.syd.accfino.test/login', admin.url().startsWith('https://kutumb.syd.accfino.test/login'), admin.url())
await admin.waitForSelector('input[type=password]'); await sleep(500)
check('the sign-in page greets the organisation by name', /Sign in to Kutumb/.test(await text(admin)), (await text(admin)).slice(0, 200))
await signIn(admin, 'kutumb.syd.accfino.test', 'olive@kutumb.example')
await shot(admin, '06-admin-home')
let nav = await text(admin)
check('admin sidebar shows the organisation name and its web address', /Kutumb/.test(nav) && /kutumb\.syd\.accfino\.test/.test(nav), nav.slice(0, 300))
check('admin sees Settings', await admin.evaluate(() => [...document.querySelectorAll('a')].some(a => a.getAttribute('href') === '/settings')))
check('admin sees My Account', await admin.evaluate(() => [...document.querySelectorAll('a')].some(a => a.getAttribute('href') === '/my-account')))

// Settings tabs (admin)
await admin.goto('https://kutumb.syd.accfino.test/settings/setup', { waitUntil: 'networkidle2' }); await sleep(1500)
let s = await text(admin); await shot(admin, '07-settings-admin')
for (const tab of ['Business Setup', 'IAM Setup', 'Open Banking', 'Integrations', 'Payment Setup']) check(`admin sees the Settings tab "${tab}"`, s.includes(tab))
for (const tab of ['Organisation', 'Knowledge Base']) check(`admin sees "${tab}" in Business Setup`, s.includes(tab))
await clickText(admin, 'Organisation', '[role=tab],.tab-btn,button'); await sleep(2000)
s = await text(admin); await shot(admin, '08-organisation-admin')
check('Organisation page: Organisation Admin and primary contact card with the address', /Organisation Admin and primary contact/.test(s) && s.includes('olive@kutumb.example') && s.includes('0412 345 678') && s.includes('https://kutumb.syd.accfino.test'), s.slice(0, 600))
check('Organisation page: the admin dashboard (users / access codes) is shown', /Licensed users/.test(s) && /Pending invitations/.test(s) && /Available slots/.test(s))
check('Organisation page: the member list shows the Organisation Admin badge', await admin.evaluate(() => !!document.querySelector('[data-testid="admin-badge"]')))
// generate an access code THROUGH THE UI
await admin.evaluate(() => { const b = [...document.querySelectorAll('button')].find(x => x.innerText.trim() === 'Generate'); b.scrollIntoView(); })
const roleOpts = await admin.evaluate(() => [...document.querySelector('[aria-label="Role"]').options].map(o => o.value))
check('the access-code role list has no admin/owner', JSON.stringify(roleOpts) === JSON.stringify(['bookkeeper', 'accountant', 'payroll', 'readonly']), JSON.stringify(roleOpts))
await clickText(admin, 'Generate', 'button'); await admin.waitForSelector('[data-testid="fresh-codes"]', { timeout: 8000 })
const freshText = await admin.evaluate(() => document.querySelector('[data-testid="fresh-codes"]').innerText)
const code = freshText.match(/[A-Z]{3}-[A-Z0-9]{4}-[A-Z0-9]{4}/)[0]
await shot(admin, '09-code-generated')
check('an access code was generated on screen', /^[A-Z]{3}-/.test(code), code)

// ============================================================================ 3. A bookkeeper joins by code, in a different browser, at the organisation address
const bob = await newSession()
await bob.goto('https://kutumb.syd.accfino.test/login', { waitUntil: 'networkidle2' }); await bob.waitForSelector('input[type=password]')
await clickText(bob, 'start free'); await sleep(800)
check('on the Kutumb address the join screen is fixed to Kutumb (no organisation search)', /Join Kutumb/.test(await text(bob)) && !(await bob.$('[aria-label="Organisation name"]')), (await text(bob)).slice(0, 300))
await fill(bob, 'Organisation access code', 'WRONG-CODE-1'); await clickText(bob, 'Verify & Continue'); await sleep(1200)
check('a wrong code is refused with a generic message', /not valid|expired/.test(await text(bob)))
await fill(bob, 'Organisation access code', code); console.log('   typed code:', code, '| input now holds:', await bob.$eval('[aria-label="Organisation access code"]', e => e.value), '| fresh-codes text was:', JSON.stringify(freshText)); await clickText(bob, 'Verify & Continue'); await waitText(bob, 'Joining')
check('after the code: "Joining Kutumb as Bookkeeper"', /Joining Kutumb as Bookkeeper/.test(await text(bob)), (await text(bob)).slice(0, 300))
await accountForm(bob, { first: 'Bob', last: 'Book', email: 'bob@kutumb.example', phone: '0498 765 432' })
await fill(bob, 'Phone Number', '12345'); await clickText(bob, 'Create Account'); await sleep(500)
check('an invalid phone number is explained', /Please enter a valid phone number\./.test(await text(bob)))
await fill(bob, 'Phone Number', '0498 765 432'); await fill(bob, 'Email Address', 'not-an-email'); await clickText(bob, 'Create Account'); await sleep(500)
check('an invalid email is explained', /Please enter a valid email address\./.test(await text(bob)))
await fill(bob, 'Email Address', 'bob@kutumb.example')
await verifyContact(bob, 'email', 'email address', 'Email', 'bob@kutumb.example'); await verifyContact(bob, 'phone', 'phone number', 'Phone', '+61498765432')
await shot(bob, '10-join-verified')
await clickText(bob, 'Create Account'); await waitText(bob, 'Welcome to Kutumb')
check('joined: "Welcome to Kutumb"', true); await shot(bob, '11-joined')
await signIn(bob, 'kutumb.syd.accfino.test', 'bob@kutumb.example')
await shot(bob, '12-bob-home'); nav = await text(bob)
const addrBox = await bob.evaluate(() => { const e = document.querySelector('[data-testid="org-address"]'); if (!e) return null; const r = e.getBoundingClientRect(); const a = e.querySelector('a'); const lum = c => { const m = (c.match(/\d+/g) || [0,0,0]).map(Number); return 0.2126*m[0] + 0.7152*m[1] + 0.0722*m[2] }; return { text: e.innerText.replace(/\s+/g, ' '), top: r.top, bottom: r.bottom, vh: innerHeight, linkLum: a ? lum(getComputedStyle(a).color) : 0 } })
check('the sidebar shows "Kutumb" and its web address, fully inside the visible window', !!addrBox && /Kutumb/.test(addrBox.text) && /kutumb\.syd\.accfino\.test/.test(addrBox.text) && addrBox.top >= 0 && addrBox.bottom <= addrBox.vh && addrBox.linkLum > 150, JSON.stringify(addrBox))   // (light text on the dark sidebar)
check('bookkeeper is signed in at the Kutumb address and sees the organisation name and address', /Kutumb/.test(nav) && /kutumb\.syd\.accfino\.test/.test(nav), nav.slice(0, 300))
check('bookkeeper does NOT see Settings in the menu', !(await bob.evaluate(() => [...document.querySelectorAll('a')].some(a => (a.getAttribute('href') || '').startsWith('/settings')))))
check('bookkeeper sees My Account', await bob.evaluate(() => [...document.querySelectorAll('a')].some(a => a.getAttribute('href') === '/my-account')))
check('bookkeeper does not see the word "Settings" as a menu entry', !/\bSettings\b\s*\n?\s*Organisation/.test(nav))
for (const path of ['/settings', '/settings/setup', '/settings/iam', '/settings/api-webhooks', '/settings/open-banking', '/settings/organisation', '/setup', '/organisation', '/identity']) {
  await bob.goto('https://kutumb.syd.accfino.test' + path, { waitUntil: 'networkidle2' }); await sleep(1200)
  const p = new URL(bob.url()).pathname; const body = await text(bob)
  check(`bookkeeper typing ${path} lands on My Account, not Settings`, p === '/my-account' && !/Payment Setup|IAM Setup|Knowledge Base/.test(body), p)
}
await shot(bob, '13-bob-my-account')
const acct = await text(bob)
check('My Account shows the organisation, role and sign-in address', /Your organisation/.test(acct) && /Bookkeeper/.test(acct) && /https:\/\/kutumb\.syd\.accfino\.test/.test(acct), acct.slice(0, 500))
check('My Account shows verified email and phone', /Email verified/.test(acct) && /Phone verified/.test(acct), acct.slice(0, 700))
await fill(bob, 'Phone number *', ''); await clickText(bob, 'Save details'); await sleep(600)
check('blanking the phone number in My Account is refused with the specified message', /Phone number is required\./.test(await text(bob)))
await fill(bob, 'Phone number *', '0498 765 432'); await fill(bob, 'Full name *', 'Bobby Book'); await clickText(bob, 'Save details'); await sleep(1500)
console.log('   profile card says:', await bob.evaluate(() => (document.querySelector('[data-testid="profile-card"]')||{innerText:'(no card)'}).innerText.replace(/\s+/g,' ').slice(0, 500)), '| toasts:', await bob.evaluate(() => [...document.querySelectorAll('[role=status]')].map(e => e.innerText).join('|'))); await shot(bob, '13b-after-save')
check('a plain name change saves', /Profile saved/.test(await text(bob)) || (await bob.evaluate(() => document.querySelector('[aria-label="Full name *"]').value)) === 'Bobby Book')
// the real server refuses the same person's API calls made from the browser's own session
const api = await bob.evaluate(async () => {
  const u = JSON.parse(localStorage.getItem('af_user')); const h = { Authorization: 'Bearer ' + u.token, 'Content-Type': 'application/json' }
  const out = {}
  for (const [k, m, p, b] of [['invites', 'GET', '/api/org/current/invites'], ['members', 'GET', '/api/org/current/members'], ['rename', 'PATCH', '/api/org/current', { name: 'Hacked' }], ['stripe', 'GET', '/api/stripe/status'], ['kbwrite', 'PUT', '/api/kb/meta', {}], ['kbread', 'GET', '/api/kb']])
    out[k] = (await fetch(p, { method: m, headers: h, body: b ? JSON.stringify(b) : undefined })).status
  return out
})
check('the browser session of a bookkeeper gets 403 from the API for admin settings, 200 for reading the knowledge base', api.invites === 403 && api.members === 403 && api.rename === 403 && api.stripe === 403 && api.kbwrite === 403 && api.kbread === 200, JSON.stringify(api))

// ============================================================================ 4. Admin: second look, and the member now appears
await admin.goto('https://kutumb.syd.accfino.test/settings/setup', { waitUntil: 'networkidle2' }); await sleep(1000)
await clickText(admin, 'Organisation', '[role=tab],.tab-btn,button'); await sleep(2000)
const s2 = await text(admin); await shot(admin, '14-organisation-after-join')
check('admin now sees both people, with email and phone, and the bookkeeper has a role picker', s2.includes('bob@kutumb.example') && s2.includes('0498 765 432'))
check('admin sees Transfer admin', /Transfer admin/.test(s2))
for (const tab of ['IAM Setup', 'Payment Setup']) { await clickText(admin, tab, '[role=tab],.tab-btn,a'); await sleep(1500); check(`admin can open ${tab}`, !/not allowed|Only the Organisation Admin/.test(await text(admin))) }
await shot(admin, '15-payment-setup-admin')

console.log('\nconsole errors seen in the browser:', consoleErrors.length); consoleErrors.slice(0, 8).forEach(e => console.log('  ' + e))
console.log(`\n${results.filter(Boolean).length} passed, ${results.filter(x => !x).length} failed`)
await browser.close(); process.exit(results.every(Boolean) ? 0 : 1)
