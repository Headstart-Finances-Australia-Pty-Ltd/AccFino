import React, { useState, useEffect, useRef } from 'react'
import { stocksStatus, stocksAnalyze, stocksExport } from '../../lib/api.js'
import { Upload, Download, RefreshCw, TrendingUp, DollarSign, BarChart2, AlertTriangle } from 'lucide-react'
import toast from 'react-hot-toast'

const fmtAUD = n => n==null?'—':new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(n)
const fmtN   = n => n==null?'—':Number(n).toLocaleString('en-AU',{minimumFractionDigits:2,maximumFractionDigits:2})

const BROKERS = ['CommSec','NABtrade','SelfWealth','Stake','Superhero','Other']
const FYS     = ['2024-25','2023-24','2022-23','2021-22','2020-21']
const PAGE_SZ = 50

export default function StockTrading() {
  const [moduleStatus, setModuleStatus] = useState(null)
  const [files,        setFiles]        = useState([])
  const [fy,           setFy]           = useState('2024-25')
  const [result,       setResult]       = useState(null)
  const [loading,      setLoading]      = useState(false)
  const [tab,          setTab]          = useState('summary')
  const [page,         setPage]         = useState(1)
  const fileRef = useRef()

  useEffect(() => {
    stocksStatus().then(r=>setModuleStatus(r.data)).catch(()=>setModuleStatus({available:false,error:'API not reachable'}))
  }, [])

  const handleAnalyze = async () => {
    if (!files.length) { toast.error('Upload at least one broker file (Excel or CSV)'); return }
    setLoading(true); setResult(null)
    try {
      const fd = new FormData()
      files.forEach(f => fd.append('files', f, f.name))
      fd.append('financial_year', fy)
      const { data } = await stocksAnalyze(fd)
      setResult(data); setTab('summary'); setPage(1)
      toast.success(`Processed ${data.total_disposals} disposals for FY ${data.financial_year}`)
    } catch (e) { toast.error(e.response?.data?.detail||'Analysis failed') }
    finally { setLoading(false) }
  }

  const handleExport = async () => {
    if (!files.length) return
    try {
      const fd = new FormData()
      files.forEach(f => fd.append('files', f, f.name))
      fd.append('financial_year', fy)
      const { data } = await stocksExport(fd)
      const url = URL.createObjectURL(new Blob([data]))
      const a = document.createElement('a'); a.href=url; a.download=`HSLedger_CGT_${fy}.xlsx`; a.click()
      URL.revokeObjectURL(url)
    } catch { toast.error('Export failed') }
  }

  const summary    = result?.summary    || []
  const disposals  = result?.disposals  || []
  const income     = result?.income     || []
  const missing    = result?.missing_buys || []
  const totalPages = Math.max(1, Math.ceil(disposals.length/PAGE_SZ))
  const dispPage   = disposals.slice((page-1)*PAGE_SZ, page*PAGE_SZ)

  // Summary metrics from first summary row
  const s = summary[0] || {}
  const netGain    = parseFloat(s['Net Taxable Gain']||s['net_taxable_gain']||0)
  const grossGains = parseFloat(s['Gross Capital Gains']||s['gross_capital_gains']||0)
  const grossLoss  = parseFloat(s['Gross Capital Losses']||s['gross_capital_losses']||0)
  const discount   = parseFloat(s['CGT Discount Applied']||s['cgt_discount_applied']||0)

  return (
    <div className="fade-in">
      <div style={{marginBottom:22}}>
        <h1>📊 Stock / Equity Trading Analysis</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
          Upload broker files · ATO-compliant CGT · CGT discount · tax report · export Excel
        </p>
      </div>
      {/* Module status */}
      {moduleStatus && !moduleStatus.available && (
        <div className="alert alert-warning" style={{marginBottom:16}}>
          <AlertTriangle size={15} style={{flexShrink:0,marginTop:1}}/>
          <div>
            <strong>Stock Trading Module Unavailable</strong>
            <div style={{fontSize:'.8rem',marginTop:4}}>
              {moduleStatus.error}
              <br/>Ensure <code>HSLedger_Trading_Module</code> is in the project root alongside the <code>Accfino</code> folder.
            </div>
          </div>
        </div>
      )}

      {/* Upload + controls */}
      <div className="card" style={{marginBottom:20}}>
        <h3 style={{marginBottom:14}}>Upload Broker Files</h3>
        <div style={{display:'grid',gridTemplateColumns:'1fr auto auto',gap:12,alignItems:'flex-end',flexWrap:'wrap'}}>
          <div>
            <div className="drop-zone" onClick={()=>fileRef.current.click()}
              onDrop={e=>{e.preventDefault();setFiles(p=>[...p,...Array.from(e.dataTransfer.files)])}}
              onDragOver={e=>e.preventDefault()}>
              <Upload size={20} className="drop-icon"/>
              <div>
                <div style={{fontWeight:600,fontSize:'.875rem',color:'var(--text-2)'}}>
                  {files.length>0 ? `${files.length} file(s) selected` : 'Drop broker Excel/CSV files here'}
                </div>
                <div style={{fontSize:'.75rem',color:'var(--text-3)',marginTop:2}}>
                  CommSec · NABtrade · SelfWealth · Stake · Superhero · Standard CSV
                </div>
              </div>
            </div>
            <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" multiple style={{display:'none'}}
              onChange={e=>setFiles(p=>[...p,...Array.from(e.target.files)])}/>
            {files.length>0 && (
              <div style={{marginTop:8,display:'flex',flexWrap:'wrap',gap:4}}>
                {files.map((f,i)=>(
                  <span key={i} style={{display:'inline-flex',alignItems:'center',gap:4,padding:'2px 8px',background:'var(--brand-xlight)',border:'1px solid #A7F3D0',borderRadius:'var(--r-sm)',fontSize:'.75rem',color:'var(--brand)'}}>
                    {f.name}
                    <button onClick={()=>setFiles(p=>p.filter((_,j)=>j!==i))} style={{background:'none',border:'none',cursor:'pointer',color:'var(--text-3)',lineHeight:1,padding:0}}>✕</button>
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="input-group" style={{minWidth:130}}>
            <label>Financial Year</label>
            <select className="input" value={fy} onChange={e=>setFy(e.target.value)}>
              {FYS.map(f=><option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div style={{display:'flex',gap:8,alignItems:'flex-end'}}>
            <button className="btn btn-primary btn-lg" onClick={handleAnalyze} disabled={!files.length||loading||!moduleStatus?.available}>
              {loading?<><span className="spinner spinner-sm"/>Analysing…</>:<><TrendingUp size={16}/>Analyse</>}
            </button>
            {result&&<button className="btn btn-ghost" onClick={()=>{setResult(null);setFiles([]);fileRef.current.value=''}}><RefreshCw size={14}/> Reset</button>}
          </div>
        </div>

        {/* Broker support info */}
        <div style={{marginTop:14,padding:'10px 14px',background:'var(--surface-2)',borderRadius:'var(--r-md)',fontSize:'.8rem',color:'var(--text-3)'}}>
          <strong style={{color:'var(--text-2)'}}>Supported brokers (auto-detected):</strong> CommSec, NABtrade, SelfWealth, Stake, Superhero, CoinSpot, Binance, Swyftx, Kraken.
          ATO TR 2023/1 · FIFO CGT · 50% discount · brokerage capitalised · loss carry-forward.
        </div>
      </div>

      {!result && !loading && (
        <div className="card">
          <div className="empty-state">
            <div className="empty-icon">📊</div>
            <h3>Upload Broker Files to Analyse</h3>
            <p>Upload one or more broker transaction files. The engine auto-detects CommSec, NABtrade, SelfWealth, Stake, and Superhero formats, then runs the full ATO-compliant FIFO CGT calculation.</p>
            <div style={{marginTop:16,display:'flex',gap:8,flexWrap:'wrap',justifyContent:'center'}}>
              {BROKERS.map(b=><span key={b} className="badge badge-neutral">{b}</span>)}
            </div>
          </div>
        </div>
      )}

      {result && (
        <>
          {/* Summary stats */}
          <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12,marginBottom:16}}>
            {[
              {label:'Net Taxable Gain',      val:fmtAUD(netGain),    color:netGain>=0?'var(--success)':'var(--danger)',  icon:TrendingUp},
              {label:'Gross Capital Gains',   val:fmtAUD(grossGains), color:'var(--success)', icon:TrendingUp},
              {label:'Gross Capital Losses',  val:fmtAUD(grossLoss),  color:'var(--danger)',  icon:TrendingDown},
              {label:'CGT Discount Applied',  val:fmtAUD(discount),   color:'var(--info)',    icon:DollarSign},
            ].map(({label,val,color,icon:Icon})=>(
              <div key={label} style={{background:'var(--surface)',border:'1px solid var(--border)',borderRadius:'var(--r-lg)',padding:'14px 16px',display:'flex',alignItems:'center',gap:12,boxShadow:'var(--sh-xs)'}}>
                <div style={{width:36,height:36,borderRadius:'var(--r-md)',background:color+'18',display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0}}>
                  <Icon size={17} color={color}/>
                </div>
                <div>
                  <div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em',marginBottom:2}}>{label}</div>
                  <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'.95rem',color:'var(--text-1)'}}>{val}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Missing buys warning */}
          {missing.length>0 && (
            <div className="alert alert-warning" style={{marginBottom:16}}>
              <AlertTriangle size={15} style={{flexShrink:0,marginTop:1}}/>
              <div>
                <strong>{missing.length} missing buy record(s) flagged</strong>
                <div style={{fontSize:'.8rem',marginTop:4}}>
                  The following tickers had sells with no matching buy: {missing.map(m=>m.code).join(', ')}.
                  These disposals are excluded from the CGT calculation. Resolve them by adding manual purchase lots.
                </div>
              </div>
            </div>
          )}

          {/* Tabs */}
          <div className="tabs-bar" style={{marginBottom:0}}>
            {[
              ['summary',   `📊 FY Summary`],
              ['disposals', `💸 CGT Disposals (${disposals.length})`],
              ['income',    `💰 Income (${income.length})`],
              ['missing',   `⚠️ Missing Buys (${missing.length})`],
            ].map(([k,label])=>(
              <button key={k} className={`tab-btn${tab===k?' active':''}`} onClick={()=>setTab(k)}>{label}</button>
            ))}
          </div>

          <div style={{background:'var(--surface)',border:'1px solid var(--border)',borderTop:'none',borderRadius:'0 0 var(--r-lg) var(--r-lg)',overflow:'hidden',marginBottom:16}}>
            {/* Summary tab */}
            {tab==='summary' && (
              <div style={{overflowX:'auto'}}>
                <table className="data-table">
                  <thead><tr>{summary.length>0&&Object.keys(summary[0]).map(k=><th key={k}>{k}</th>)}</tr></thead>
                  <tbody>
                    {summary.map((row,i)=>(
                      <tr key={i}>
                        {Object.entries(row).map(([k,v],j)=>(
                          <td key={j} style={{fontFamily:typeof v==='number'?'var(--font-mono)':'inherit',textAlign:typeof v==='number'?'right':'left',fontSize:'.8rem'}}>
                            {v==null?'':typeof v==='number'?fmtN(v):String(v)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {summary.length===0&&<div className="empty-state" style={{padding:32}}><p>No summary data</p></div>}
              </div>
            )}

            {/* CGT Disposals tab */}
            {tab==='disposals' && (
              <>
                <div style={{overflowX:'auto'}}>
                  <table className="data-table">
                    <thead><tr>{dispPage.length>0&&Object.keys(dispPage[0]).map(k=><th key={k}>{k}</th>)}</tr></thead>
                    <tbody>
                      {dispPage.map((row,i)=>(
                        <tr key={i}>
                          {Object.entries(row).map(([k,v],j)=>(
                            <td key={j} style={{fontSize:'.78rem',fontFamily:typeof v==='number'?'var(--font-mono)':'inherit',textAlign:typeof v==='number'?'right':'left'}}>
                              {v==null?'':String(v)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'10px 16px',borderTop:'1px solid var(--border)',background:'var(--surface-2)'}}>
                  <span style={{fontSize:'.78rem',color:'var(--text-3)'}}>{disposals.length} disposals · Page {page} of {totalPages}</span>
                  <div style={{display:'flex',gap:3}}>
                    <button className="page-btn" disabled={page<=1} onClick={()=>setPage(p=>p-1)}>‹</button>
                    {[...Array(Math.min(totalPages,7))].map((_,i)=><button key={i+1} onClick={()=>setPage(i+1)} className={`page-btn${i+1===page?' active':''}`}>{i+1}</button>)}
                    <button className="page-btn" disabled={page>=totalPages} onClick={()=>setPage(p=>p+1)}>›</button>
                  </div>
                </div>
              </>
            )}

            {/* Income tab */}
            {tab==='income' && (
              <div style={{overflowX:'auto'}}>
                <table className="data-table">
                  <thead><tr>{income.length>0&&Object.keys(income[0]).map(k=><th key={k}>{k}</th>)}</tr></thead>
                  <tbody>{income.map((row,i)=><tr key={i}>{Object.values(row).map((v,j)=><td key={j} style={{fontSize:'.78rem'}}>{v==null?'':String(v)}</td>)}</tr>)}</tbody>
                </table>
                {income.length===0&&<div className="empty-state" style={{padding:32}}><p>No income events (dividends, interest) found</p></div>}
              </div>
            )}

            {/* Missing buys tab */}
            {tab==='missing' && (
              missing.length>0 ? (
                <div style={{overflowX:'auto'}}>
                  <table className="data-table">
                    <thead><tr><th>Code</th><th>Qty Unmatched</th><th>Disposal Date</th><th>Proceeds/Unit</th><th>Broker</th><th>Reference</th></tr></thead>
                    <tbody>
                      {missing.map((m,i)=>(
                        <tr key={i}>
                          <td style={{fontWeight:700,fontFamily:'var(--font-mono)'}}>{m.code}</td>
                          <td className="mono" style={{textAlign:'right'}}>{fmtN(m.qty_unmatched)}</td>
                          <td className="mono" style={{fontSize:'.78rem'}}>{m.disposal_date}</td>
                          <td className="mono" style={{textAlign:'right'}}>{fmtAUD(m.proceeds_per_unit)}</td>
                          <td style={{fontSize:'.8rem'}}>{m.broker}</td>
                          <td style={{fontSize:'.75rem',color:'var(--text-3)'}}>{m.reference}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <div className="empty-state" style={{padding:40}}><p>No missing buy records — all disposals matched ✅</p></div>
            )}
          </div>

          <button className="btn btn-primary" onClick={handleExport}>
            <Download size={15}/> Download Full Excel Report (FY {fy})
          </button>
        </>
      )}
    </div>
  )
}

function TrendingDown({size,color}) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
}
