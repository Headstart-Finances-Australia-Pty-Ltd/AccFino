/**
 * TopBar.jsx — shared top navigation bar used on every page.
 *
 * Props:
 *   variant   "marketing"  — logo + nav links + Sign in + Start free (Login / PaymentPage)
 *             "app"        — breadcrumb (left) + userName (centre) + avatar + logout (right)
 *
 *   // marketing variant only:
 *   onSignIn        () => void
 *   onStartFree     () => void
 *
 *   // app variant only:
 *   pageName        string   — breadcrumb page label e.g. "Dashboard"
 *   initials        string   — user initials e.g. "JT"
 *   userName        string   — full name or email displayed in centre
 *   onLogout        () => void
 */
import React from 'react'
import { LogOut } from 'lucide-react'

const NAV_LINKS = [
  { label: 'Features',     href: '/index-marketing.html#features'     },
  { label: 'Why AccFino',  href: '/index-marketing.html#advantages'   },
  { label: 'Pricing',      href: '/index-marketing.html#pricing'      },
 /* { label: 'Integrations', href: '/index-marketing.html#integrations' }, */
 /* { label: 'Built on',     href: '/index-marketing.html#stack'        }, */
]

/* ─── Shared style tokens ─────────────────────────────────────────────────── */
const BAR = {
  position: 'sticky', top: 0, zIndex: 200,
  height: 60,
  display: 'flex', alignItems: 'center',
  padding: '0 54px 0 24px',
  background: 'rgba(13,17,23,.92)',
  backdropFilter: 'blur(16px) saturate(180%)',
  borderBottom: '3px solid rgba(255,255,255,0.12)',
  flexShrink: 0,
}

const LOGO_LINK = {
  display: 'flex', alignItems: 'center', gap: 9,
  fontFamily: "'Instrument Serif', serif",
  fontSize: '1.35rem',
  color: '#fff', letterSpacing: '-.01em',
  textDecoration: 'none', cursor: 'pointer',
}

const LOGO_GEM = {
  width: 35, height: 35, borderRadius: 12, flexShrink: 0,
  background: 'linear-gradient(135deg,#C8963E 0%,#E8B86D 100%)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  boxShadow: '0 2px 10px rgba(200,150,62,.4)',
}

const NAV_LINKS_WRAP = {
  display: 'flex', gap: 28,
  fontSize: '.9rem', color: '#ffffff',
  marginRight: 28,
}

const BTN_GHOST = {
  fontSize: '.9rem', fontWeight: 500, padding: '9px 20px',
  borderRadius: 6, border: '1px solid rgba(255,255,255,.18)',
  background: 'transparent', color: 'rgba(255,255,255,.8)',
  cursor: 'pointer', marginRight: 8, fontFamily: 'inherit',
  transition: 'all .15s',
}

const BTN_CTA = {
  fontSize: '.9rem', fontWeight: 600, padding: '9px 22px',
  borderRadius: 6, border: 'none',
  background: '#C8963E', color: '#fff',
  cursor: 'pointer', fontFamily: 'inherit',
  boxShadow: '0 2px 10px rgba(200,150,62,.35)',
  transition: 'background .15s', letterSpacing: '.01em',
}

/* ─── Logo gem SVG ────────────────────────────────────────────────────────── */
function LogoGem() {
  return (
    <div style={LOGO_GEM}>
      <svg width="20" height="20" viewBox="0 0 40 40" fill="none">
        <rect x="8"  y="28" width="5" height="16" rx="2" transform="rotate(-30 8 28)"  fill="white" opacity="0.9"/>
        <rect x="27" y="9"  width="5" height="16" rx="2" transform="rotate(30 27 9)"   fill="white" opacity="0.9"/>
        <rect x="12" y="23" width="16" height="4" rx="2" fill="#FF6B35"/>
        <path d="M20 7 L24 13 H22 V18 H18 V13 H16 Z" fill="#FF6B35"/>
      </svg>
    </div>
  )
}

/* ─── Logo text ───────────────────────────────────────────────────────────── */
function LogoText() {
  return <span>Acc<span style={{color:'#FF6B35'}}>Fino</span></span>
}

/* ─── TopBar component ────────────────────────────────────────────────────── */
export default function TopBar({ variant = 'marketing', onSignIn, onStartFree, pageName, initials, userName, onLogout }) {

  if (variant === 'marketing') {
    return (
      <nav style={BAR}>
        <a href="/index-marketing.html" style={{ ...LOGO_LINK, marginRight: 'auto' }}>
          <LogoGem/>
          <LogoText/>
        </a>
        <div style={NAV_LINKS_WRAP} className="mkt-nav-links">
          {NAV_LINKS.map(({ label, href }) => (
            <a key={href} href={href} style={{ color: '#ffffff', textDecoration: 'none' }}>{label}</a>
          ))}
        </div>
        <button style={BTN_GHOST} onClick={onSignIn}>Sign in</button>
        <button style={BTN_CTA}   onClick={onStartFree}>Start free →</button>
      </nav>
    )
  }

  /* variant === "app" */
  return (
    <header style={{
      height: 'var(--header-h)',
      background: 'var(--surface)',
      borderBottom: '3px solid rgba(255,255,255,0.12)',
      display: 'flex', alignItems: 'center',
      padding: '0 24px',
      position: 'relative',
      top: 0, zIndex: 10,
      flexShrink: 0,
    }}>
      {/* Breadcrumb — left */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: '.9rem', color: 'var(--text-3)', fontWeight: 500 }}>AccFino</span>
        <span style={{ color: 'var(--border-dark)' }}>/</span>
        <span style={{ fontSize: '.9rem', fontWeight: 600, color: 'var(--text-1)' }}>{pageName}</span>
      </div>

{/* User name — centre */}
<div style={{
  position: 'absolute', left: '50%', transform: 'translateX(-50%)',
  display: 'flex', alignItems: 'center', gap: 8,
  pointerEvents: 'none', whiteSpace: 'nowrap',
}}>
  <div style={{
    width: 28, height: 28, borderRadius: '50%',
    background: 'linear-gradient(135deg,#C8963E,#E8B86D)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: '.65rem', fontWeight: 700, color: '#fff', flexShrink: 0,
  }}>{initials}</div>
  <span style={{ fontSize: '.9rem', fontWeight: 600, color: 'var(--text-1)' }}>
    {userName}
  </span>
</div>
{/* Logout — right */}
<div style={{ display: 'flex', alignItems: 'center', marginLeft: 'auto' }}>
  <button onClick={onLogout} style={{
    background: 'none', border: 'none', cursor: 'pointer',
    fontSize: '.9rem', fontWeight: 700, color: 'var(--text-1)', fontFamily: 'inherit',
    display: 'flex', alignItems: 'center', gap: 4, padding: 0,
  }}>
    <LogOut size={25} color="#FF6B35"/> Logout
  </button>
</div>
</header>
  )
}