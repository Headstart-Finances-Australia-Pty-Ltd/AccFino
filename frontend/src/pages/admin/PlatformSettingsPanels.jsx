import React, { useEffect, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import { Database, Cloud, Mail, CalendarClock, Video, Eye, EyeOff, Trash2, CheckCircle2, XCircle, KeyRound, Plus } from 'lucide-react'
import * as api from '../../lib/api.js'
import { useModuleVisibility } from '../../hooks/useModuleVisibility.jsx'

// ── shared bits ──────────────────────────────────────────────────────────

function ResultBanner({ result }) {
  if (!result) return null
  return (
    <div className={`alert ${result.ok ? 'alert-success' : 'alert-warning'}`} style={{ marginTop: 10 }}>
      {result.ok ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
      <span>{result.message}</span>
    </div>
  )
}

function SavedRow({ row, onDelete }) {
  return (
    <div className="flex items-center gap-1" style={{ padding: '7px 10px', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', marginBottom: 6 }}>
      <span className="text-sm fw-600" style={{ minWidth: 140 }}>{row.key_name}</span>
      <span className="mono text-sm text-muted">{row.key_preview || '—'}</span>
      <div className="flex-1" />
      <button className="btn btn-ghost btn-xs" onClick={() => onDelete(row.id)} title="Remove"><Trash2 size={13} /></button>
    </div>
  )
}

// Loads every saved setting for one `service` and offers a save/delete helper.
function useServiceSettings(service) {
  const [rows, setRows] = useState([])
  const load = () => api.platformSettings(service).then(r => setRows(r.data)).catch(() => {})
  useEffect(() => { load() }, [service])
  const save = async (key_name, key_value) => {
    await api.savePlatformSetting({ service, key_name, key_value })
  }
  const remove = async id => {
    try { await api.deletePlatformSetting(id); toast.success('Removed'); load() }
    catch (e) { toast.error(api.errMsg ? api.errMsg(e) : 'Could not remove') }
  }
  const val = key_name => rows.find(r => r.key_name === key_name)?.key_preview || ''
  return { rows, load, save, remove, val }
}

// ── Groq Key Pool ────────────────────────────────────────────────────────
function GroqKeyPoolPanel() {
  const [poolKeys, setPoolKeys] = useState([])
  const [newPoolKey, setNewPoolKey] = useState({ key_value:'', model:'' })
  const [fetchedModels, setFetchedModels] = useState(null)
  const [fetchingModels, setFetchingModels] = useState(false)
  const [modelsFetchError, setModelsFetchError] = useState('')
  const autoFetchTimer = useRef(null)

  const loadPool = () => api.groqPoolList().then(r=>setPoolKeys(r.data||[])).catch(()=>{})
  useEffect(() => { loadPool() }, [])

  const fetchModelsForKey = async (keyOverride) => {
    const key = (keyOverride ?? newPoolKey.key_value).trim()
    if (!key) { setModelsFetchError('Enter the API key above first.'); return }
    setFetchingModels(true); setModelsFetchError(''); setFetchedModels(null)
    try {
      const { data } = await api.groqPoolListModels(key)
      setFetchedModels(data.models || [])
    } catch (e) {
      setModelsFetchError(e.response?.data?.detail || 'Could not fetch models for this key.')
    } finally {
      setFetchingModels(false)
    }
  }

  // Auto-fetches shortly after the user stops typing/pasting a
  // plausible-looking key — mirrors Groq's own console, no extra click needed.
  useEffect(() => {
    if (autoFetchTimer.current) clearTimeout(autoFetchTimer.current)
    const key = newPoolKey.key_value.trim()
    if (key.length < 20) return
    autoFetchTimer.current = setTimeout(() => fetchModelsForKey(key), 600)
    return () => { if (autoFetchTimer.current) clearTimeout(autoFetchTimer.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newPoolKey.key_value])

  const addPoolKey = async () => {
    const key_value = newPoolKey.key_value.trim()
    if (!key_value) return
    try {
      await api.groqPoolAdd({ key_value, model: newPoolKey.model.trim() || undefined })
      setNewPoolKey({ key_value:'', model:'' }); setFetchedModels(null); setModelsFetchError('')
      loadPool()
      toast.success('Key added to pool')
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to add key') }
  }

  const togglePoolKey = async (id, is_active) => {
    try { await api.groqPoolUpdate(id, { is_active }); loadPool() }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed to update key') }
  }

  const removePoolKey = async id => {
    if (!confirm('Remove this key from the pool?')) return
    try { await api.groqPoolRemove(id); loadPool(); toast.success('Key removed') }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed to remove key') }
  }

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 style={{marginBottom:8}}><KeyRound size={16} style={{display:'inline',marginRight:6,verticalAlign:'middle'}}/>Groq Key Pool — scale capacity automatically</h3>
      <p style={{fontSize:'.8rem',color:'var(--text-2)',marginBottom:16,lineHeight:1.6}}>
        Add multiple Groq keys here (separate accounts give real added throughput —
        Groq's rate limits apply per account, not per key). AccFino automatically spreads
        load across whichever keys are healthy, and routes around any that are temporarily
        rate-limited, recovering them automatically once they cool down. Used by the
        transaction/bank-classification LLM calls (e.g. <code>rdr.py</code>).
      </p>

      {poolKeys.length > 0 && (
        <div style={{marginBottom:20}}>
          <div style={{fontSize:'.72rem',fontWeight:700,color:'var(--text-3)',marginBottom:8,textTransform:'uppercase',letterSpacing:'.04em'}}>
            Keys in pool ({poolKeys.length})
          </div>
          <div style={{display:'flex',flexDirection:'column',gap:8}}>
            {(() => {
              const byAddedAsc = [...poolKeys].sort((a,b)=>new Date(a.added_at||0)-new Date(b.added_at||0))
              const numberOf = new Map(byAddedAsc.map((k,i)=>[k.id,i+1]))
              return poolKeys.map(k => (
                <div key={k.id} style={{display:'flex',alignItems:'center',gap:10,padding:'8px 12px',border:'1px solid var(--border)',borderRadius:'var(--r-md)',opacity:k.is_active?1:0.5}}>
                  <span style={{display:'flex',alignItems:'center',justifyContent:'center',width:24,height:24,borderRadius:6,flexShrink:0,background:'var(--surface-2)',fontSize:'.7rem',fontWeight:700,color:'var(--text-3)'}}>
                    {numberOf.get(k.id)}
                  </span>
                  <span style={{fontFamily:'var(--font-mono)',fontSize:'.82rem'}}>{k.key_preview}</span>
                  <span style={{fontSize:'.75rem',color:'var(--text-3)'}}>{k.model || 'platform default'}</span>
                  {k.cooldown_until && new Date(k.cooldown_until) > new Date() && (
                    <span style={{fontSize:'.7rem',color:'var(--warning, #f59e0b)'}}>⏳ cooling down</span>
                  )}
                  {!k.is_active && <span style={{fontSize:'.7rem',color:'var(--text-3)'}}>disabled</span>}
                  <div style={{marginLeft:'auto',display:'flex',gap:6}}>
                    <button className="btn btn-ghost btn-sm" onClick={()=>togglePoolKey(k.id, !k.is_active)}>
                      {k.is_active ? 'Disable' : 'Enable'}
                    </button>
                    <button className="btn btn-ghost btn-icon btn-sm" style={{color:'var(--danger)'}} onClick={()=>removePoolKey(k.id)} title="Remove">
                      <Trash2 size={13}/>
                    </button>
                  </div>
                </div>
              ))
            })()}
          </div>
        </div>
      )}

      <div style={{borderTop:'1px solid var(--border)',paddingTop:16}}>
        <div style={{fontSize:'.72rem',fontWeight:700,color:'var(--text-3)',marginBottom:10,textTransform:'uppercase',letterSpacing:'.04em'}}>
          Add a new key — will become Key #{poolKeys.length + 1}
        </div>

        <div className="input-group" style={{marginBottom:8}}>
          <label>API Key</label>
          <input className="input" type="password" placeholder="gsk_…" value={newPoolKey.key_value}
            onChange={e=>{ setNewPoolKey(k=>({...k,key_value:e.target.value})); setFetchedModels(null); setModelsFetchError('') }} />
        </div>

        <div style={{marginBottom:4,display:'flex',alignItems:'center',gap:10,flexWrap:'wrap'}}>
          {fetchingModels && <span style={{fontSize:'.75rem',color:'var(--text-3)'}}>Checking with Groq…</span>}
          {!fetchingModels && fetchedModels && (
            <span style={{fontSize:'.75rem',color:'var(--success)'}}>✓ {fetchedModels.length} models available for this key</span>
          )}
          {!fetchingModels && !fetchedModels && !modelsFetchError && newPoolKey.key_value.trim().length > 0 && (
            <span style={{fontSize:'.75rem',color:'var(--text-3)'}}>Models will load automatically once the key looks complete…</span>
          )}
          <button className="btn btn-ghost btn-sm" onClick={()=>fetchModelsForKey()} disabled={fetchingModels || !newPoolKey.key_value.trim()}>
            {fetchedModels ? 'Refetch' : 'Fetch now'}
          </button>
          {modelsFetchError && <span style={{fontSize:'.75rem',color:'var(--danger)'}}>{modelsFetchError}</span>}
        </div>

        <div className="input-group" style={{marginTop:10,marginBottom:14}}>
          <label>Model</label>
          {fetchedModels ? (
            <select className="input" value={newPoolKey.model} onChange={e=>setNewPoolKey(k=>({...k,model:e.target.value}))}>
              <option value="">Platform default (openai/gpt-oss-20b)</option>
              {fetchedModels.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : (
            <input className="input" value={newPoolKey.model} onChange={e=>setNewPoolKey(k=>({...k,model:e.target.value}))}
              placeholder="leave blank for platform default, or fetch models above to pick from a live list"/>
          )}
        </div>

        <button className="btn btn-primary" onClick={addPoolKey} disabled={!newPoolKey.key_value.trim()}>
          <Plus size={14}/> Add as Key #{poolKeys.length + 1}
        </button>
      </div>
    </div>
  )
}

// ── Database ─────────────────────────────────────────────────────────────
const DB_PROVIDERS = [
  { value: 'postgres', label: 'PostgreSQL', placeholder: 'postgresql://<user>:<password>@<host>:5432/<dbname>' },
  { value: 'xata',     label: 'Xata',       placeholder: 'postgresql://<workspace-id>:<api-key>@<region>.sql.xata.sh:5432/<db>:<branch>' },
  { value: 'neon',     label: 'Neon',       placeholder: 'postgresql://<user>:<password>@<endpoint>.neon.tech/<dbname>?sslmode=require' },
]

function DatabasePanel() {
  const { rows, save, remove, load } = useServiceSettings('database')
  const [provider, setProvider] = useState('postgres')
  const [url, setUrl] = useState('')
  const [showUrl, setShowUrl] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const p = rows.find(r => r.key_name === 'provider')?.key_preview
    if (p) setProvider(p)
  }, [rows])

  const providerMeta = DB_PROVIDERS.find(p => p.value === provider) || DB_PROVIDERS[0]
  const connectionRow = rows.find(r => r.key_name === 'connection_url')

  const test = async () => {
    setTesting(true); setTestResult(null)
    try { const { data } = await api.testDatabaseConnection(url); setTestResult(data) }
    catch (e) { setTestResult({ ok: false, message: api.errMsg ? api.errMsg(e) : 'Test failed.' }) }
    finally { setTesting(false) }
  }
  const doSave = async () => {
    setSaving(true)
    try {
      await save('connection_url', url); await save('provider', provider)
      toast.success('Database settings saved'); setUrl(''); setTestResult(null); load()
    } catch (e) { toast.error(api.errMsg ? api.errMsg(e) : 'Could not save') }
    finally { setSaving(false) }
  }

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 style={{ marginTop: 0 }}><Database size={16} style={{ verticalAlign: '-3px', marginRight: 6 }} />Database</h3>
      <p className="text-xs text-muted" style={{ marginBottom: 14, lineHeight: 1.5 }}>
        Test a connection string before saving. Saving records it here for reference and hand-off, but does not move this
        running app onto it — set it as your hosting platform's <code>DATABASE_URL</code> environment variable and redeploy
        to actually switch.
      </p>
      <div className="input-group">
        <label className="text-sm fw-600">Provider</label>
        <select className="input input-sm" style={{ maxWidth: 220 }} value={provider} onChange={e => { setProvider(e.target.value); setTestResult(null) }}>
          {DB_PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
      </div>
      <div className="input-group mt-4">
        <label className="text-sm fw-600">Connection string</label>
        <div className="flex items-center gap-1">
          <input className="input" style={{ fontFamily: 'monospace', fontSize: '.8rem' }} type={showUrl ? 'text' : 'password'}
            placeholder={providerMeta.placeholder} value={url} onChange={e => { setUrl(e.target.value); setTestResult(null) }} />
          <button type="button" className="btn btn-ghost btn-icon" onClick={() => setShowUrl(s => !s)} title={showUrl ? 'Hide' : 'Show'}>
            {showUrl ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
      </div>
      <ResultBanner result={testResult} />
      <div className="flex gap-1 mt-4">
        <button className="btn btn-outline btn-sm" disabled={!url.trim() || testing} onClick={test}>{testing ? 'Testing…' : 'Test connection'}</button>
        <button className="btn btn-primary btn-sm" disabled={!url.trim() || saving} onClick={doSave}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
      {connectionRow && (
        <div className="mt-4">
          <div className="text-xs fw-600 text-muted" style={{ textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 6 }}>Currently configured</div>
          {rows.map(r => <SavedRow key={r.id} row={r} onDelete={remove} />)}
        </div>
      )}
    </div>
  )
}

// ── S3 Bucket Storage ────────────────────────────────────────────────────
function S3Panel() {
  const { rows, save, remove, load } = useServiceSettings('s3')
  const [form, setForm] = useState({ access_key_id: '', secret_access_key: '', bucket_name: '', region: '', endpoint_url: '' })
  const [showSecret, setShowSecret] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const test = async () => {
    setTesting(true); setTestResult(null)
    try { const { data } = await api.testS3Connection(form); setTestResult(data) }
    catch (e) { setTestResult({ ok: false, message: api.errMsg ? api.errMsg(e) : 'Test failed.' }) }
    finally { setTesting(false) }
  }
  const doSave = async () => {
    setSaving(true)
    try {
      for (const [k, v] of Object.entries(form)) if (v.trim()) await save(k, v.trim())
      toast.success('S3 settings saved')
      setForm({ access_key_id: '', secret_access_key: '', bucket_name: '', region: '', endpoint_url: '' })
      setTestResult(null); load()
    } catch (e) { toast.error(api.errMsg ? api.errMsg(e) : 'Could not save') }
    finally { setSaving(false) }
  }
  const anyFilled = Object.values(form).some(v => v.trim())

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 style={{ marginTop: 0 }}><Cloud size={16} style={{ verticalAlign: '-3px', marginRight: 6 }} />S3 Bucket Storage</h3>
      <p className="text-xs text-muted" style={{ marginBottom: 14 }}>Used for document/file storage (invoices, statements, attachments) instead of local disk.</p>
      <div className="grid-2" style={{ gap: 12 }}>
        <div className="input-group"><label className="text-sm fw-600">Access Key ID</label>
          <input className="input input-sm" value={form.access_key_id} onChange={e => { set('access_key_id', e.target.value); setTestResult(null) }} placeholder="AKIA..." /></div>
        <div className="input-group"><label className="text-sm fw-600">Secret Access Key</label>
          <div className="flex items-center gap-1">
            <input className="input input-sm" type={showSecret ? 'text' : 'password'} value={form.secret_access_key}
              onChange={e => { set('secret_access_key', e.target.value); setTestResult(null) }} placeholder="••••••••" />
            <button type="button" className="btn btn-ghost btn-icon" onClick={() => setShowSecret(s => !s)}>{showSecret ? <EyeOff size={14} /> : <Eye size={14} />}</button>
          </div></div>
        <div className="input-group"><label className="text-sm fw-600">Bucket name</label>
          <input className="input input-sm" value={form.bucket_name} onChange={e => { set('bucket_name', e.target.value); setTestResult(null) }} placeholder="my-accfino-bucket" /></div>
        <div className="input-group"><label className="text-sm fw-600">Region</label>
          <input className="input input-sm" value={form.region} onChange={e => { set('region', e.target.value); setTestResult(null) }} placeholder="ap-southeast-2" /></div>
        <div className="input-group" style={{ gridColumn: 'span 2' }}><label className="text-sm fw-600">Endpoint URL (optional — for S3-compatible providers)</label>
          <input className="input input-sm" value={form.endpoint_url} onChange={e => { set('endpoint_url', e.target.value); setTestResult(null) }} placeholder="https://<account>.r2.cloudflarestorage.com" /></div>
      </div>
      <ResultBanner result={testResult} />
      <div className="flex gap-1 mt-4">
        <button className="btn btn-outline btn-sm" disabled={!anyFilled || testing} onClick={test}>{testing ? 'Testing…' : 'Test connection'}</button>
        <button className="btn btn-primary btn-sm" disabled={!anyFilled || saving} onClick={doSave}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
      {rows.length > 0 && (
        <div className="mt-4">
          <div className="text-xs fw-600 text-muted" style={{ textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 6 }}>Currently configured</div>
          {rows.map(r => <SavedRow key={r.id} row={r} onDelete={remove} />)}
        </div>
      )}
    </div>
  )
}

// ── System Email (SMTP) ──────────────────────────────────────────────────
const SMTP_FIELDS = [
  { name: 'host', label: 'SMTP Host', placeholder: 'e.g. smtp.gmail.com' },
  { name: 'port', label: 'SMTP Port', placeholder: '587' },
  { name: 'username', label: 'Username', placeholder: 'system@company.com' },
  { name: 'password', label: 'Password', type: 'password', placeholder: '••••••••' },
  { name: 'from_email', label: 'From Email', type: 'email', placeholder: 'noreply@yourcompany.com' },
]

function SystemEmailPanel() {
  const { rows, save, remove, load } = useServiceSettings('system_email')
  const [form, setForm] = useState({})
  const [showPw, setShowPw] = useState(false)
  const [saving, setSaving] = useState(false)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const doSave = async () => {
    setSaving(true)
    try {
      for (const f of SMTP_FIELDS) if ((form[f.name] || '').trim()) await save(f.name, form[f.name].trim())
      toast.success('System email settings saved'); setForm({}); load()
    } catch (e) { toast.error(api.errMsg ? api.errMsg(e) : 'Could not save') }
    finally { setSaving(false) }
  }
  const anyFilled = SMTP_FIELDS.some(f => (form[f.name] || '').trim())

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 style={{ marginTop: 0 }}><Mail size={16} style={{ verticalAlign: '-3px', marginRight: 6 }} />System Email</h3>
      <p className="text-xs text-muted" style={{ marginBottom: 14, lineHeight: 1.5 }}>
        Sends account-lifecycle system email — signup verification, password reset links. Separate from any
        per-organisation email settings used for candidate/customer-facing messages.
      </p>
      <div className="grid-2" style={{ gap: 12 }}>
        {SMTP_FIELDS.map(f => (
          <div className="input-group" key={f.name}>
            <label className="text-sm fw-600">{f.label}</label>
            {f.type === 'password' ? (
              <div className="flex items-center gap-1">
                <input className="input input-sm" type={showPw ? 'text' : 'password'} placeholder={f.placeholder}
                  value={form[f.name] || ''} onChange={e => set(f.name, e.target.value)} />
                <button type="button" className="btn btn-ghost btn-icon" onClick={() => setShowPw(s => !s)}>{showPw ? <EyeOff size={14} /> : <Eye size={14} />}</button>
              </div>
            ) : (
              <input className="input input-sm" type={f.type || 'text'} placeholder={f.placeholder}
                value={form[f.name] || ''} onChange={e => set(f.name, e.target.value)} />
            )}
          </div>
        ))}
      </div>
      <button className="btn btn-primary btn-sm mt-4" disabled={!anyFilled || saving} onClick={doSave}>
        {saving ? 'Saving…' : rows.length > 0 ? 'Update system email settings' : 'Save system email settings'}
      </button>
      {rows.length > 0 && (
        <div className="mt-4">
          <div className="text-xs fw-600 text-muted" style={{ textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 6 }}>Currently configured</div>
          {rows.map(r => <SavedRow key={r.id} row={r} onDelete={remove} />)}
        </div>
      )}
    </div>
  )
}

// ── Calendly ─────────────────────────────────────────────────────────────
function CalendlyPanel() {
  const { rows, save, remove, load } = useServiceSettings('calendly')
  const [bookingUrl, setBookingUrl] = useState('')
  const [saving, setSaving] = useState(false)

  const doSave = async () => {
    setSaving(true)
    try { await save('booking_url', bookingUrl); toast.success('Calendly link saved'); setBookingUrl(''); load() }
    catch (e) { toast.error(api.errMsg ? api.errMsg(e) : 'Could not save') }
    finally { setSaving(false) }
  }

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 style={{ marginTop: 0 }}><CalendarClock size={16} style={{ verticalAlign: '-3px', marginRight: 6 }} />Calendly — Interview / Meeting Scheduling</h3>
      <p className="text-xs text-muted" style={{ marginBottom: 14, lineHeight: 1.5 }}>
        Lets scheduling flows hand out a Calendly link so the other party books their own time slot — Calendly
        handles availability and calendar conflicts.
      </p>
      <div className="input-group">
        <label className="text-sm fw-600">Booking link</label>
        <input className="input" value={bookingUrl} onChange={e => setBookingUrl(e.target.value)} placeholder="https://calendly.com/your-username/30min" />
      </div>
      <button className="btn btn-primary btn-sm mt-4" disabled={!bookingUrl.trim() || saving} onClick={doSave}>
        {saving ? 'Saving…' : 'Save Calendly link'}
      </button>
      {rows.length > 0 && (
        <div className="mt-4">
          <div className="text-xs fw-600 text-muted" style={{ textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 6 }}>Currently configured</div>
          {rows.map(r => <SavedRow key={r.id} row={r} onDelete={remove} />)}
        </div>
      )}
    </div>
  )
}

// ── Meeting Link (Zoom / Teams / Google Meet) ──────────────────────────
function MeetingLinkPanel() {
  const { rows, save, remove, load } = useServiceSettings('meeting_link')
  const [platform, setPlatform] = useState('zoom')
  const [link, setLink] = useState('')
  const [saving, setSaving] = useState(false)

  const doSave = async () => {
    setSaving(true)
    try { await save('platform', platform); await save('link', link); toast.success('Meeting link saved'); setLink(''); load() }
    catch (e) { toast.error(api.errMsg ? api.errMsg(e) : 'Could not save') }
    finally { setSaving(false) }
  }

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h3 style={{ marginTop: 0 }}><Video size={16} style={{ verticalAlign: '-3px', marginRight: 6 }} />Meeting Link — Zoom / Teams / Google Meet</h3>
      <p className="text-xs text-muted" style={{ marginBottom: 14, lineHeight: 1.5 }}>
        A default video-call link used to pre-fill meeting/interview scheduling whenever no link is set at
        booking time. Paste your own recurring Zoom Personal Meeting Room, Microsoft Teams meeting, or Google
        Meet link — this doesn't create new meetings, it just saves retyping the same one every time.
      </p>
      <div className="grid-2" style={{ gap: 12 }}>
        <div className="input-group"><label className="text-sm fw-600">Platform</label>
          <select className="input input-sm" value={platform} onChange={e => setPlatform(e.target.value)}>
            <option value="zoom">Zoom</option>
            <option value="teams">Microsoft Teams</option>
            <option value="meet">Google Meet</option>
            <option value="other">Other</option>
          </select></div>
        <div className="input-group"><label className="text-sm fw-600">Meeting link</label>
          <input className="input input-sm" value={link} onChange={e => setLink(e.target.value)} placeholder="https://zoom.us/j/…" /></div>
      </div>
      <button className="btn btn-primary btn-sm mt-4" disabled={!link.trim() || saving} onClick={doSave}>
        {saving ? 'Saving…' : 'Save meeting link'}
      </button>
      {rows.length > 0 && (
        <div className="mt-4">
          <div className="text-xs fw-600 text-muted" style={{ textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 6 }}>Currently configured</div>
          {rows.map(r => <SavedRow key={r.id} row={r} onDelete={remove} />)}
        </div>
      )}
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────
// Each panel has its own module id (see Admin > Modules Management) so any
// one of them can be hidden independently — e.g. an org not using Calendly
// can hide that panel without affecting Database/S3/etc.
export default function PlatformSettingsPanels() {
  const { isModuleVisible } = useModuleVisibility()
  return (
    <div style={{ maxWidth: 720 }}>
      {isModuleVisible('groq-key-pool') && <GroqKeyPoolPanel />}
      {isModuleVisible('platform-database') && <DatabasePanel />}
      {isModuleVisible('platform-s3') && <S3Panel />}
      {isModuleVisible('platform-system-email') && <SystemEmailPanel />}
      {isModuleVisible('platform-calendly') && <CalendlyPanel />}
      {isModuleVisible('platform-meeting-link') && <MeetingLinkPanel />}
    </div>
  )
}
