import React from 'react'

// Global error boundary — prevents full app crash on navigation errors
class AppErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false } }
  static getDerivedStateFromError() { return { hasError: true } }
  componentDidCatch(e, info) {
    console.error('App error:', e)
    console.error('Component stack:', info?.componentStack)
    this.setState({ errorMsg: e?.message || String(e) })
  }
  render() {
    if (this.state.hasError) return (
      <div style={{padding:40,textAlign:'center',fontFamily:'sans-serif'}}>
        <h2 style={{marginBottom:12}}>Something went wrong.</h2>
        <p style={{color:'#666',fontSize:'.9rem',marginBottom:8}}>
          Error: {this.state.errorMsg}
        </p>
        <p style={{color:'#999',fontSize:'.8rem',marginBottom:20}}>
          Check browser console (F12) for details.
        </p>
        <button onClick={() => { this.setState({hasError:false, errorMsg:''}); window.location.href='/index-marketing.html' }}
          style={{marginTop:8,padding:'10px 24px',background:'#0F6B44',color:'#fff',
            border:'none',borderRadius:8,cursor:'pointer',fontSize:'1rem',marginRight:8}}>
          Go to Home
        </button>
        <button onClick={() => { this.setState({hasError:false, errorMsg:''}); window.location.href='/login' }}
          style={{marginTop:8,padding:'10px 24px',background:'#333',color:'#fff',
            border:'none',borderRadius:8,cursor:'pointer',fontSize:'1rem'}}>
          Go to Login
        </button>
      </div>
    )
    return this.props.children
  }
}
import { Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import { AuthProvider, useAuth } from './hooks/useAuth.jsx'
import Layout                from './components/layout/Layout.jsx'
import LoginPage             from './pages/LoginPage.jsx'
import DashboardPage         from './pages/DashboardPage.jsx'
import OverviewPage          from './pages/OverviewPage.jsx'
import ReconciliationPage    from './pages/ReconciliationPage.jsx'
import TradingPage           from './pages/TradingPage.jsx'
import SmartLendingPage      from './pages/lending/SmartLendingPage.jsx'
import CashFlowPage          from './pages/CashFlowPage.jsx'
import InvoicePage           from './pages/InvoicePage.jsx'
import AccountingPage        from './pages/accounting/AccountingPage.jsx'
import PayrollPage           from './pages/accounting/PayrollPage.jsx'
import AdminPage             from './pages/AdminPage.jsx'
import PaymentPage           from './pages/PaymentPage.jsx'
import FileManagerPage       from './pages/FileManagerPage.jsx'
import LicencePage           from './pages/LicencePage.jsx'
import PricingAdminPage      from './pages/PricingAdminPage.jsx'
import ResetPasswordPage     from './pages/ResetPasswordPage.jsx'
import SetupPage             from './pages/SetupPage.jsx'
import CompanyDBPage         from './pages/CompanyDBPage.jsx'

function Guard({ children, adminOnly }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  const isAdmin = (Array.isArray(user.roles) && user.roles.includes('admin')) || user?.is_admin === true
  if (adminOnly && !isAdmin) return <Navigate to="/" replace />
  return children
}

function AppRoutes() {
  const { user } = useAuth()
  return (
    <Routes>
      <Route path="/upgrade"         element={<PaymentPage />} />
      <Route path="/login"          element={user ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/reset-password" element={user ? <Navigate to="/" replace /> : <ResetPasswordPage />} />
      <Route path="/" element={<Guard><Layout /></Guard>}>
        <Route index                    element={<OverviewPage />} />
        <Route path="dashboard"           element={<DashboardPage />} />
        <Route path="reconciliation"    element={<ReconciliationPage />} />
        <Route path="lending"            element={<SmartLendingPage />} />
        <Route path="accounting"        element={<AccountingPage />} />
        <Route path="payroll"           element={<PayrollPage />} />
        <Route path="trading"           element={<TradingPage />} />
        <Route path="cash-flow"         element={<CashFlowPage />} />
        <Route path="invoice"           element={<InvoicePage />} />
        <Route path="setup"             element={<SetupPage />} />
        <Route path="admin"             element={<Guard adminOnly><AdminPage /></Guard>} />
        <Route path="file-manager"      element={<Guard adminOnly><FileManagerPage /></Guard>} />
        <Route path="licence"           element={<Guard adminOnly><LicencePage /></Guard>} />
        <Route path="pricing-admin"      element={<Guard adminOnly><PricingAdminPage /></Guard>} />
        <Route path="company-db"           element={<Guard adminOnly><CompanyDBPage /></Guard>} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <AppErrorBoundary>
    <AuthProvider>
      <Toaster position="top-right" toastOptions={{
        duration: 3500,
        style: { fontFamily:"'Plus Jakarta Sans',system-ui,sans-serif", fontSize:'.875rem', borderRadius:'10px', boxShadow:'0 8px 24px rgba(15,25,36,.12)' },
        success: { iconTheme: { primary:'#0B6E4F', secondary:'#fff' } },
      }} />
      <AppRoutes />
    </AuthProvider>
    </AppErrorBoundary>
  )
}