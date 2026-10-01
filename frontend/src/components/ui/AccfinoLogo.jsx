import React from 'react'

/**
 * Accfino Logo — Abstract geometric mark: overlapping A-shape with upward arrow
 * suggesting finance, growth, precision.
 */
export default function AccfinoLogo({ size = 32, showText = true, textColor = '#fff', light = false }) {
  const markColor = light ? '#0B6E4F' : '#fff'
  const accentCol = '#FF6B35'

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: showText ? 10 : 0 }}>
      {/* Mark */}
      <svg width={size} height={size} viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
        {/* Background pill */}
        <rect width="40" height="40" rx="10" fill={light ? '#0B6E4F' : 'rgba(255,255,255,0.15)'}/>
        {/* Left bar of A */}
        <rect x="8" y="28" width="5" height="16" rx="2" transform="rotate(-30 8 28)" fill={markColor} opacity="0.9"/>
        {/* Right bar of A */}
        <rect x="27" y="9" width="5" height="16" rx="2" transform="rotate(30 27 9)" fill={markColor} opacity="0.9"/>
        {/* Cross bar — accent */}
        <rect x="12" y="23" width="16" height="4" rx="2" fill={accentCol}/>
        {/* Arrow up */}
        <path d="M20 7 L24 13 H22 V18 H18 V13 H16 Z" fill={accentCol}/>
      </svg>

      {showText && (
        <span style={{
          fontFamily: "'Sora', 'Plus Jakarta Sans', sans-serif",
          fontWeight: 700, fontSize: size * 0.55,
          color: textColor, letterSpacing: '-0.03em',
          lineHeight: 1,
        }}>
          <span>acc</span>
          <span style={{ color: accentCol }}>fino</span>
        </span>
      )}
    </div>
  )
}
