# AccFino UI: simpler, calmer, still complete

Status: **proposal for approval** (nothing in the running UI has changed yet).

## 1. What users face today (measured from `frontend/src/core/config/modules.json`)
| | |
|---|---|
| Registry entries | **65** across 7 domains |
| Working, user-facing features | **21** (15 live + 6 beta) |
| "Planned" placeholders shown as tabs/links | **29** (45% of everything on screen is not built) |
| Admin / platform settings listed as "modules" under business domains | **15** (10 of the 16 entries under "Lending, Credit & Treasury" are Groq keys, S3, email, calendly...) |
| Accounting hub alone | 9 live tabs + 5 bank-feed/admin entries |
| Top-level destinations in the side panel | 7 domains + Overview + Settings + Admin + My Account |

The product is not too big - the *presentation* mixes what users do daily, what administrators set up once, and what is not built yet.

## 2. What the research says
* **Keep primary navigation to about seven items** and use role-aware menus that *hide* irrelevant sections rather than disabling them; B2B products tend to grow sidebars of 20+ items "half of which most users never touch" ([Attract Group](https://attractgroup.com/blog/best-practices-to-design-a-saas-product-saas-application-design-guide.md)). Sidebars suit 5-20 sections with grouping; top bars suit 3-7; large apps combine them (top bar for global context, sidebar for primary navigation) ([SaaSUI](https://www.saasui.design/blog/saas-navigation-ux-patterns)).
* **Progressive disclosure**: show the essentials first and reveal the rest on demand; it improves learnability, efficiency and error rate. Caveat: hidden things frustrate when users know a feature exists but cannot find it ([The Decision Lab](https://thedecisionlab.com/reference-guide/design/progressive-disclosure)) - so every hidden item must stay reachable by search.
* **Command palette (Ctrl/Cmd+K)** scales the opposite way to a menu: every added feature makes it more useful; show recents before typing ([DEV Community](https://dev.to/thekitbase/cmdk-is-the-new-hamburger-menu-why-command-palettes-are-taking-over-saas-81d)). Task-based IA: organise around user jobs, not system capabilities or departments; let users pin frequent items; test with 5-8 users per role and revise if critical-task success is below ~70% ([GeekyAnts](https://customer-experience.geekyants.com/book/it_services/chapter_24.md)).
* **Xero** (the closest peer) separated *Business* (daily) from *Accounting* (advanced) menus, added Favourites (star any report/tool), an organisation menu, "/" search and a "+" quick-create, and centralised settings ([summary](https://www.alphapartners.co/blog/xero-product-update-new-xero-feature-navigation-simplifies-everyday-tasks)). Its later homepage widgets drew "busy and cluttered" feedback ([Xero ideas](https://productideas.xero.com/forums/966063/suggestions/50098983?page=20)).
* **QuickBooks** simplified menu drew a backlash: a sub-menu sliding over the main menu was called an anti-pattern, and users were told to switch to *Accountant view* for the full layout ([QuickBooks community](https://quickbooks.intuit.com/community/other-questions-9/how-do-we-go-back-to-the-old-sidebar-80740)). Lesson: never change silently, avoid overlay sub-menus, always keep a path to the full view.

## 3. Design principles for AccFino
1. **Task first, not module first.** Home answers "what needs me today?"
2. **Calm by default, complete on demand.** Seven primary destinations; everything else one search away.
3. **Hide, don't lock.** Unlicensed or role-irrelevant items disappear from menus (shown once, on the Plan page).
4. **Separate three audiences**: daily users, accountants (advanced), administrators (set-up once).
5. **Only what exists.** Planned modules leave navigation; one "What's coming" page holds the roadmap.
6. **One primary action per screen**, <= 5 tabs, summary before detail.
7. **Never surprise.** Opt-in rollout, a "Simple / Full" switch, no overlay sub-menus.

## 4. Proposed information architecture (all modules kept)
| New primary item | Contains (existing modules) | Replaces domain |
|---|---|---|
| **Home** | Today: checklist, needs-attention, 4 numbers, quick actions | Overview + Dashboard |
| **Sales & Purchases** | Sales, Purchases, Expenses | part of Accounting |
| **Banking** | Reconciliation, bank feeds (connect/pull), bank rules | part of Accounting + Open Banking |
| **Accounting** | General ledger, journals, Fixed assets, Inventory, Financial reports | Books & Accounting |
| **Payroll** | Employees, Timesheets, Pay runs, Payslips, STP | Payroll & Workforce |
| **Tax & Wealth** | Tax returns, CGT, Shares/ETFs, Crypto | Taxation + Assets & Investments |
| **Lending & Planning** | Statement analysis (lending), Cash-flow forecast | Lending + Planning |

Not in the primary menu: **Practice** (all planned - appears only for practice plans), **Settings** (organisation menu, top-left), **My account / Security / Sign out** (avatar menu), **Admin Console** (platform administrators only, in the avatar menu). The 15 provider/platform entries move out of the registry's business domains into one **Admin > Integrations** page.

Role defaults (roles already exist: owner, admin, accountant, bookkeeper, payroll, readonly): owners see *Simple* menu order; accountants/bookkeepers default to *Full* (ledger, journals, tax first); payroll role lands on Payroll; readonly sees reports only. Users can pin items and switch Simple/Full at any time.

## 5. Components to add (small, reusable)
| Component | Behaviour |
|---|---|
| **Command palette** (Ctrl/Cmd+K, "/") | pages, actions ("New invoice", "Reconcile", "Run payroll"), recent records; recents shown before typing; every module reachable |
| **+ New** menu | invoice, bill, expense, journal, contact, pay run - by role |
| **Organisation menu** (top-left) | switch organisation, Settings, Plan & billing |
| **Favourites / pins** | star any page; pinned items on top of the sidebar |
| **Today home** | setup checklist until complete; needs-attention list (unreconciled lines, overdue invoices, pay run due, BAS due); max 4 KPI tiles; no ads or upsell banners |
| **Domain page template** | title, primary action, <= 5 tabs, "More" overflow for the rest; summary first, "Advanced" accordions (e.g. repeating journals, FX, AI tools) |
| **Guided flows** | wizard for bank connect, CSV import, first pay run, organisation set-up |
| **Empty states** | say what the page is for and offer the next step |

## 6. Registry changes (data, not code)
`modules.json` v6 adds: `group` (new primary item), `audience` (`everyday` | `advanced` | `admin`), `roles`, `keywords` (for search), `featured` (shown in Home quick actions); `status: planned` entries are excluded from user navigation (still listed in Admin > Modules). Layout, hubs, Home and the landing page keep reading the same file, so all stay in step.

## 7. Rollout and validation
1. **Tree test** the new IA (5-8 users per role: owner, bookkeeper, accountant, payroll officer): 10 tasks ("find where to reconcile", "add an employee", "see CGT for shares"). Target >= 80% first-click success; revise below 70%.
2. Ship behind a user preference **"New navigation (beta)"**; old layout stays until metrics beat it.
3. Measure: time to first reconciliation, clicks to common tasks, command-palette use, support tickets about "where is X".
4. Phase 1 (low risk, no layout change): registry cleanup (hide planned, move admin items), Ctrl+K palette, + New. Phase 2: new sidebar + Today home. Phase 3: pins, Simple/Full, guided flows.

## 8. Accessibility and quality bar
Keyboard operable everywhere (palette, menus, tabs); `<nav aria-label>` and `aria-current="page"`; breadcrumbs above the title in deep pages; WCAG 2.2 AA contrast; focus management in dialogs; no content that exists only on hover.
