// Module registry helpers. src/config/modules.json is the single source of truth for the
// side panel, the in-app Home page and the public landing page (served as /modules.json).
import registry from '../config/modules.json'

export const REGISTRY = registry
export const STATUS_LABEL = registry.statuses
export const DOMAINS = [...registry.domains].sort((a, b) => a.order - b.order)
export const MODULES = registry.modules

// Presentation-only groups: several registry modules shown as ONE entry (Home tiles, side-panel list). The member modules keep their own ids,
// plan locks and visibility switches (Admin > Modules, Pricing), so nothing about plans or the backend changes. A group is visible while ANY member is.
// `after` is the module the group is listed behind; the members are removed from the list and replaced by the group.
export const MODULE_GROUPS = [
  { id: 'assets-costs', domain: 'accounting', after: 'reconciliation', name: 'Assets and Costs', status: 'live', nav: true, route: '/accounting', tab: 'assets-costs', emoji: '🏗',
    sub: 'Expenses · Inventory · Fixed Assets', blurb: 'Expense claims and receipts, stock and cost of goods sold, and the fixed asset register with depreciation',
    members: ['expenses', 'inventory-trading', 'fixed-assets'] },
  { id: 'taxes', domain: 'tax_compliance', after: 'tax-returns', name: 'Taxes', status: 'live', nav: true, route: '/tax', tab: 'taxes', emoji: '📚',
    sub: 'GST · CGT · FBT', blurb: 'GST, BAS and IAS, capital gains tax, and fringe benefits tax with Division 7A',
    members: ['gst-bas-ias', 'cgt', 'fbt-other-taxes'] },
  { id: 'tax-workings', domain: 'tax_compliance', after: 'taxes', name: 'Tax Workings', status: 'live', nav: true, route: '/tax', tab: 'workings', emoji: '🧮',
    sub: 'Income tax · Lodgment · Planning · Workpapers', blurb: 'Income tax workings, lodgment readiness, tax planning and review-ready workpapers',
    members: ['income-tax', 'tax-lodgement-ato', 'tax-planning', 'tax-workpapers'] },
]
export function applyGroups(items, domainId) {
  let out = items
  for (const g of MODULE_GROUPS.filter(x => x.domain === domainId)) {
    if (!out.some(m => g.members.includes(m.id))) continue
    const rest = out.filter(m => !g.members.includes(m.id))
    const at = rest.findIndex(m => m.id === g.after)
    rest.splice(at >= 0 ? at + 1 : rest.length, 0, g)
    out = rest
  }
  return out
}
// Settings/Admin switches (Basiq, Stripe, Groq key pool ...) carry an `area`; they are toggled in Admin > Modules Management
// and consumed by the Settings/Admin screens, but they are NOT business modules and must never surface as domain tiles.
export const isAreaItem = m => !!m.area
const byId = Object.fromEntries(DOMAINS.map(d => [d.id, d]))
export const domainOf = id => byId[id]

export const isAvailable = m => m.status === 'live' || m.status === 'beta'

// Side panel: modules flagged nav:true (live, preview and "soon"), grouped by domain.
export function navGroups() {
  return DOMAINS.map(d => ({ domain: d, items: applyGroups(MODULES.filter(m => m.domain === d.id && m.nav && !isAreaItem(m)), d.id) }))
    .filter(g => g.items.length)
}

// Home page: every domain that has at least one module, with all statuses. A module with a `parent` is a sub-tab of that
// module (e.g. Payslips inside Payrun): it keeps its own plan/visibility switch but is not listed as a separate tile.
// A module with `home: false` (e.g. My Pay) is likewise left off the Home page.
export function homeGroups() {
  return DOMAINS.map(d => ({ domain: d, items: applyGroups(MODULES.filter(m => m.domain === d.id && !isAreaItem(m) && !m.parent && m.home !== false), d.id) }))
    .filter(g => g.items.length)
}

export const hrefOf = m => m.route ? m.route + (m.tab ? `?tab=${m.tab}` : '') : null

// A side-panel entry is active on its route, and - when several entries share one page - only for
// the tabs it owns (e.g. /trading: Tax Returns owns taxreturn/property, Shares & Crypto owns crypto/stocks).
export function isNavActive(m, location) {
  if (!m.route || location.pathname !== m.route) return false
  if (!m.tabs) return true
  const tab = new URLSearchParams(location.search).get('tab')
  if (tab) return m.tabs.includes(tab)
  const owners = MODULES.filter(x => x.nav && x.route === m.route)
  return owners[0]?.id === m.id
}

// Domain groups for the sidebar's domain list + per-domain module dropdown: every leaf
// (Overview first, then features, live or planned) grouped by domain, in registry order.
export function domainGroups() {
  return DOMAINS.map(d => ({ domain: d, items: applyGroups(MODULES.filter(m => m.domain === d.id && !isAreaItem(m)), d.id) }))
    .filter(g => g.items.length)
}

// Which leaf of a domain's dropdown matches the current location - used as the <select> value.
// Prefers a specific feature leaf over the domain's own "Overview" leaf when both share a route+tab.
export function activeLeafId(items, location) {
  const tab = new URLSearchParams(location.search).get('tab') || null
  const matches = items.filter(m => m.route === location.pathname && (m.tab || null) === tab)
  if (!matches.length) return null
  const specific = matches.find(m => !m.id.startsWith('overview-'))
  return (specific || matches[0]).id
}

// The domain that owns the currently active route (for highlighting the domain row).
export function domainForLocation(location) {
  const group = domainGroups().find(({ items }) => activeLeafId(items, location))
  return group?.domain.id ?? null
}

// Applies admin-controlled module visibility (see useModuleVisibility) on top of
// domainGroups()/homeGroups() output: drops hidden domains, drops hidden leaves
// within the domains that remain, and drops any domain left with nothing visible
// (so the side panel never links to an empty page). Used by the side panel and
// the Home page; hub pages use tabsForDomain below instead, since their tab bars
// are defined locally rather than derived from these {domain, items} groups.
export function visibleGroups(groups, isDomainVisible, isModuleVisible) {
  return groups
    .filter(g => isDomainVisible(g.domain.id))
    .map(g => ({ ...g, items: g.items.filter(m => m.members ? m.members.some(isModuleVisible) : isModuleVisible(m.id)) }))
    .filter(g => g.items.some(m => m.route))      // a domain needs at least one routable module to link to
}

// A hub page's TABS entries use a local `key` (e.g. 'ledger', 'reconciliation') that
// matches a module's `tab` field in the registry - or, for the one entry per domain
// with no `tab` field (the default landing tab), the literal key 'dashboard'. This
// resolves each TABS entry to its module id so a hub page can filter its own tab bar
// against the same visibility map as the side panel and Home, then drops the entry
// if no matching module is found at all (keeps working even if a key is renamed).
export function tabsForDomain(domainId, TABS, isModuleVisible) {
  const byTabKey = {}
  for (const m of MODULES) {
    if (m.domain !== domainId || !m.route) continue      // route-less entries (capability flags) are not tabs
    byTabKey[m.tab || 'dashboard'] = m.id
  }
  return TABS.filter(t => {
    const moduleId = byTabKey[t.key]
    return moduleId ? isModuleVisible(moduleId) : true
  })
}

// The business module the current page belongs to (by route + ?tab), or null for pages that are not modules (Home, Settings, Admin ...).
// Used to stop a page opening by typed address / bookmark when the organisation's plan does not include it.
export function moduleAtLocation(location) {
  const tab = new URLSearchParams(location.search).get('tab') || null
  const here = MODULES.filter(m => !isAreaItem(m) && m.route === location.pathname)
  if (!here.length) return null
  const exact = here.filter(m => (m.tab || null) === tab)
  if (exact.length) return exact.find(m => !m.id.startsWith('overview-')) || exact[0]
  if (!tab) return here.find(m => !m.tab) || null                      // the page's default tab
  return here.find(m => (m.tabs || []).includes(tab)) || null          // one module owning several tabs
}

