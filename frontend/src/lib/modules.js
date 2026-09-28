// Module registry helpers. src/config/modules.json is the single source of truth for the
// side panel, the in-app Home page and the public landing page (served as /modules.json).
import registry from '../config/modules.json'

export const REGISTRY = registry
export const STATUS_LABEL = registry.statuses
export const DOMAINS = [...registry.domains].sort((a, b) => a.order - b.order)
export const MODULES = registry.modules
// Settings/Admin switches (Basiq, Stripe, Groq key pool ...) carry an `area`; they are toggled in Admin > Modules Management
// and consumed by the Settings/Admin screens, but they are NOT business modules and must never surface as domain tiles.
export const isAreaItem = m => !!m.area
const byId = Object.fromEntries(DOMAINS.map(d => [d.id, d]))
export const domainOf = id => byId[id]

export const isAvailable = m => m.status === 'live' || m.status === 'beta'

// Side panel: modules flagged nav:true (live, preview and "soon"), grouped by domain.
export function navGroups() {
  return DOMAINS.map(d => ({ domain: d, items: MODULES.filter(m => m.domain === d.id && m.nav && !isAreaItem(m)) }))
    .filter(g => g.items.length)
}

// Home page: every domain that has at least one module, with all statuses.
export function homeGroups() {
  return DOMAINS.map(d => ({ domain: d, items: MODULES.filter(m => m.domain === d.id && !isAreaItem(m)) }))
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
  return DOMAINS.map(d => ({ domain: d, items: MODULES.filter(m => m.domain === d.id && !isAreaItem(m)) }))
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
    .map(g => ({ ...g, items: g.items.filter(m => isModuleVisible(m.id)) }))
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
