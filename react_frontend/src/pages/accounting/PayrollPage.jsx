import React, { useState, useEffect } from 'react'
import { useAuth } from '../../hooks/useAuth.jsx'
import toast from 'react-hot-toast'
import { Plus, Trash2, Check, RefreshCw, Play, Users, DollarSign, Calendar, FileText } from 'lucide-react'
import axios from 'axios'

const http = axios.create({ baseURL: '/api', withCredentials: true })
http.interceptors.request.use(cfg => {
  try { const u = JSON.parse(localStorage.getItem('af_user')||'{}'); if (u.token) cfg.headers['Authorization'] = `Bearer ${u.token}` } catch {}
  return cfg
})

const api = {
  getEmployees:  (uid) => http.get('/payroll/employees', { params: { user_id: uid } }),
  createEmployee:(b)   => http.post('/payroll/employees', b),
  patchEmployee: (id,b)=> http.patch(`/payroll/employees/${id}`, b),
  deleteEmployee:(id)  => http.delete(`/payroll/employees/${id}`),
  getTimesheets: (eid) => http.get('/payroll/timesheets', { params: { employee_id: eid } }),
  createTimesheet:(b)  => http.post('/payroll/timesheets', b),
  patchTimesheet:(id,b)=> http.patch(`/payroll/timesheets/${id}`, b),
  getRuns:       (uid) => http.get('/payroll/payroll-runs', { params: { user_id: uid } }),
  createRun:     (b)   => http.post('/payroll/payroll-runs', b),
  processRun:    (id)  => http.post(`/payroll/payroll-runs/${id}/process`),
  getRun:        (id)  => http.get(`/payroll/payroll-runs/${id}`),
  getPayslips:   ()    => http.get('/payroll/payslips'),
  getStats:      (uid) => http.get('/payroll/stats', { params: { user_id: uid } }),
  getStpList:    ()    => http.get('/payroll/stp/submissions'),
  prepareStp:    (b)   => http.post('/payroll/stp/prepare', b),
  submitStp:     (id)  => http.post(`/payroll/stp/submit/${id}`),
}

const fmtAUD  = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(n||0)
const fmtDate = d => d ? new Date(d).toLocaleDateString('en-AU') : '—'

const EMP_TYPES = ['full_time','part_time','casual','contract']
const PAY_FREQS = ['weekly','fortnightly','monthly']
const AU_STATES = ['ACT','NSW','NT','QLD','SA','TAS','VIC','WA']

const EMPTY_EMP = {
  employee_number:'', first_name:'', last_name:'', email:'', phone:'',
  employment_type:'full_time', pay_frequency:'fortnightly', annual_salary:'',
  hourly_rate:'', tfn:'', super_fund_name:'AustralianSuper', super_member_number:'',
  bank_bsb:'', bank_account_number:'', bank_account_name:'',
  start_date: new Date().toISOString().split('T')[0],
  tax_free_threshold:true, residency_status:'resident',
  address_line1:'', address_suburb:'', address_state:'NSW', address_postcode:'',
}

export default function PayrollPage() {
  const { user } = useAuth()
  const userId   = user?.id

  const [tab,     setTab]     = useState('dashboard')
  const [stats,   setStats]   = useState(null)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    if (!userId) return
    setLoading(true)
    try {
      const r = await api.getStats(userId)
      setStats(r.data)
    } catch {}
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [userId])

  const TABS = [
    { key:'dashboard',   label:'📊 Dashboard'   },
    { key:'employees',   label:'👥 Employees'   },
    { key:'timesheets',  label:'⏱ Timesheets'   },
    { key:'runs',        label:'💸 Payroll Runs' },
    { key:'payslips',    label:'📄 Payslips'    },
    { key:'compliance',  label:'🏛 STP / ATO'   },
  ]

  return (
    <div className="fade-in">
      <div style={{marginBottom:20,display:'flex',alignItems:'flex-start',justifyContent:'space-between'}}>
        <div>
          <h1>👔 Payroll</h1>
          <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
            Australian payroll · PAYG · Super · STP Phase 2
          </p>
        </div>
        <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}>
          <RefreshCw size={13} className={loading?'spin':''}/> Refresh
        </button>
      </div>

      <div className="tabs-bar" style={{marginBottom:0}}>
        {TABS.map(t => (
          <button key={t.key}
            className={`tab-btn${tab===t.key?' active':''}`}
            onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div style={{background:'var(--surface)',border:'1px solid var(--border)',
        borderTop:'none',borderRadius:'0 0 var(--r-lg) var(--r-lg)',
        minHeight:400,overflow:'hidden',boxShadow:'var(--sh-sm)'}}>

        {tab==='dashboard'  && <PayrollDashboard stats={stats} userId={userId} onNav={setTab}/>}
        {tab==='employees'  && <EmployeesTab userId={userId}/>}
        {tab==='timesheets' && <TimesheetsTab userId={userId}/>}
        {tab==='runs'       && <RunsTab userId={userId} onDone={load}/>}
        {tab==='payslips'   && <PayslipsTab/>}
        {tab==='compliance' && <ComplianceTab userId={userId}/>}
      </div>
    </div>
  )
}

// ── Dashboard ──────────────────────────────────────────────────────────────────
function PayrollDashboard({ stats, userId, onNav }) {
  if (!stats) return <div style={{padding:40,textAlign:'center',color:'var(--text-3)'}}>Loading…</div>
  const cards = [
    { label:'Active Employees',  val:stats.total_employees,             icon:Users,     color:'var(--info)',    bg:'var(--info-bg,#e0f2fe)' },
    { label:'Payroll Runs',      val:stats.total_runs,                  icon:Calendar,  color:'var(--brand)',   bg:'var(--brand-light)' },
    { label:'YTD Payroll',       val:fmtAUD(stats.total_payroll_ytd),   icon:DollarSign,color:'var(--success)', bg:'var(--success-bg,#dcfce7)' },
    { label:'Last Run Net Pay',  val:fmtAUD(stats.last_run?.total_net), icon:FileText,  color:'var(--warning)', bg:'var(--warning-bg,#fef3c7)' },
  ]
  return (
    <div style={{padding:24}}>
      <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12,marginBottom:24}}>
        {cards.map(({label,val,icon:Icon,color,bg}) => (
          <div key={label} style={{background:'var(--surface-2)',border:'1px solid var(--border)',
            borderRadius:'var(--r-lg)',padding:'16px',display:'flex',alignItems:'center',gap:12}}>
            <div style={{width:38,height:38,borderRadius:'var(--r-md)',background:bg,
              display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0}}>
              <Icon size={18} color={color}/>
            </div>
            <div>
              <div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em'}}>{label}</div>
              <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'1rem',color:'var(--text-1)'}}>{val}</div>
            </div>
          </div>
        ))}
      </div>

      {stats.last_run && (
        <div style={{background:'var(--surface-2)',borderRadius:'var(--r-lg)',padding:20,
          border:'1px solid var(--border)',marginBottom:16}}>
          <h4 style={{marginBottom:12}}>Last Payroll Run</h4>
          <div style={{display:'grid',gridTemplateColumns:'repeat(5,1fr)',gap:12,fontSize:'.82rem'}}>
            {[
              ['Run Name',    stats.last_run.run_name],
              ['Period',      `${stats.last_run.period_start} → ${stats.last_run.period_end}`],
              ['Employees',   stats.last_run.employee_count],
              ['Gross',       fmtAUD(stats.last_run.total_gross)],
              ['Status',      stats.last_run.status],
            ].map(([l,v]) => (
              <div key={l}>
                <div style={{color:'var(--text-3)',fontSize:'.7rem',fontWeight:700,marginBottom:2,textTransform:'uppercase'}}>{l}</div>
                <div style={{fontWeight:600}}>{v}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{display:'flex',gap:8}}>
        <button className="btn btn-primary btn-sm" onClick={()=>onNav('runs')}><Plus size={13}/> New Payroll Run</button>
        <button className="btn btn-outline btn-sm" onClick={()=>onNav('employees')}><Users size={13}/> Manage Employees</button>
      </div>
    </div>
  )
}

// ── Employees Tab ─────────────────────────────────────────────────────────────
function EmployeesTab({ userId }) {
  const [emps,    setEmps]    = useState([])
  const [showAdd, setShowAdd] = useState(false)
  const [form,    setForm]    = useState({...EMPTY_EMP})
  const [saving,  setSaving]  = useState(false)
  const [editId,  setEditId]  = useState(null)

  const load = async () => {
    try { const r = await api.getEmployees(userId); setEmps(r.data||[]) } catch {}
  }
  useEffect(()=>{ load() },[userId])

  const F = ({label,field,type='text',opts,req}) => {
    const val = form[field]
    return (
      <div className="input-group">
        <label>{label}{req&&' *'}</label>
        {opts
          ? <select className="input input-sm" value={val||''} onChange={e=>setForm(p=>({...p,[field]:e.target.value}))}>
              {opts.map(o=><option key={o.v||o} value={o.v||o}>{o.l||o.replace(/_/g,' ')}</option>)}
            </select>
          : type==='checkbox'
            ? <label style={{display:'flex',alignItems:'center',gap:6,marginTop:4}}>
                <input type="checkbox" checked={!!val} onChange={e=>setForm(p=>({...p,[field]:e.target.checked}))}/>
                <span style={{fontSize:'.8rem',color:'var(--text-2)'}}>{label}</span>
              </label>
            : <input className="input input-sm" type={type} value={val||''} required={req}
                onChange={e=>setForm(p=>({...p,[field]:type==='number'?parseFloat(e.target.value)||'':e.target.value}))}/>
        }
      </div>
    )
  }

  const handleSave = async () => {
    if (!form.employee_number||!form.first_name||!form.last_name||!form.annual_salary) {
      toast.error('Fill in required fields'); return
    }
    setSaving(true)
    try {
      if (editId) {
        await api.patchEmployee(editId, form)
        toast.success('Employee updated ✓')
      } else {
        await api.createEmployee({...form, user_id: userId})
        toast.success('Employee added ✓')
      }
      setShowAdd(false); setForm({...EMPTY_EMP}); setEditId(null); load()
    } catch(e) { toast.error(e.response?.data?.detail||'Save failed') }
    finally { setSaving(false) }
  }

  const handleEdit = (e) => { setForm({...e}); setEditId(e.id); setShowAdd(true) }
  const handleDelete = async (id) => {
    if (!confirm('Deactivate this employee?')) return
    try { await api.deleteEmployee(id); toast.success('Deactivated'); load() } catch { toast.error('Failed') }
  }

  return (
    <div style={{padding:24}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
        <h3>Employees ({emps.length})</h3>
        <button className="btn btn-primary btn-sm" onClick={()=>{setShowAdd(s=>!s);setForm({...EMPTY_EMP});setEditId(null)}}>
          <Plus size={13}/> Add Employee
        </button>
      </div>

      {showAdd && (
        <div className="card card-flat" style={{background:'var(--surface-2)',marginBottom:16}}>
          <h4 style={{marginBottom:16}}>{editId?'Edit':'New'} Employee</h4>
          <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12}}>
            <F label="Employee #"      field="employee_number" req/>
            <F label="First Name"      field="first_name"      req/>
            <F label="Last Name"       field="last_name"       req/>
            <F label="Email"           field="email"           type="email" req/>
            <F label="Phone"           field="phone"/>
            <F label="TFN"             field="tfn"/>
            <F label="Employment Type" field="employment_type" opts={EMP_TYPES}/>
            <F label="Pay Frequency"   field="pay_frequency"   opts={PAY_FREQS}/>
            <F label="Annual Salary"   field="annual_salary"   type="number" req/>
            <F label="Hourly Rate"     field="hourly_rate"     type="number"/>
            <F label="Start Date"      field="start_date"      type="date" req/>
            <F label="Residency"       field="residency_status" opts={[{v:'resident',l:'Resident'},{v:'non_resident',l:'Non-Resident'}]}/>
            <F label="Tax-Free Threshold" field="tax_free_threshold" type="checkbox"/>
          </div>
          <h4 style={{margin:'16px 0 12px'}}>Super & Banking</h4>
          <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12}}>
            <F label="Super Fund"      field="super_fund_name"/>
            <F label="Super USI"       field="super_fund_usi"/>
            <F label="Member Number"   field="super_member_number"/>
            <F label="Bank BSB"        field="bank_bsb"/>
            <F label="Account Number"  field="bank_account_number"/>
            <F label="Account Name"    field="bank_account_name"/>
          </div>
          <h4 style={{margin:'16px 0 12px'}}>Address</h4>
          <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12}}>
            <div style={{gridColumn:'span 2'}}><F label="Street" field="address_line1"/></div>
            <F label="Suburb"    field="address_suburb"/>
            <F label="State"     field="address_state" opts={AU_STATES}/>
            <F label="Postcode"  field="address_postcode"/>
          </div>
          <div style={{display:'flex',gap:8,marginTop:16}}>
            <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
              {saving?'Saving…':<><Check size={13}/> Save</>}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={()=>{setShowAdd(false);setEditId(null)}}>Cancel</button>
          </div>
        </div>
      )}

      {emps.length===0
        ? <div className="empty-state" style={{padding:40}}><p>No employees yet. Add one to get started.</p></div>
        : <table className="data-table">
            <thead><tr>
              <th>Emp #</th><th>Name</th><th>Type</th><th>Freq</th>
              <th style={{textAlign:'right'}}>Salary</th><th>Start</th><th style={{width:100}}>Actions</th>
            </tr></thead>
            <tbody>
              {emps.map(e=>(
                <tr key={e.id}>
                  <td style={{fontFamily:'var(--font-mono)',fontSize:'.78rem'}}>{e.employee_number}</td>
                  <td style={{fontWeight:600}}>{e.first_name} {e.last_name}</td>
                  <td style={{fontSize:'.78rem'}}>{e.employment_type?.replace(/_/g,' ')}</td>
                  <td style={{fontSize:'.78rem'}}>{e.pay_frequency}</td>
                  <td style={{textAlign:'right',fontFamily:'var(--font-mono)',fontWeight:600}}>{fmtAUD(e.annual_salary)}</td>
                  <td style={{fontSize:'.78rem'}}>{e.start_date}</td>
                  <td><div style={{display:'flex',gap:4}}>
                    <button className="btn btn-outline btn-xs" onClick={()=>handleEdit(e)}>✏️</button>
                    <button className="btn btn-danger btn-xs" onClick={()=>handleDelete(e.id)}><Trash2 size={11}/></button>
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
      }
    </div>
  )
}

// ── Timesheets Tab ────────────────────────────────────────────────────────────
function TimesheetsTab({ userId }) {
  const [timesheets, setTimesheets] = useState([])
  const [employees,  setEmployees]  = useState([])
  const [showAdd,    setShowAdd]    = useState(false)
  const [form,       setForm]       = useState({
    employee_id:'', period_start:'', period_end:'',
    ordinary_hours:76, overtime_hours_1_5x:0, overtime_hours_2x:0,
    public_holiday_hours:0, annual_leave_hours:0, sick_leave_hours:0,
    long_service_leave_hours:0, unpaid_leave_hours:0, notes:'',
  })
  const [saving, setSaving] = useState(false)

  const load = async () => {
    try {
      const [tr, er] = await Promise.all([http.get('/payroll/timesheets'), api.getEmployees(userId)])
      setTimesheets(tr.data||[]); setEmployees(er.data||[])
    } catch {}
  }
  useEffect(()=>{ load() },[userId])

  const empName = id => { const e=employees.find(x=>x.id===id); return e?`${e.first_name} ${e.last_name}`:'?' }

  const handleSave = async () => {
    if (!form.employee_id||!form.period_start) { toast.error('Select employee and period'); return }
    setSaving(true)
    try { await api.createTimesheet(form); toast.success('Timesheet saved ✓'); setShowAdd(false); load() }
    catch(e) { toast.error(e.response?.data?.detail||'Save failed') }
    finally { setSaving(false) }
  }

  const handleApprove = async (id) => {
    try { await api.patchTimesheet(id,{status:'approved'}); toast.success('Approved'); load() }
    catch { toast.error('Failed') }
  }

  const NF = ({label,field}) => (
    <div className="input-group">
      <label>{label}</label>
      <input className="input input-sm" type="number" min="0" step="0.5" value={form[field]||0}
        onChange={e=>setForm(p=>({...p,[field]:parseFloat(e.target.value)||0}))}/>
    </div>
  )

  return (
    <div style={{padding:24}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
        <h3>Timesheets ({timesheets.length})</h3>
        <button className="btn btn-primary btn-sm" onClick={()=>setShowAdd(s=>!s)}><Plus size={13}/> New Timesheet</button>
      </div>

      {showAdd && (
        <div className="card card-flat" style={{background:'var(--surface-2)',marginBottom:16}}>
          <h4 style={{marginBottom:12}}>New Timesheet</h4>
          <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12,marginBottom:12}}>
            <div className="input-group">
              <label>Employee *</label>
              <select className="input input-sm" value={form.employee_id}
                onChange={e=>setForm(p=>({...p,employee_id:e.target.value}))}>
                <option value="">— Select —</option>
                {employees.map(e=><option key={e.id} value={e.id}>{e.first_name} {e.last_name}</option>)}
              </select>
            </div>
            <div className="input-group">
              <label>Period Start *</label>
              <input className="input input-sm" type="date" value={form.period_start}
                onChange={e=>setForm(p=>({...p,period_start:e.target.value}))}/>
            </div>
            <div className="input-group">
              <label>Period End *</label>
              <input className="input input-sm" type="date" value={form.period_end}
                onChange={e=>setForm(p=>({...p,period_end:e.target.value}))}/>
            </div>
          </div>
          <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12}}>
            <NF label="Ordinary Hours"       field="ordinary_hours"/>
            <NF label="Overtime 1.5x Hours"  field="overtime_hours_1_5x"/>
            <NF label="Overtime 2x Hours"    field="overtime_hours_2x"/>
            <NF label="Public Holiday Hours" field="public_holiday_hours"/>
            <NF label="Annual Leave Hours"   field="annual_leave_hours"/>
            <NF label="Sick Leave Hours"     field="sick_leave_hours"/>
            <NF label="LSL Hours"            field="long_service_leave_hours"/>
            <NF label="Unpaid Leave Hours"   field="unpaid_leave_hours"/>
          </div>
          <div style={{display:'flex',gap:8,marginTop:12}}>
            <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
              {saving?'Saving…':<><Check size={13}/> Save</>}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={()=>setShowAdd(false)}>Cancel</button>
          </div>
        </div>
      )}

      {timesheets.length===0
        ? <div className="empty-state" style={{padding:40}}><p>No timesheets yet.</p></div>
        : <table className="data-table">
            <thead><tr>
              <th>Employee</th><th>Period</th><th style={{textAlign:'right'}}>Ord Hrs</th>
              <th style={{textAlign:'right'}}>OT Hrs</th><th>Status</th><th>Actions</th>
            </tr></thead>
            <tbody>
              {timesheets.map(t=>(
                <tr key={t.id}>
                  <td>{empName(t.employee_id)}</td>
                  <td style={{fontSize:'.78rem'}}>{t.period_start} → {t.period_end}</td>
                  <td style={{textAlign:'right',fontFamily:'var(--font-mono)'}}>{t.ordinary_hours}</td>
                  <td style={{textAlign:'right',fontFamily:'var(--font-mono)'}}>{(t.overtime_hours_1_5x||0)+(t.overtime_hours_2x||0)}</td>
                  <td>
                    <span style={{
                      padding:'2px 8px',borderRadius:100,fontSize:'.72rem',fontWeight:700,
                      background:t.status==='approved'?'#dcfce7':t.status==='submitted'?'#dbeafe':'var(--surface-2)',
                      color:t.status==='approved'?'#16a34a':t.status==='submitted'?'#1d4ed8':'var(--text-3)',
                    }}>{t.status}</span>
                  </td>
                  <td>
                    {t.status!=='approved' && (
                      <button className="btn btn-outline btn-xs" onClick={()=>handleApprove(t.id)}>
                        <Check size={11}/> Approve
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
      }
    </div>
  )
}

// ── Payroll Runs Tab ──────────────────────────────────────────────────────────
function RunsTab({ userId, onDone }) {
  const [runs,    setRuns]    = useState([])
  const [showAdd, setShowAdd] = useState(false)
  const [form,    setForm]    = useState({
    run_name:'', pay_frequency:'fortnightly',
    period_start:'', period_end:'', pay_date:'', notes:'',
  })
  const [processing, setProcessing] = useState(null)
  const [saving,     setSaving]     = useState(false)
  const [expanded,   setExpanded]   = useState({})
  const [runDetail,  setRunDetail]  = useState({})

  const load = async () => {
    try { const r = await api.getRuns(userId); setRuns(r.data||[]) } catch {}
  }
  useEffect(()=>{ load() },[userId])

  const handleCreate = async () => {
    if (!form.run_name||!form.period_start||!form.period_end) { toast.error('Fill required fields'); return }
    setSaving(true)
    try { await api.createRun({...form,user_id:userId}); toast.success('Run created'); setShowAdd(false); load() }
    catch(e) { toast.error(e.response?.data?.detail||'Failed') }
    finally { setSaving(false) }
  }

  const handleProcess = async (id) => {
    if (!confirm('Process this payroll run? This will calculate pay for all active employees.')) return
    setProcessing(id)
    try {
      const r = await api.processRun(id)
      toast.success(`✓ ${r.data.employee_count} payslips generated · Gross: ${fmtAUD(r.data.total_gross)}`)
      load(); onDone()
    } catch(e) { toast.error(e.response?.data?.detail||'Processing failed') }
    finally { setProcessing(null) }
  }

  const handleExpand = async (id) => {
    setExpanded(p=>({...p,[id]:!p[id]}))
    if (!runDetail[id]) {
      try { const r = await api.getRun(id); setRunDetail(p=>({...p,[id]:r.data})) } catch {}
    }
  }

  const SC = ({s}) => {
    const m = {completed:'#dcfce7|#16a34a',processing:'#dbeafe|#1d4ed8',
               pending:'#fef3c7|#92400e',failed:'#fee2e2|#991b1b'}
    const [bg,col] = (m[s]||'var(--surface-2)|var(--text-3)').split('|')
    return <span style={{padding:'2px 10px',borderRadius:100,fontSize:'.72rem',fontWeight:700,background:bg,color:col}}>{s}</span>
  }

  return (
    <div style={{padding:24}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
        <h3>Payroll Runs ({runs.length})</h3>
        <button className="btn btn-primary btn-sm" onClick={()=>setShowAdd(s=>!s)}><Plus size={13}/> New Run</button>
      </div>

      {showAdd && (
        <div className="card card-flat" style={{background:'var(--surface-2)',marginBottom:16}}>
          <h4 style={{marginBottom:12}}>New Payroll Run</h4>
          <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12}}>
            {[['run_name','Run Name *','text'],['period_start','Period Start *','date'],
              ['period_end','Period End *','date'],['pay_date','Pay Date','date']].map(([f,l,t])=>(
              <div key={f} className="input-group">
                <label>{l}</label>
                <input className="input input-sm" type={t} value={form[f]||''}
                  onChange={e=>setForm(p=>({...p,[f]:e.target.value}))}/>
              </div>
            ))}
            <div className="input-group">
              <label>Pay Frequency</label>
              <select className="input input-sm" value={form.pay_frequency}
                onChange={e=>setForm(p=>({...p,pay_frequency:e.target.value}))}>
                {PAY_FREQS.map(f=><option key={f}>{f}</option>)}
              </select>
            </div>
          </div>
          <div style={{display:'flex',gap:8,marginTop:12}}>
            <button className="btn btn-primary btn-sm" onClick={handleCreate} disabled={saving}>
              {saving?'Saving…':<><Check size={13}/> Create</>}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={()=>setShowAdd(false)}>Cancel</button>
          </div>
        </div>
      )}

      {runs.length===0
        ? <div className="empty-state" style={{padding:40}}><p>No payroll runs yet.</p></div>
        : <div style={{display:'flex',flexDirection:'column',gap:8}}>
            {runs.map(run=>(
              <div key={run.id} style={{border:'1px solid var(--border)',borderRadius:'var(--r-lg)',overflow:'hidden'}}>
                <div style={{display:'flex',alignItems:'center',gap:12,padding:'14px 16px',
                  background:'var(--surface-2)',cursor:'pointer'}}
                  onClick={()=>handleExpand(run.id)}>
                  <div style={{flex:1}}>
                    <div style={{fontWeight:700}}>{run.run_name}</div>
                    <div style={{fontSize:'.78rem',color:'var(--text-3)'}}>
                      {run.period_start} → {run.period_end} · {run.pay_frequency}
                    </div>
                  </div>
                  <SC s={run.status}/>
                  {run.status==='completed' && (
                    <div style={{display:'flex',gap:16,fontSize:'.82rem',fontFamily:'var(--font-mono)'}}>
                      <span>Gross: <strong>{fmtAUD(run.total_gross)}</strong></span>
                      <span>Tax: <strong>{fmtAUD(run.total_tax)}</strong></span>
                      <span>Net: <strong>{fmtAUD(run.total_net)}</strong></span>
                      <span>Super: <strong>{fmtAUD(run.total_super)}</strong></span>
                    </div>
                  )}
                  {run.status==='pending' && (
                    <button className="btn btn-primary btn-sm"
                      onClick={e=>{e.stopPropagation();handleProcess(run.id)}}
                      disabled={processing===run.id}>
                      {processing===run.id?<span className="spinner spinner-sm"/>:<Play size={13}/>}
                      {processing===run.id?' Processing…':' Process'}
                    </button>
                  )}
                </div>
                {expanded[run.id] && runDetail[run.id] && (
                  <div style={{padding:16,overflowX:'auto'}}>
                    <table className="data-table" style={{fontSize:'.78rem'}}>
                      <thead><tr>
                        <th>Employee</th><th>Ord Hrs</th>
                        <th style={{textAlign:'right'}}>Gross</th>
                        <th style={{textAlign:'right'}}>PAYG Tax</th>
                        <th style={{textAlign:'right'}}>Net Pay</th>
                        <th style={{textAlign:'right'}}>Super</th>
                      </tr></thead>
                      <tbody>
                        {(runDetail[run.id].payslips||[]).map(p=>(
                          <tr key={p.id}>
                            <td style={{fontWeight:600}}>{p.full_name}</td>
                            <td>{p.ordinary_hours}</td>
                            <td style={{textAlign:'right',fontFamily:'var(--font-mono)'}}>{fmtAUD(p.gross_earnings)}</td>
                            <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:'var(--danger)'}}>{fmtAUD(p.payg_tax)}</td>
                            <td style={{textAlign:'right',fontFamily:'var(--font-mono)',fontWeight:700,color:'var(--success)'}}>{fmtAUD(p.net_pay)}</td>
                            <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:'var(--brand)'}}>{fmtAUD(p.super_guarantee)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
          </div>
      }
    </div>
  )
}

// ── Payslips Tab ──────────────────────────────────────────────────────────────
function PayslipsTab() {
  const [payslips, setPayslips] = useState([])
  const [selected, setSelected] = useState(null)
  const [filter,   setFilter]   = useState('')

  useEffect(()=>{
    api.getPayslips().then(r=>setPayslips(r.data||[])).catch(()=>{})
  },[])

  const shown = payslips.filter(p=>!filter||p.full_name?.toLowerCase().includes(filter.toLowerCase()))

  const Row = ({l,v,hi}) => (
    <div style={{display:'flex',justifyContent:'space-between',padding:'6px 0',borderBottom:'1px solid var(--border)'}}>
      <span style={{color:'var(--text-3)',fontSize:'.82rem'}}>{l}</span>
      <span style={{color:hi||'var(--text-1)',fontWeight:hi?700:400,fontFamily:'var(--font-mono)',fontSize:'.82rem'}}>{v}</span>
    </div>
  )

  return (
    <div style={{padding:24}}>
      <h3 style={{marginBottom:12}}>Payslips ({payslips.length})</h3>
      <input className="input input-sm" style={{marginBottom:12,maxWidth:260}} placeholder="Filter by name…"
        value={filter} onChange={e=>setFilter(e.target.value)}/>

      <div style={{display:'grid',gridTemplateColumns:selected?'1fr 380px':'1fr',gap:16}}>
        <div style={{overflowX:'auto'}}>
          <table className="data-table" style={{fontSize:'.78rem'}}>
            <thead><tr>
              <th>Employee</th><th>Period</th>
              <th style={{textAlign:'right'}}>Gross</th>
              <th style={{textAlign:'right'}}>Tax</th>
              <th style={{textAlign:'right'}}>Net</th>
              <th style={{textAlign:'right'}}>Super</th>
            </tr></thead>
            <tbody>
              {shown.map(p=>(
                <tr key={p.id} onClick={()=>setSelected(p===selected?null:p)}
                  style={{cursor:'pointer',background:p===selected?'var(--brand-xlight)':undefined}}>
                  <td style={{fontWeight:600}}>{p.full_name}</td>
                  <td>{p.period_start} → {p.period_end}</td>
                  <td style={{textAlign:'right',fontFamily:'var(--font-mono)'}}>{fmtAUD(p.gross_earnings)}</td>
                  <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:'var(--danger)'}}>{fmtAUD(p.total_tax)}</td>
                  <td style={{textAlign:'right',fontFamily:'var(--font-mono)',fontWeight:700,color:'var(--success)'}}>{fmtAUD(p.net_pay)}</td>
                  <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:'var(--brand)'}}>{fmtAUD(p.super_guarantee)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {selected && (
          <div style={{border:'1px solid var(--border)',borderRadius:'var(--r-lg)',padding:20,
            background:'var(--surface)',height:'fit-content',position:'sticky',top:0}}>
            <div style={{display:'flex',justifyContent:'space-between',marginBottom:16}}>
              <div>
                <div style={{fontWeight:700,fontSize:'1rem'}}>{selected.full_name}</div>
                <div style={{fontSize:'.75rem',color:'var(--text-3)'}}>{selected.period_start} → {selected.period_end}</div>
              </div>
              <button onClick={()=>setSelected(null)} style={{background:'none',border:'none',cursor:'pointer',color:'var(--text-3)'}}>✕</button>
            </div>
            <Row l="Ordinary Pay"   v={fmtAUD(selected.ordinary_pay)}/>
            {selected.overtime_pay_1_5x>0 && <Row l="Overtime 1.5x" v={fmtAUD(selected.overtime_pay_1_5x)}/>}
            {selected.overtime_pay_2x>0   && <Row l="Overtime 2x"   v={fmtAUD(selected.overtime_pay_2x)}/>}
            {selected.annual_leave_pay>0  && <Row l="Annual Leave"  v={fmtAUD(selected.annual_leave_pay)}/>}
            {selected.sick_leave_pay>0    && <Row l="Sick Leave"    v={fmtAUD(selected.sick_leave_pay)}/>}
            <Row l="Gross Earnings" v={fmtAUD(selected.gross_earnings)} hi="var(--text-1)"/>
            <div style={{height:8}}/>
            <Row l="PAYG Tax"       v={fmtAUD(selected.payg_tax)} hi="var(--danger)"/>
            <Row l="Medicare Levy"  v={fmtAUD(selected.medicare_levy)}/>
            <Row l="Total Tax"      v={fmtAUD(selected.total_tax)} hi="var(--danger)"/>
            <div style={{height:8}}/>
            <Row l="Net Pay"        v={fmtAUD(selected.net_pay)} hi="var(--success)"/>
            <div style={{height:8}}/>
            <Row l="Super (11%)"    v={fmtAUD(selected.super_guarantee)} hi="var(--brand)"/>
            <Row l="Super Fund"     v={selected.super_fund_name||'—'}/>
            <div style={{height:8}}/>
            <Row l="YTD Gross"      v={fmtAUD(selected.ytd_gross)}/>
            <Row l="YTD Tax"        v={fmtAUD(selected.ytd_tax)}/>
            <Row l="YTD Super"      v={fmtAUD(selected.ytd_super)}/>
          </div>
        )}
      </div>
    </div>
  )
}

// ── STP / Compliance Tab ──────────────────────────────────────────────────────
function ComplianceTab({ userId }) {
  const [submissions, setSubmissions] = useState([])
  const [runs,        setRuns]        = useState([])
  const [selectedRun, setSelectedRun] = useState('')
  const [abn,         setAbn]         = useState('')
  const [preparing,   setPreparing]   = useState(false)
  const [submitting,  setSubmitting]  = useState(null)

  const load = async () => {
    try {
      const [sr, rr] = await Promise.all([api.getStpList(), api.getRuns(userId)])
      setSubmissions(sr.data||[])
      setRuns((rr.data||[]).filter(r=>r.status==='completed'))
    } catch {}
  }
  useEffect(()=>{ load() },[userId])

  const handlePrepare = async () => {
    if (!selectedRun) { toast.error('Select a payroll run'); return }
    if (!abn)         { toast.error('Enter your ABN'); return }
    setPreparing(true)
    try {
      await api.prepareStp({payroll_run_id:selectedRun, abn})
      toast.success('STP submission prepared ✓'); load()
    } catch(e) { toast.error(e.response?.data?.detail||'Failed') }
    finally { setPreparing(false) }
  }

  const handleSubmit = async (id) => {
    if (!confirm('Submit to ATO? (Simulation — no real ATO connection)')) return
    setSubmitting(id)
    try { await api.submitStp(id); toast.success('Submitted to ATO ✓'); load() }
    catch { toast.error('Submission failed') }
    finally { setSubmitting(null) }
  }

  const SC = ({s}) => {
    const m = {validated:'#dbeafe|#1d4ed8',submitted:'#dcfce7|#16a34a',
               draft:'var(--surface-2)|var(--text-3)',accepted:'#dcfce7|#166534'}
    const [bg,col]=(m[s]||'var(--surface-2)|var(--text-3)').split('|')
    return <span style={{padding:'2px 8px',borderRadius:100,fontSize:'.72rem',fontWeight:700,background:bg,color:col}}>{s}</span>
  }

  return (
    <div style={{padding:24}}>
      <h3 style={{marginBottom:16}}>STP Phase 2 / ATO Compliance</h3>

      <div className="card card-flat" style={{background:'var(--surface-2)',marginBottom:20}}>
        <h4 style={{marginBottom:12}}>Prepare STP Submission</h4>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr auto',gap:12,alignItems:'flex-end'}}>
          <div className="input-group">
            <label>Payroll Run</label>
            <select className="input input-sm" value={selectedRun} onChange={e=>setSelectedRun(e.target.value)}>
              <option value="">— Select completed run —</option>
              {runs.map(r=><option key={r.id} value={r.id}>{r.run_name} ({r.period_start})</option>)}
            </select>
          </div>
          <div className="input-group">
            <label>ABN</label>
            <input className="input input-sm" value={abn} onChange={e=>setAbn(e.target.value)}
              placeholder="12 345 678 901"/>
          </div>
          <button className="btn btn-primary btn-sm" onClick={handlePrepare} disabled={preparing}>
            {preparing?'Preparing…':'Prepare STP'}
          </button>
        </div>
      </div>

      <div style={{background:'#fef3c7',borderRadius:'var(--r-md)',padding:'10px 14px',
        marginBottom:16,fontSize:'.78rem',color:'#92400e',border:'1px solid #fde68a'}}>
        ⚠️ STP submission is simulated — no real ATO connection. In production, connect to your STP-enabled software.
      </div>

      {submissions.length===0
        ? <div className="empty-state" style={{padding:32}}><p>No STP submissions yet.</p></div>
        : <table className="data-table">
            <thead><tr>
              <th>Run Period</th><th>ABN</th><th style={{textAlign:'right'}}>Employees</th>
              <th style={{textAlign:'right'}}>Total Gross</th><th>Status</th>
              <th>ATO Reference</th><th>Actions</th>
            </tr></thead>
            <tbody>
              {submissions.map(s=>(
                <tr key={s.id}>
                  <td style={{fontSize:'.78rem'}}>{s.period_start} → {s.period_end}</td>
                  <td style={{fontFamily:'var(--font-mono)',fontSize:'.78rem'}}>{s.abn}</td>
                  <td style={{textAlign:'right'}}>{s.employee_count}</td>
                  <td style={{textAlign:'right',fontFamily:'var(--font-mono)',fontWeight:600}}>{fmtAUD(s.total_gross)}</td>
                  <td><SC s={s.status}/></td>
                  <td style={{fontFamily:'var(--font-mono)',fontSize:'.72rem',color:'var(--text-3)'}}>{s.ato_reference||'—'}</td>
                  <td>
                    {s.status==='validated' && (
                      <button className="btn btn-primary btn-xs" onClick={()=>handleSubmit(s.id)}
                        disabled={submitting===s.id}>
                        {submitting===s.id?'…':'Submit to ATO'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
      }
    </div>
  )
}
