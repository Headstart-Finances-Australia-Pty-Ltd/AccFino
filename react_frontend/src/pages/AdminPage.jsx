import React, { useEffect, useState } from 'react'
import { changePassword, mlStatus, mlTrain, mlSampleCsv, rdrList, rdrCreate, rdrUpdate, rdrDelete, rdrTest, coaAccounts } from '../lib/api.js'
import { useAuth } from '../hooks/useAuth.jsx'
import { Trash2, Key, Brain, Plus, Check, X, Play, Pencil } from 'lucide-react'
import toast from 'react-hot-toast'

const ALLOWED_GST = ['','GST on Expenses','GST on Capital','GST on Income','GST Free Expenses','GST Free Income','BAS Excluded']
const DIRECTION_OPTIONS = [
  { value: '', label: 'Any direction' },
  { value: 'debit_only', label: '🟡 Outgoing only (debit)' },
  { value: 'credit_only', label: '🔵 Incoming only (credit)' },
]

const BLANK_FORM = { name:'', priority:100, keywords:'', gl:'', gst:'', direction:'' }

export default function AdminPage() {
  const { user } = useAuth()
  const [tab,       setTab]      = useState('rdr')
  const [pwForm,    setPwForm]   = useState({old_password:'',new_password:''})
  const [mlStat,    setMlStat]   = useState(null)
  const [training,  setTraining] = useState(false)
  const [trainRes,  setTrainRes] = useState(null)
  const [rules,     setRules]    = useState([])
  const [glList,    setGlList]   = useState([])
  const [form,      setForm]     = useState(BLANK_FORM)
  const [editId,    setEditId]   = useState(null)
  const [testInput, setTestInput]= useState({description:'',debit:0,credit:0})
  const [testResult,setTestResult]=useState(null)
  const fileRef = React.useRef()

  useEffect(()=>{
    mlStatus().then(r=>setMlStat(r.data)).catch(()=>{})
    loadRules()
    coaAccounts().then(r=>setGlList(r.data||[])).catch(()=>{})
  },[])

  const loadRules = () => rdrList().then(r=>setRules(r.data||[])).catch(()=>{})

  const set = k => e => setForm(f=>({...f,[k]:e.target.value}))

  const saveRule = async () => {
    if (!form.gl && !form.gst) { toast.error('Set at least GL Account or GST Category'); return }
    const keywords = form.keywords.split(',').map(k=>k.trim().toLowerCase()).filter(Boolean)
    if (!keywords.length) { toast.error('Add at least one keyword'); return }

    const cond = { contains_any: keywords }
    if (form.direction === 'debit_only')  cond.debit_only  = true
    if (form.direction === 'credit_only') cond.credit_only = true

    const rule = {
      id:                editId || `rule_${Date.now()}`,
      name:              form.name || keywords[0],
      priority:          parseInt(form.priority) || 100,
      if:                cond,
      then:              form.gl,
      then_gst_category: form.gst,
    }
    try {
      if (editId) {
        const { data } = await rdrUpdate(editId, rule)
        setRules(r=>r.map(x=>x.id===editId?data:x))
        toast.success('Rule updated')
      } else {
        const { data } = await rdrCreate(rule)
        setRules(r=>[data,...r])
        toast.success('Rule created — will apply to all future reconciliations')
      }
      setForm(BLANK_FORM); setEditId(null)
    } catch { toast.error('Save failed') }
  }

  const startEdit = rule => {
    const dir = rule.if?.debit_only ? 'debit_only' : rule.if?.credit_only ? 'credit_only' : ''
    setForm({
      name:      rule.name || '',
      priority:  rule.priority || 100,
      keywords:  (rule.if?.contains_any||[]).join(', '),
      gl:        typeof rule.then === 'string' ? rule.then : '',
      gst:       rule.then_gst_category || rule.gst_category || '',
      direction: dir,
    })
    setEditId(rule.id)
    setTab('rdr')
    window.scrollTo({top:0,behavior:'smooth'})
  }

  const delRule = async id => {
    if (!confirm('Delete this rule?')) return
    try { await rdrDelete(id); setRules(r=>r.filter(x=>x.id!==id)); toast.success('Deleted') }
    catch { toast.error('Delete failed') }
  }

  const runTest = async () => {
    try {
      const { data } = await rdrTest(testInput)
      setTestResult(data)
    } catch { toast.error('Test failed') }
  }

  const changePw = async e => {
    e.preventDefault()
    try { await changePassword({email:user.email,...pwForm}); toast.success('Password updated'); setPwForm({old_password:'',new_password:''}) }
    catch { toast.error('Failed — check current password') }
  }

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

  const dirLabel = r => r.if?.debit_only ? '🟡 Out' : r.if?.credit_only ? '🔵 In' : '↔'

  return (
    <div className="fade-in">
      <div style={{marginBottom:22}}>
        <h1>🧠 ML Classifier & RDR Rules</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
          RDR rules take priority over TF-IDF — edit any transaction's GL Account to auto-create a rule.
        </p>
      </div>

      <div className="tabs-bar" style={{marginBottom:20}}>
        {[['rdr','📋 RDR Rules'],['ml','🧠 ML Training'],['password','🔑 Password']].map(([k,label])=>(
          <button key={k} className={`tab-btn${tab===k?' active':''}`} onClick={()=>setTab(k)}>{label}</button>
        ))}
      </div>

      {/* ── RDR Rules ── */}
      {tab==='rdr' && (
        <div style={{display:'grid',gridTemplateColumns:'1fr 380px',gap:20,alignItems:'start'}}>
          <div>
            {/* Rule editor */}
            <div className="card" style={{marginBottom:16}}>
              <h3 style={{marginBottom:14}}>{editId ? '✏️ Edit Rule' : '➕ New Rule'}
                <span style={{fontSize:'.78rem',fontWeight:400,color:'var(--text-3)',marginLeft:8}}>
                  Rules fire before TF-IDF — higher priority wins
                </span>
              </h3>
              <div style={{display:'grid',gridTemplateColumns:'2fr 1fr',gap:10,marginBottom:10}}>
                <div className="input-group">
                  <label>Rule Name</label>
                  <input className="input" value={form.name} onChange={set('name')} placeholder="e.g. Uber rides"/>
                </div>
                <div className="input-group">
                  <label>Priority</label>
                  <input className="input" type="number" value={form.priority} onChange={set('priority')}/>
                </div>
              </div>
              <div className="input-group" style={{marginBottom:10}}>
                <label>Keywords — IF description contains any <span style={{fontWeight:400,color:'var(--text-3)'}}>(comma-separated)</span></label>
                <input className="input" value={form.keywords} onChange={set('keywords')}
                  placeholder="uber, didi, taxi, ride share"/>
              </div>
              <div style={{display:'grid',gridTemplateColumns:'2fr 2fr 1fr',gap:10,marginBottom:14}}>
                <div className="input-group">
                  <label>GL Account (THEN)</label>
                  <select className="input" value={form.gl} onChange={set('gl')}>
                    <option value="">— Select —</option>
                    {glList.map(g=>(
                      <option key={g.name} value={g.name}>{g.name} ({g.type})</option>
                    ))}
                  </select>
                </div>
                <div className="input-group">
                  <label>GST Category (THEN)</label>
                  <select className="input" value={form.gst} onChange={set('gst')}>
                    {ALLOWED_GST.map(g=><option key={g} value={g}>{g||'— Same as COA —'}</option>)}
                  </select>
                </div>
                <div className="input-group">
                  <label>Direction</label>
                  <select className="input" value={form.direction} onChange={set('direction')}>
                    {DIRECTION_OPTIONS.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
              </div>
              <div style={{display:'flex',gap:8}}>
                <button className="btn btn-primary btn-sm" onClick={saveRule}>
                  <Check size={13}/> {editId ? 'Update Rule' : 'Save Rule'}
                </button>
                {editId && (
                  <button className="btn btn-ghost btn-sm" onClick={()=>{setForm(BLANK_FORM);setEditId(null)}}>
                    <X size={13}/> Cancel
                  </button>
                )}
              </div>
            </div>

            {/* Rules table */}
            <div className="card" style={{padding:0,overflow:'hidden'}}>
              <div style={{padding:'12px 18px',borderBottom:'1px solid var(--border)',display:'flex',alignItems:'center',gap:10}}>
                <h3>Active Rules</h3>
                <span style={{background:'var(--surface-3)',borderRadius:100,padding:'1px 8px',fontSize:'.72rem',fontWeight:700}}>{rules.length}</span>
                <span style={{marginLeft:'auto',fontSize:'.75rem',color:'var(--text-3)'}}>sorted by priority</span>
              </div>
              {rules.length === 0
                ? <div style={{padding:36,textAlign:'center',color:'var(--text-3)'}}>
                    No rules yet. Create one above or edit a GL Account in Reconciliation.
                  </div>
                : <table className="data-table">
                    <thead>
                      <tr>
                        <th style={{width:60}}>Pri.</th>
                        <th>Name</th>
                        <th>Keywords</th>
                        <th>Dir.</th>
                        <th>GL Account</th>
                        <th>GST</th>
                        <th style={{width:72}}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...rules].sort((a,b)=>(b.priority||0)-(a.priority||0)).map(r=>(
                        <tr key={r.id}>
                          <td style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'.82rem'}}>{r.priority||0}</td>
                          <td style={{fontWeight:600,fontSize:'.875rem'}}>{r.name||r.id}</td>
                          <td style={{fontSize:'.75rem',color:'var(--text-2)'}}>{(r.if?.contains_any||[]).slice(0,4).join(', ')}{(r.if?.contains_any||[]).length>4?'…':''}</td>
                          <td style={{fontSize:'.78rem'}}>{dirLabel(r)}</td>
                          <td><span className="badge badge-neutral" style={{fontSize:'.75rem'}}>{r.then||'—'}</span></td>
                          <td style={{fontSize:'.72rem',color:'var(--text-3)'}}>{r.then_gst_category||'—'}</td>
                          <td>
                            <div style={{display:'flex',gap:4}}>
                              <button className="btn btn-ghost btn-icon btn-sm" onClick={()=>startEdit(r)} title="Edit"><Pencil size={13}/></button>
                              <button className="btn btn-ghost btn-icon btn-sm" onClick={()=>delRule(r.id)} title="Delete"
                                style={{color:'var(--text-3)'}} onMouseEnter={e=>e.currentTarget.style.color='var(--danger)'}
                                onMouseLeave={e=>e.currentTarget.style.color='var(--text-3)'}>
                                <Trash2 size={13}/>
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
              }
            </div>
          </div>

          {/* Test panel */}
          <div style={{display:'flex',flexDirection:'column',gap:16}}>
            <div className="card">
              <h3 style={{marginBottom:14}}><Play size={15} style={{display:'inline',marginRight:6,verticalAlign:'middle'}}/>Test a Transaction</h3>
              <div style={{display:'flex',flexDirection:'column',gap:10}}>
                <div className="input-group">
                  <label>Description</label>
                  <input className="input" value={testInput.description} onChange={e=>setTestInput(t=>({...t,description:e.target.value}))} placeholder="UBER *TRIP SYDNEY"/>
                </div>
                <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
                  <div className="input-group">
                    <label>Debit $</label>
                    <input className="input" type="number" min="0" value={testInput.debit} onChange={e=>setTestInput(t=>({...t,debit:parseFloat(e.target.value)||0}))}/>
                  </div>
                  <div className="input-group">
                    <label>Credit $</label>
                    <input className="input" type="number" min="0" value={testInput.credit} onChange={e=>setTestInput(t=>({...t,credit:parseFloat(e.target.value)||0}))}/>
                  </div>
                </div>
                <button className="btn btn-outline btn-sm" onClick={runTest}><Play size={13}/> Test Rules</button>
              </div>
              {testResult && (
                <div style={{marginTop:14}}>
                  {testResult.matched
                    ? <div className="alert alert-success" style={{fontSize:'.82rem'}}>
                        <strong>✅ Matched: {testResult.rule?.name||testResult.rule?.id}</strong>
                        <div style={{marginTop:4}}>
                          GL: <strong>{testResult.rule?.then||'—'}</strong><br/>
                          GST: {testResult.rule?.then_gst_category||'—'}<br/>
                          Priority: {testResult.rule?.priority}
                        </div>
                      </div>
                    : <div className="alert alert-warning" style={{fontSize:'.82rem'}}>❌ No RDR rule matched — TF-IDF will classify this.</div>
                  }
                </div>
              )}
            </div>

            <div className="card" style={{fontSize:'.82rem',color:'var(--text-2)',lineHeight:1.7}}>
              <h3 style={{marginBottom:10,fontSize:'.9rem'}}>💡 How to add a rule</h3>
              <ol style={{paddingLeft:18,margin:0}}>
                <li>Go to <strong>Reconciliation → Output</strong></li>
                <li>Change any row's <strong>GL Account</strong></li>
                <li>Click <strong>Save as Rule</strong> to auto-create an RDR rule</li>
                <li>Or create rules here manually</li>
              </ol>
              <div style={{marginTop:10,padding:'8px 10px',background:'var(--surface-2)',borderRadius:'var(--r-md)',fontSize:'.78rem'}}>
                RDR rules fire <strong>before TF-IDF</strong>. Higher priority = checked first. Use direction filter to restrict to incoming or outgoing only.
              </div>
            </div>
          </div>
        </div>
      )}

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
              </div>
            )}
          </div>
          <div className="card">
            <h3 style={{marginBottom:12}}>How it works</h3>
            <button className="btn btn-outline btn-sm" onClick={downloadSample}>⬇ Download sample CSV</button>
          </div>
        </div>
      )}

      {/* ── Password ── */}
      {tab==='password' && (
        <div style={{maxWidth:400}}>
          <div className="card">
            <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:18,paddingBottom:14,borderBottom:'1px solid var(--border)'}}>
              <Key size={18} color="var(--brand)"/><h3>Change Password</h3>
            </div>
            <form onSubmit={changePw} style={{display:'flex',flexDirection:'column',gap:14}}>
              <div className="input-group"><label>Current Password</label><input className="input" type="password" value={pwForm.old_password} onChange={e=>setPwForm(p=>({...p,old_password:e.target.value}))} required/></div>
              <div className="input-group"><label>New Password</label><input className="input" type="password" value={pwForm.new_password} onChange={e=>setPwForm(p=>({...p,new_password:e.target.value}))} required/></div>
              <button className="btn btn-primary" type="submit">Update Password</button>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

// Export startEdit so OutputPanel can open Admin page pre-filled
export { }
