import React, { lazy, Suspense } from 'react'

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
import { ModuleVisibilityProvider } from './hooks/useModuleVisibility.jsx'
import Layout                from './components/layout/Layout.jsx'
import LoginPage             from './pages/LoginPage.jsx'
const DashboardPage = lazy(() => import('./pages/DashboardPage.jsx'))
const OverviewPage = lazy(() => import('./pages/OverviewPage.jsx'))
const ReconciliationPage = lazy(() => import('./pages/ReconciliationPage.jsx'))
const TradingPage = lazy(() => import('./pages/TradingPage.jsx'))
const SmartLendingPage = lazy(() => import('./pages/lending/SmartLendingPage.jsx'))
const LendingHubPage = lazy(() => import('./pages/LendingHubPage.jsx'))
const TaxCompliancePage = lazy(() => import('./pages/TaxCompliancePage.jsx'))
const AssetsInvestmentsPage = lazy(() => import('./pages/AssetsInvestmentsPage.jsx'))
const PlanningPage = lazy(() => import('./pages/PlanningPage.jsx'))
const PracticePage = lazy(() => import('./pages/PracticePage.jsx'))
const CashFlowPage = lazy(() => import('./pages/CashFlowPage.jsx'))
const InvoicePage = lazy(() => import('./pages/InvoicePage.jsx'))
const AccountingPage = lazy(() => import('./pages/accounting/AccountingPage.jsx'))
const PayrollPage = lazy(() => import('./pages/accounting/PayrollPage.jsx'))
const AdminPage = lazy(() => import('./pages/AdminPage.jsx'))
const PaymentPage = lazy(() => import('./pages/PaymentPage.jsx'))
const FileManagerPage = lazy(() => import('./pages/FileManagerPage.jsx'))
const LicencePage = lazy(() => import('./pages/LicencePage.jsx'))
const PricingAdminPage = lazy(() => import('./pages/PricingAdminPage.jsx'))
const ModulesAdminPage = lazy(() => import('./pages/ModulesAdminPage.jsx'))
import ResetPasswordPage     from './pages/ResetPasswordPage.jsx'
const SetupPage = lazy(() => import('./pages/SetupPage.jsx'))
const LedgerPage = lazy(() => import('./pages/ledger/LedgerPage.jsx'))
const OpenBankingPage = lazy(() => import('./pages/OpenBankingPage.jsx'))
const IAMSetupPage = lazy(() => import('./pages/settings/IAMSetupPage.jsx'))
const ApiWebhooksPage = lazy(() => import('./pages/settings/ApiWebhooksPage.jsx'))
import ComingSoonTab         from './components/layout/ComingSoonTab.jsx'
const SettingsHub = lazy(() => import('./pages/hubs/SettingsHub.jsx'))
const MyAccountPage = lazy(() => import('./pages/MyAccountPage.jsx'))
import useOrgRole from './hooks/useOrgRole.jsx'
const AdminHub = lazy(() => import('./pages/hubs/AdminHub.jsx'))
function Guard({ children, adminOnly }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  const isAdmin = (Array.isArray(user.roles) && user.roles.includes('admin')) || user?.is_admin === true
  if (adminOnly && !isAdmin) return <Navigate to="/" replace />
  return children
}

// Organisation settings are for the Organisation Admin only. This hides the screens; the API refuses everyone else on every organisation-level endpoint.
function OrgAdminGuard({ children }) {
  const { loading, isOrgAdmin } = useOrgRole()
  if (loading) return <div style={{padding:40,textAlign:'center',color:'#888'}}>Loading…</div>
  if (!isOrgAdmin) return <Navigate to="/my-account" replace />
  return children
}

function AppRoutes() {
  const { user } = useAuth()
  return (
    <Suspense fallback={<div style={{padding:40,textAlign:'center',color:'#888'}}>Loading…</div>}>
    <Routes>
      <Route path="/upgrade"         element={<PaymentPage />} />
      <Route path="/login"          element={user ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/reset-password" element={user ? <Navigate to="/" replace /> : <ResetPasswordPage />} />
      <Route path="/" element={<Guard><Layout /></Guard>}>
        <Route index                    element={<OverviewPage />} />
        <Route path="dashboard"           element={<DashboardPage />} />
        <Route path="reconciliation"    element={<ReconciliationPage />} />
        <Route path="lending"            element={<LendingHubPage />} />
        <Route path="accounting"        element={<AccountingPage />} />
        <Route path="payroll"           element={<PayrollPage />} />
        <Route path="trading"           element={<TradingPage />} />
        <Route path="tax"               element={<TaxCompliancePage />} />
        <Route path="investments"       element={<AssetsInvestmentsPage />} />
        <Route path="planning"          element={<PlanningPage />} />
        <Route path="practice"          element={<PracticePage />} />
        <Route path="cash-flow"         element={<CashFlowPage />} />
        <Route path="invoice"           element={<InvoicePage />} />
        <Route path="ledger"            element={<LedgerPage />} />
        <Route path="open-banking"      element={<Navigate to="/settings/open-banking" replace />} />

        {/* My Account - every user: personal details and sign-in security. Settings - the Organisation Admin only (organisation details, users,
            access codes, licence, IAM, integrations); the API enforces it as well. */}
        <Route path="my-account" element={<MyAccountPage />} />
        <Route path="settings" element={<OrgAdminGuard><SettingsHub /></OrgAdminGuard>}>
          <Route index                  element={<Navigate to="setup" replace />} />
          <Route path="setup"           element={<SetupPage />} />
          {/* Organisation now lives inside Business Setup as its first sub-tab (see SetupPage.jsx) */}
          <Route path="organisation"    element={<Navigate to="../setup" replace />} />
          <Route path="iam"             element={<IAMSetupPage />} />
          <Route path="identity"        element={<Navigate to="../iam" replace />} />
          <Route path="security"        element={<Navigate to="../iam" replace />} />
          <Route path="open-banking"    element={<OpenBankingPage />} />
          <Route path="integrations"    element={
            <div className="fade-in" style={{padding:24}}>
              <ComingSoonTab emoji="🧩" name="Business Integrations" phase="Phase 3" blurb="Integrations with other business software."/>
            </div>
          } />
          <Route path="api-webhooks"    element={<ApiWebhooksPage />} />
        </Route>

        {/* Admin - AccFino super admin team only */}
        <Route path="admin" element={<Guard adminOnly><AdminHub /></Guard>}>
          <Route index                  element={<Navigate to="api-keys" replace />} />
          <Route path="api-keys"        element={<AdminPage />} />
          <Route path="licence"         element={<LicencePage />} />
          <Route path="file-manager"    element={<FileManagerPage />} />
          <Route path="payments"        element={<Navigate to="/admin/api-keys?tab=payments" replace />} />
          <Route path="pricing"         element={<PricingAdminPage />} />
          <Route path="open-banking"    element={<Navigate to="/admin/api-keys?tab=open-banking" replace />} />
          <Route path="modules"         element={<ModulesAdminPage />} />
          {/* Old addresses keep working - Platform Users now lives inside "licence" (Users & Licence);
              Company DB was removed (covered by Data Manager / Settings > Setup > Knowledgebase). */}
          <Route path="ml-classifier"   element={<Navigate to="../api-keys" replace />} />
          <Route path="platform-users"  element={<Navigate to="../licence" replace />} />
          <Route path="company-db"      element={<Navigate to="../file-manager" replace />} />
        </Route>

        {/* Old addresses keep working */}
        <Route path="setup"             element={<Navigate to="/settings/setup" replace />} />
        <Route path="organisation"      element={<Navigate to="/settings/setup" replace />} />
        <Route path="security"          element={<Navigate to="/my-account?tab=security" replace />} />
        <Route path="identity"          element={<Navigate to="/settings/iam" replace />} />
        <Route path="platform"          element={<Navigate to="/settings" replace />} />
        <Route path="file-manager"      element={<Navigate to="/admin/file-manager" replace />} />
        <Route path="licence"           element={<Navigate to="/admin/licence" replace />} />
        <Route path="pricing-admin"     element={<Navigate to="/admin/pricing" replace />} />
        <Route path="company-db"        element={<Navigate to="/admin/file-manager" replace />} />
      </Route>
    </Routes>
    </Suspense>
  )
}

export default function App() {
  return (
    <AppErrorBoundary>
    <AuthProvider>
    <ModuleVisibilityProvider>
      <Toaster position="top-right" toastOptions={{
        duration: 3500,
        style: { fontFamily:"'Plus Jakarta Sans',system-ui,sans-serif", fontSize:'.875rem', borderRadius:'10px', boxShadow:'0 8px 24px rgba(15,25,36,.12)' },
        success: { iconTheme: { primary:'#0B6E4F', secondary:'#fff' } },
      }} />
      <AppRoutes />
    </ModuleVisibilityProvider>
    </AuthProvider>
    </AppErrorBoundary>
  )
}