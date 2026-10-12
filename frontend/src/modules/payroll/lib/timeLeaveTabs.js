// Time & Leave sub-tab configuration. Same permission rules the two features had as separate top-level tabs (the server still authorises every call).
// moduleId ties each sub-tab to its registry module, so plan / Admin > Modules visibility keeps working exactly as before.
const has = (me, ...caps) => caps.some(c => me.capabilities.includes(c))
export const TIME_LEAVE_TABS = [
  { key: 'timesheets', label: 'Timesheets', moduleId: 'timesheets', need: me => has(me, 'timesheets_manage', 'timesheets_approve') || me.self_service },
  { key: 'leave', label: 'Leave', moduleId: 'leave-entitlements', need: me => has(me, 'leave_manage', 'leave_approve') || me.self_service },
]

// Old top-level payroll tab keys -> Time & Leave sub-tab (bookmarks, dashboard links, registry links).
export const LEGACY_TIME_TO_SUB = { timesheets: 'timesheets', leave: 'leave' }

// An ordinary employee (no payroll role, nobody reporting to them) does everything in My Pay, which already embeds their timesheets and leave:
// a second Time & Leave tab would only duplicate it. Managers and payroll staff keep Time & Leave (that is where approvals happen).
export const isPureEmployee = me => !!me.self_service && !me.is_manager && !has(me, 'timesheets_manage', 'timesheets_approve', 'leave_manage', 'leave_approve')

export function visibleTimeLeaveTabs(me, isModuleVisible) {
  if (isPureEmployee(me)) return []
  return TIME_LEAVE_TABS.filter(t => t.need(me) && isModuleVisible(t.moduleId))
}
