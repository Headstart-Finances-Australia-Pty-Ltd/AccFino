import React, { useEffect, useState, useRef } from 'react'
import { mlStatus, mlTrain, mlSampleCsv } from '../../modules/reconciliation/public.js'
import { Key, Brain, Check, X, Play, Pencil } from 'lucide-react'
import toast from 'react-hot-toast'
import PlatformSettingsPanels from './admin/PlatformSettingsPanels.jsx'
import { OpenBankingSetupPage } from '../../modules/open_banking/public.js'
import { PaymentGatewayAdminPage } from '../../modules/billing/public.js'
import TenantAddressCheck from '../components/tenancy/TenantAddressCheck.jsx'
import { useModuleVisibility } from '../hooks/useModuleVisibility.jsx'

const ALLOWED_GST = ['','GST on Expenses','GST on Capital','GST on Income','GST Free Expenses','GST Free Income','BAS Excluded']
const DIRECTION_OPTIONS = [
  { value: '', label: 'Any direction' },
  { value: 'debit_only', label: '🟡 Outgoing only (debit)' },
  { value: 'credit_only', label: '🔵 Incoming only (credit)' },
]

// BLANK_FORM removed -- RDR rule form now lives only in Setup page (SetupPage.jsx RdrTab)

const ALL_TABS = [
  ['platform','🔌 Platform Settings', null],
  ['open-banking','🏦 Open Banking', ['basiq-admin-open-banking','openfeed-admin-open-banking']],     // Basiq + OpenFeed platform set-up (clients only ever see Settings > Open Banking)
  ['payments','💳 Payment Card Setup', ['square-admin-payments','stripe-admin-payments']],            // Square / Stripe: how AccFino charges organisations their subscription
  ['addresses','🌐 Web Addresses', null],                 // https://<organisation>.<your domain>: what is still missing
  ['ml','🧠 ML Training', 'ml-training'],
]
// A deep link such as /admin/api-keys?tab=open-banking opens that tab straight away.
const tabFromUrl = () => {
  const k = new URLSearchParams(typeof window !== 'undefined' ? window.location.search : '').get('tab')
  return ALL_TABS.some(([id]) => id === k) ? k : 'platform'
}

export default function AdminPage() {
  const { isModuleVisible } = useModuleVisibility()
  // a tab with several module ids is shown while ANY of them is switched on (Admin > Modules Management > Settings & Admin Console)
  const TABS = ALL_TABS.filter(([,,moduleId]) => !moduleId || [].concat(moduleId).some(isModuleVisible))
  const [tab,       setTabState] = useState(tabFromUrl)
  const setTab = k => setTabState(k)
  useEffect(() => { if (!TABS.find(([k]) => k === tab) && TABS[0]) setTab(TABS[0][0]) }, [TABS.map(([k])=>k).join(',')])
  const [mlStat,    setMlStat]   = useState(null)
  const [training,  setTraining] = useState(false)
  const [trainRes,  setTrainRes] = useState(null)
  // RDR rules editor moved entirely to Setup page (SetupPage.jsx RdrTab) --
  // this page no longer duplicates that state/UI.
  const fileRef = React.useRef()

  useEffect(()=>{
    mlStatus().then(r=>setMlStat(r.data)).catch(()=>{})
  },[])

  const trainModel = async () => {
    const file = fileRef.current?.files?.[0]
    if (!file) { toast.error('Select a training CSV first'); return }
    setTraining(true); setTrainRes(null)
    try {
      const fd = new FormData(); fd.append('file', file, file.name)
      const { data } = await mlTrain(fd)
      setTrainRes(data); setMlStat(s=>({...s,category_model:true,gst_model:true}))
      toast.success('Models trained successfully')
    } catch (e) { toast.error(e.response?.data?.detail||'Training failed') }
    finally { setTraining(false) }
  }

  const downloadSample = async () => {
    const { data } = await mlSampleCsv()
    const a = document.createElement('a'); a.href=URL.createObjectURL(new Blob([data])); a.download='sample_training_data.csv'; a.click()
  }


  return (
    <div className="fade-in">
      <div style={{marginBottom:16}}>
        <div className="flex items-center gap-1">
          <Key size={22} />
          <h2 style={{margin:0}}>API Keys</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
          Everything the platform needs to be set up once: platform settings (Groq key pool, Database, S3 storage, system email, Calendly, meeting
          link), the Open Banking providers (Basiq, OpenFeed), the card-payment gateways AccFino charges subscriptions with, and the ML classifier.
          Business Rules (RDR) are managed on the Setup page, and your password under Admin &gt; Users &amp; Licence.
        </p>
      </div>

      <div className="tabs-bar" style={{marginBottom:20, flexWrap:'nowrap', overflowX:'auto'}}>
        {TABS.map(([k,label])=>(
          <button key={k} className={`tab-btn${tab===k?' active':''}`} onClick={()=>setTab(k)}>{label}</button>
        ))}
      </div>

      {tab==='platform' && <PlatformSettingsPanels/>}
      {tab==='open-banking' && <OpenBankingSetupPage embedded />}
      {tab==='payments' && <PaymentGatewayAdminPage embedded />}
      {tab==='addresses' && <TenantAddressCheck />}

      {/* ── ML Training ── */}
      {tab==='ml' && (
        <div style={{display:'grid',gridTemplateColumns:'1fr 360px',gap:20,alignItems:'start'}}>
          <div className="card">
            <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:18,paddingBottom:14,borderBottom:'1px solid var(--border)'}}>
              <Brain size={18} color="var(--brand)"/><h3>Train Classification Models</h3>
            </div>
            <p style={{color:'var(--text-2)',fontSize:'.875rem',marginBottom:16,lineHeight:1.7}}>
              Upload a labelled CSV to retrain the <strong>GL Account</strong> and <strong>GST Category</strong> classifiers.
            </p>
            {mlStat && (
              <div style={{display:'flex',gap:12,marginBottom:16}}>
                <div style={{padding:'8px 14px',borderRadius:'var(--r-md)',background:mlStat.category_model?'var(--success-bg)':'var(--surface-3)',border:`1px solid ${mlStat.category_model?'var(--success-border)':'var(--border)'}`,fontSize:'.8rem',fontWeight:600,color:mlStat.category_model?'var(--success)':'var(--text-3)'}}>
                  {mlStat.category_model?'✅':'❌'} GL Account Model
                </div>
                <div style={{padding:'8px 14px',borderRadius:'var(--r-md)',background:mlStat.gst_model?'var(--success-bg)':'var(--surface-3)',border:`1px solid ${mlStat.gst_model?'var(--success-border)':'var(--border)'}`,fontSize:'.8rem',fontWeight:600,color:mlStat.gst_model?'var(--success)':'var(--text-3)'}}>
                  {mlStat.gst_model?'✅':'❌'} GST Category Model
                </div>
              </div>
            )}
            <div className="input-group" style={{marginBottom:12}}>
              <label>Training CSV File</label>
              <input ref={fileRef} type="file" accept=".csv" className="input" style={{paddingTop:6}}/>
            </div>
            <button className="btn btn-primary" onClick={trainModel} disabled={training}>
              {training?<><span className="spinner spinner-sm"/>Training…</>:<><Brain size={15}/>Train Models</>}
            </button>
            {trainRes && (
              <div className="alert alert-success" style={{marginTop:16}}>
                <strong>✅ Training complete!</strong>
                <div style={{marginTop:6,fontSize:'.8rem'}}>
                  Rows: {trainRes.rows_used} · GL: {trainRes.category_accuracy!=null?(trainRes.category_accuracy*100).toFixed(1)+'%':'—'} · GST: {trainRes.gst_accuracy!=null?(trainRes.gst_accuracy*100).toFixed(1)+'%':'—'}
                </div>
                {trainRes.warning && (
                  <div style={{marginTop:8,padding:'6px 10px',background:'var(--warning-bg,#fffbeb)',
                    borderRadius:'var(--r-md)',fontSize:'.76rem',color:'var(--warning,#b45309)'}}>
                    ⚠ {trainRes.warning}
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="card">
            <h3 style={{marginBottom:12}}>How it works</h3>
            <button className="btn btn-outline btn-sm" onClick={downloadSample}>⬇ Download sample CSV</button>
          </div>
        </div>
      )}
    </div>
  )
}

// Export startEdit so OutputPanel can open Admin page pre-filled
export { }
