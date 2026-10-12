import React from 'react'
import { NavLink, Outlet } from 'react-router-dom'

// A page with sub-tabs; each tab is a nested route rendered in <Outlet/>.
export default function TabHub({ title, icon: Icon, tabs, note }) {
  return (
    <div className="fade-in">
      <div style={{ padding: '4px 24px 0' }}>
        <div className="flex items-center gap-1" style={{ marginBottom: 10 }}>
          {Icon && <Icon size={20} />}<h2 style={{ margin: 0 }}>{title}</h2>
          {note && <span className="text-xs text-muted" style={{ marginLeft: 10 }}>{note}</span>}
        </div>
        <div className="tabs-bar" style={{ marginBottom: 0, flexWrap: 'nowrap', overflowX: 'auto' }} role="tablist">
          {tabs.filter(t => t.visible !== false).map(t => (
            <NavLink key={t.to} to={t.to} role="tab" data-testid={`tab-${t.to}`}
                     className={({ isActive }) => `tab-btn${isActive ? ' active' : ''}`}>
              {t.icon && <t.icon size={14} style={{ marginRight: 5, verticalAlign: '-2px' }} />}{t.label}
            </NavLink>))}
        </div>
      </div>
      <Outlet />
    </div>)
}
