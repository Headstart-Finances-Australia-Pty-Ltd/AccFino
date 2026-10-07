import React from 'react'
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import TopBar from '../components/ui/TopBar.jsx'

const setWidth = w => { Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: w }); act(() => { window.dispatchEvent(new Event('resize')) }) }
afterEach(() => setWidth(1024))

describe('app top bar on narrow screens', () => {
  it('desktop: absolutely centred name, breadcrumb and labelled Home / Logout', () => {
    setWidth(1280)
    render(<TopBar variant="app" pageName="Tax" initials="O" userName="owner" onLogout={() => {}} />)
    expect(screen.getByTestId('topbar-user').style.position).toBe('absolute')
    expect(screen.getByText('AccFino')).toBeInTheDocument(); expect(screen.getByText(/Logout/)).toBeVisible()
  })
  it('phone: the name takes the free space (no absolute overlay), the breadcrumb shows only the page, and the buttons stay reachable by name', () => {
    setWidth(390)
    render(<TopBar variant="app" pageName="Tax" initials="O" userName="a very long organisation owner name that would collide" onLogout={() => {}} />)
    const u = screen.getByTestId('topbar-user')
    expect(u.style.position).not.toBe('absolute'); expect(u.style.flex).toContain('1')
    expect(screen.queryByText('AccFino')).not.toBeInTheDocument(); expect(screen.getByText('Tax')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Logout' })).toBeInTheDocument(); expect(screen.getByRole('link', { name: 'Home' })).toBeInTheDocument()   // icon-only, still named for screen readers
  })
  it('crossing the breakpoint switches layout without a reload', () => {
    setWidth(1280)
    render(<TopBar variant="app" pageName="Tax" initials="O" userName="owner" onLogout={() => {}} />)
    expect(screen.getByTestId('topbar-user').style.position).toBe('absolute')
    setWidth(400); expect(screen.getByTestId('topbar-user').style.position).not.toBe('absolute')
    setWidth(1200); expect(screen.getByTestId('topbar-user').style.position).toBe('absolute')
  })
})
