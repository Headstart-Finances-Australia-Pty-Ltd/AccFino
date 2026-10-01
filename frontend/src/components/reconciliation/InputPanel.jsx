import React, { useState, useEffect, useRef } from 'react'
import { getSessions, deleteSession, getSession, getBanks } from '../../lib/api.js'
import { PlusCircle, Trash2, Upload, PlayCircle, Folder, FileText, X, ChevronRight } from 'lucide-react'
import toast from 'react-hot-toast'

export default function InputPanel({ accounts, setAccounts, username, onProcess, running, onLoadSession, processLabel="⚡ Agent Run", currency, onCurrencyChange }) {
  const [banks,      setBanks]      = useState([])
  const [bankName,   setBankName]   = useState('')
  const [accNum,     setAccNum]     = useState('')
  const [pending,    setPending]    = useState([])
  const [sessions,   setSessions]   = useState([])
  const [loadingSid, setLoadingSid] = useState(null)
  const [dragging,   setDragging]   = useState(false)
  const fileRef = useRef()

  const CURRENCIES = [
    { code: 'AUD', label: '🇦🇺 AUD — Australian Dollar' },
    { code: 'USD', label: '🇺🇸 USD — US Dollar' },
    { code: 'EUR', label: '🇪🇺 EUR — Euro' },
    { code: 'GBP', label: '🇬🇧 GBP — British Pound' },
    { code: 'INR', label: '🇮🇳 INR — Indian Rupee' },
    { code: 'JPY', label: '🇯🇵 JPY — Japanese Yen' },
    { code: 'CNY', label: '🇨🇳 CNY — Chinese Yuan' },
    { code: 'CAD', label: '🇨🇦 CAD — Canadian Dollar' },
    { code: 'NZD', label: '🇳🇿 NZD — New Zealand Dollar' },
    { code: 'SGD', label: '🇸🇬 SGD — Singapore Dollar' },
    { code: 'HKD', label: '🇭🇰 HKD — Hong Kong Dollar' },
    { code: 'CHF', label: '🇨🇭 CHF — Swiss Franc' },
    { code: 'KRW', label: '🇰🇷 KRW — South Korean Won' },
    { code: 'AED', label: '🇦🇪 AED — UAE Dirham' },
    { code: 'MYR', label: '🇲🇾 MYR — Malaysian Ringgit' },
    { code: 'THB', label: '🇹🇭 THB — Thai Baht' },
    { code: 'IDR', label: '🇮🇩 IDR — Indonesian Rupiah' },
    { code: 'PHP', label: '🇵🇭 PHP — Philippine Peso' },
    { code: 'PKR', label: '🇵🇰 PKR — Pakistani Rupee' },
    { code: 'BDT', label: '🇧🇩 BDT — Bangladeshi Taka' },
    { code: 'VND', label: '🇻🇳 VND — Vietnamese Dong' },
    { code: 'ZAR', label: '🇿🇦 ZAR — South African Rand' },
    { code: 'MXN', label: '🇲🇽 MXN — Mexican Peso' },
    { code: 'BRL', label: '🇧🇷 BRL — Brazilian Real' },
    { code: 'SEK', label: '🇸🇪 SEK — Swedish Krona' },
    { code: 'NOK', label: '🇳🇴 NOK — Norwegian Krone' },
    { code: 'DKK', label: '🇩🇰 DKK — Danish Krone' },
  ]

  useEffect(() => {
    getBanks().then(r => setBanks(r.data || [])).catch(() => {})
  }, [])

  useEffect(() => {
    if (!username) return
    getSessions(username).then(r => setSessions(r.data || [])).catch(() => {})
  }, [username])

  const addFiles = files => setPending(p => [...p, ...Array.from(files).filter(f => f.name.endsWith('.csv'))])

  const addAccount = () => {
    if (!bankName || !accNum || !pending.length) {
      toast.error('Select a bank, enter account number, and upload at least one CSV file'); return
    }
    setAccounts(a => [...a, { bankName, accountNumber: accNum, files: pending }])
    setBankName(''); setAccNum(''); setPending([])
    toast.success(`${bankName} account added`)
  }

  const removeAccount = i => setAccounts(a => a.filter((_, j) => j !== i))

  const loadSess = async sid => {
    setLoadingSid(sid)
    try {
      const { data } = await getSession(username, sid)
      onLoadSession(data.transactions || [], data.monthly_summary || [], sid)
      toast.success('Session loaded')
    } catch { toast.error('Failed to load session') }
    finally { setLoadingSid(null) }
  }

  const delSess = async sid => {
    try {
      await deleteSession(username, sid)
      setSessions(s => s.filter(x => x.session_id !== sid))
      toast.success('Session deleted')
    } catch { toast.error('Delete failed') }
  }

  const onDrop = e => {
    e.preventDefault(); setDragging(false)
    addFiles(e.dataTransfer.files || [])
  }

  const bankInitials = n => n ? n.slice(0, 3).toUpperCase() : '??'

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr 1fr', gap: 20, alignItems: 'start' }}>

      {/* ── Add Bank Account ── */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <div style={{ width: 28, height: 28, borderRadius: 'var(--r-md)', background: 'var(--brand-light)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <PlusCircle size={15} color="var(--brand)" />
          </div>
          <h3>Add Bank Account</h3>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Bank selector */}
          <div className="input-group">
            <label>Bank</label>
            <select value={bankName} onChange={e => setBankName(e.target.value)}>
              <option value="">Select bank…</option>
              {banks.map(b => <option key={b} value={b}>{b}</option>)}
            </select>
          </div>

          {/* Account number */}
          <div className="input-group">
            <label>Account Number</label>
            <input className="input" value={accNum} onChange={e => setAccNum(e.target.value)} placeholder="e.g. 12345678" />
          </div>

          {/* Currency selector */}
          <div className="input-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Currency of Statement
              {currency && currency !== 'AUD' && (
                <span style={{
                  fontSize: '.7rem', background: 'var(--warning-bg)', color: 'var(--warning)',
                  padding: '2px 8px', borderRadius: 100, fontWeight: 700,
                }}>
                  Will convert to AUD
                </span>
              )}
            </label>
            <select value={currency || 'AUD'} onChange={e => onCurrencyChange && onCurrencyChange(e.target.value)}>
              {CURRENCIES.map(c => (
                <option key={c.code} value={c.code}>{c.label}</option>
              ))}
            </select>
            {currency && currency !== 'AUD' && (
              <div style={{
                marginTop: 6, padding: '8px 10px',
                background: 'var(--info-bg)', borderRadius: 'var(--r-sm)',
                fontSize: '.75rem', color: 'var(--info)',
                display: 'flex', alignItems: 'center', gap: 6,
              }}>
                <span>💱</span>
                Amounts will be converted from <strong>{currency}</strong> to <strong>AUD</strong> using live Google Finance rates before processing. Output always shows AUD.
              </div>
            )}
          </div>

          {/* Drop zone */}
          <div className="input-group">
            <label>CSV Statement Files</label>
            <div
              className={`drop-zone${dragging ? ' drag-over' : ''}`}
              onDrop={onDrop}
              onDragOver={e => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onClick={() => fileRef.current.click()}
            >
              <Upload size={22} className="drop-icon" />
              <div>
                <div style={{ fontWeight: 600, fontSize: '.875rem', color: 'var(--text-2)' }}>
                  Drag & drop CSV files here
                </div>
                <div style={{ fontSize: '.78rem', color: 'var(--text-3)', marginTop: 2 }}>
                  or click to browse · .csv files only
                </div>
              </div>
            </div>
            <input ref={fileRef} type="file" accept=".csv" multiple style={{ display: 'none' }}
              onChange={e => addFiles(e.target.files)} />

            {/* File list */}
            {pending.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 8 }}>
                {pending.map((f, i) => (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px',
                    background: 'var(--brand-xlight)', border: '1px solid #A7F3D0',
                    borderRadius: 'var(--r-sm)',
                  }}>
                    <FileText size={13} color="var(--brand)" style={{ flexShrink: 0 }} />
                    <span style={{ flex: 1, fontSize: '.78rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-2)', fontWeight: 500 }}>
                      {f.name}
                    </span>
                    <span style={{ fontSize: '.72rem', color: 'var(--text-3)' }}>
                      {(f.size / 1024).toFixed(0)}KB
                    </span>
                    <button onClick={() => setPending(p => p.filter((_, j) => j !== i))} style={{
                      background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-3)',
                      display: 'flex', padding: 2, borderRadius: 3,
                    }}>
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <button className="btn btn-accent btn-full" onClick={addAccount}
            style={{ marginTop: 4 }}>
            <PlusCircle size={15} /> Add Account
          </button>
        </div>
      </div>

      {/* ── Accounts Ready ── */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <div style={{ width: 28, height: 28, borderRadius: 'var(--r-md)', background: 'var(--brand-light)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <FileText size={15} color="var(--brand)" />
          </div>
          <h3>Accounts Ready</h3>
          <span style={{
            marginLeft: 'auto', background: accounts.length ? 'var(--brand)' : 'var(--surface-3)',
            color: accounts.length ? '#fff' : 'var(--text-3)',
            fontSize: '.72rem', fontWeight: 700, padding: '2px 8px', borderRadius: 100,
          }}>{accounts.length}</span>
        </div>

        {accounts.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px 16px', color: 'var(--text-3)', fontSize: '.875rem' }}>
            <div style={{ fontSize: '2rem', marginBottom: 8 }}>🏦</div>
            No accounts added yet.<br />Add one using the form on the left.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
            {accounts.map((acc, i) => (
              <div key={i} className="account-pill">
                <div className="bank-badge">{bankInitials(acc.bankName)}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: '.875rem', color: 'var(--text-1)' }}>{acc.bankName}</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-3)', marginTop: 1 }}>{acc.accountNumber}</div>
                  <div style={{ fontSize: '.72rem', color: 'var(--text-3)' }}>{acc.files.length} file{acc.files.length !== 1 ? 's' : ''}</div>
                </div>
                <button onClick={() => removeAccount(i)} style={{
                  background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-3)',
                  display: 'flex', padding: 4, borderRadius: 'var(--r-sm)', transition: 'color .12s',
                }}
                  onMouseEnter={e => e.currentTarget.style.color = 'var(--danger)'}
                  onMouseLeave={e => e.currentTarget.style.color = 'var(--text-3)'}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}

        <button
          className="btn btn-primary btn-full"
          onClick={onProcess}
          disabled={running || accounts.length === 0}
          style={{ marginTop: accounts.length > 0 ? 0 : 0 }}
        >
          {running
            ? <><span className="spinner spinner-sm" /> Running…</>
            : <><PlayCircle size={15} /> Process Files</>
          }
        </button>
      </div>

      {/* ── Past Sessions ── */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <div style={{ width: 28, height: 28, borderRadius: 'var(--r-md)', background: 'var(--brand-light)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Folder size={15} color="var(--brand)" />
          </div>
          <h3>Past Sessions</h3>
        </div>

        {sessions.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px 16px', color: 'var(--text-3)', fontSize: '.875rem' }}>
            <div style={{ fontSize: '2rem', marginBottom: 8 }}>📂</div>
            No sessions saved yet.<br />Process files to create your first session.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 360, overflowY: 'auto' }}>
            {sessions.map(s => (
              <div key={s.session_id} className="session-item">
                <div style={{ width: 32, height: 32, borderRadius: 'var(--r-sm)', background: 'var(--surface-3)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <Folder size={14} color="var(--text-3)" />
                </div>
                <button onClick={() => loadSess(s.session_id)} disabled={!!loadingSid} style={{
                  flex: 1, background: 'none', border: 'none', cursor: 'pointer',
                  textAlign: 'left', fontFamily: 'inherit', padding: 0,
                  overflow: 'hidden',
                }}>
                  <div style={{ fontWeight: 600, fontSize: '.8125rem', color: 'var(--text-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {loadingSid === s.session_id
                      ? <span className="spinner spinner-sm" />
                      : (s.display_name || s.session_id)
                    }
                  </div>
                  <div style={{ fontSize: '.72rem', color: 'var(--text-3)' }}>
                    {s.has_results ? '✓ Has results' : 'No results'}
                  </div>
                </button>
                <button onClick={() => delSess(s.session_id)} style={{
                  background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-3)',
                  display: 'flex', padding: 4, borderRadius: 'var(--r-sm)', flexShrink: 0, transition: 'color .12s',
                }}
                  onMouseEnter={e => e.currentTarget.style.color = 'var(--danger)'}
                  onMouseLeave={e => e.currentTarget.style.color = 'var(--text-3)'}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

    </div>
  )
}