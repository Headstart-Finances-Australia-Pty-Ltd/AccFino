// Payrun sub-tab configuration (kept out of the page so PayrollPage can use it without pulling the lazy tab chunks in).
// need(me) decides who sees a sub-tab (same rules the six features had as top-level tabs; the server still authorises every call).
// moduleId ties each sub-tab to its registry module, so plan / Admin > Modules visibility keeps working exactly as before.
const has = (me, ...caps) => caps.some(c => me.capabilities.includes(c))
export const PAYRUN_TABS = [
  { key: 'pays', label: 'Pay Runs', moduleId: 'pay-runs', need: me => has(me, 'reports_view') },
  { key: 'payslips', label: 'Payslips', moduleId: 'payslips', need: me => has(me, 'sensitive_view') },
  { key: 'payments', label: 'Payments', moduleId: 'payroll-payments', need: me => has(me, 'payments_manage', 'reports_view') },
  { key: 'super', label: 'Super', moduleId: 'superannuation', need: me => has(me, 'reports_view') },
  { key: 'payitems', label: 'Pay Items', moduleId: 'pay-items', need: me => has(me, 'items_manage') },
  { key: 'payg', label: 'PAYG', moduleId: 'payg-withholding', need: me => has(me, 'reports_view') },
  { key: 'audit', label: 'Audit', moduleId: 'payroll-audit', need: me => has(me, 'audit_view') },
]

// Old top-level payroll tab keys -> Payrun sub-tab, so bookmarks, dashboard links and registry links keep working.
export const LEGACY_TAB_TO_SUB = { runs: 'pays', payslips: 'payslips', payments: 'payments', super: 'super', payitems: 'payitems', payg: 'payg', audit: 'audit' }

export function visiblePayrunTabs(me, isModuleVisible) {
  return PAYRUN_TABS.filter(t => t.need(me) && isModuleVisible(t.moduleId))
}

