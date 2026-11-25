import React, { useState, useRef } from 'react'
import { tradingAnalyze, tradingExport } from '../../lib/api.js'
import { Upload, Download, RefreshCw, TrendingUp, DollarSign, BarChart2 } from 'lucide-react'
import toast from 'react-hot-toast'

const fmtAUD = n => n==null?'—':new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(n)
const fmtN   = n => n==null?'—':Number(n).toLocaleString('en-AU',{minimumFractionDigits:2,maximumFractionDigits:2})

const PAGE_SZ = 50

export default function CryptoTrading() {
  const [file,      setFile]      = useState(null)
  const [result,    setResult]    = useState(null)
  const [loading,   setLoading]   = useState(false)
  const [tab,       setTab]       = useState('tax')
  const [tradePage, setTradePage] = useState(1)
  const fileRef = useRef()

  const handleAnalyze = async () => {
    if (!file) { toast.error('Upload a CSV or JSON trading file first'); return }
    setLoading(true)
    try {
      const fd = new FormData(); fd.append('file', file, file.name)
      const { data } = await tradingAnalyze(fd)
      setResult(data); setTab('tax'); setTradePage(1)
      toast.success(`Analyzed ${data.count} trades`)
    } catch (e) { toast.error(e.response?.data?.detail||'Analysis failed') }
    finally { setLoading(false) }
  }

  const handleExport = async () => {
    if (!file) return
    try {
      const fd = new FormData(); fd.append('file', file, file.name)
      const { data } = await tradingExport(fd)
      const url = URL.createObjectURL(new Blob([data]))
      const a = document.createElement('a'); a.href=url; a.download='trading_report.xlsx'; a.click()
      URL.revokeObjectURL(url)
    } catch { toast.error('Export failed') }
  }

  const trades     = result?.trades     || []
  const tax        = result?.tax        || []
  const perSymbol  = result?.per_symbol || []
  const pageCount  = Math.max(1, Math.ceil(trades.length / PAGE_SZ))
  const tradePage_ = Math.min(tradePage, pageCount)
  const tradeSlice = trades.slice((tradePage_-1)*PAGE_SZ, tradePage_*PAGE_SZ)

  // Compute summary from tax rows
  const totalGain  = tax.reduce((s,r)=>s+(parseFloat(r['Realized Gain']||r['Net Gain']||0)),0)
  const totalProc  = tax.reduce((s,r)=>s+(parseFloat(r['Proceeds']||0)),0)
  const totalCost  = tax.reduce((s,r)=>s+(parseFloat(r['Cost']||0)),0)

  return (
    <div className="fade-in">
      <div style={{marginBottom:22}}>
        <h1>📈 Crypto Trading Analysis</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>Upload trading CSV/JSON · compute capital gains · CGT discount · tax report · export Excel</p>
      </div>

      {/* Upload card */}
      <div className="card" style={{marginBottom:20,padding:20}}>
        <div style={{display:'flex',gap:16,alignItems:'flex-end',flexWrap:'wrap'}}>
          <div style={{flex:1,minWidth:240}}>
            <label style={{marginBottom:6}}>Trading File (CSV or JSON)</label>
            <div className="drop-zone" onClick={()=>fileRef.current.click()} style={{padding:'16px 14px'}}>
              <Upload size={20} className="drop-icon"/>
              <div>
                <div style={{fontWeight:600,fontSize:'.875rem',color:'var(--text-2)'}}>{file?file.name:'Click to upload trading file'}</div>
                <div style={{fontSize:'.75rem',color:'var(--text-3)',marginTop:2}}>Supports CSV and JSON formats</div>
              </div>
            </div>
            <input ref={fileRef} type="file" accept=".csv,.json" style={{display:'none'}} onChange={e=>setFile(e.target.files[0])}/>
          </div>
          <div style={{display:'flex',gap:8}}>
            <button className="btn btn-primary btn-lg" onClick={handleAnalyze} disabled={!file||loading}>
              {loading?<><span className="spinner spinner-sm"/>Analyzing…</>:<><TrendingUp size={16}/>Analyze Trading</>}
            </button>
            {result && <button className="btn btn-outline" onClick={()=>{setResult(null);setFile(null);fileRef.current.value=''}}><RefreshCw size={15}/>Reset</button>}
          </div>
        </div>
      </div>

      {!file && !result && (
        <div className="card">
          <div className="empty-state">
            <div className="empty-icon">📊</div>
            <h3>Upload a Trading File</h3>
            <p>Supports CSV exports from Binance, Coinbase, Kraken, and most major exchanges. JSON files also accepted.</p>
            <div style={{marginTop:16,fontSize:'.8rem',color:'var(--text-3)',textAlign:'left',maxWidth:400}}>
              <strong>Expected columns:</strong> Date, Symbol, Side (Buy/Sell), Quantity, Price, Proceeds, Cost, Fee
            </div>
          </div>
        </div>
      )}

      {result && (
        <>
          {/* Summary stats */}
          <div className="stats-grid" style={{marginBottom:20}}>
            {[
              {label:'Total Trades',  val:result.count,      color:'var(--info)',    icon:BarChart2},
              {label:'Total Proceeds',val:fmtAUD(totalProc), color:'var(--success)', icon:TrendingUp},
              {label:'Total Cost',    val:fmtAUD(totalCost), color:'var(--warning)', icon:DollarSign},
              {label:'Net Gain/Loss', val:fmtAUD(totalGain), color:totalGain>=0?'var(--success)':'var(--danger)', icon:DollarSign},
            ].map(({label,val,color,icon:Icon})=>(
              <div key={label} className="stat-card" style={{'--stat-accent':color,'--stat-icon-bg':color+'18'}}>
                <div className="stat-icon"><Icon size={18} color={color}/></div>
                <div className="stat-label">{label}</div>
                <div className="stat-value" style={{fontSize:'1.1rem'}}>{val}</div>
              </div>
            ))}
          </div>

          {/* Tabs */}
          <div className="tabs-bar" style={{marginBottom:0}}>
            {[['tax','💰 Capital Gains & Tax'],['trades','📋 Classified Trades'],['per_symbol','📊 Per Symbol']].map(([k,label])=>(
              <button key={k} className={`tab-btn${tab===k?' active':''}`} onClick={()=>setTab(k)}>{label}
                <span style={{background:tab===k?'var(--brand)':'var(--surface-3)',color:tab===k?'#fff':'var(--text-3)',fontSize:'.68rem',fontWeight:700,padding:'1px 6px',borderRadius:100}}>
                  {k==='tax'?tax.length:k==='trades'?trades.length:perSymbol.length}
                </span>
              </button>
            ))}
          </div>

          <div style={{background:'var(--surface)',border:'1px solid var(--border)',borderTop:'none',borderRadius:'0 0 var(--r-lg) var(--r-lg)',overflow:'hidden',marginBottom:16}}>
            {tab==='tax' && (
              <div style={{overflowX:'auto'}}>
                <table className="data-table">
                  <thead><tr>{tax.length>0&&Object.keys(tax[0]).map(k=><th key={k}>{k}</th>)}</tr></thead>
                  <tbody>
                    {tax.map((row,i)=>(
                      <tr key={i} style={i===tax.length-1?{fontWeight:700,background:'#FFFDE7'}:{}}>
                        {Object.values(row).map((v,j)=>(
                          <td key={j} style={{fontFamily:typeof v==='number'||/^\d/.test(String(v))?'var(--font-mono)':'inherit',textAlign:typeof v==='number'?'right':'left',fontSize:'.78rem'}}>
                            {v==null?'':String(v)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {tax.length===0&&<div className="empty-state" style={{padding:32}}><p>No capital gains data</p></div>}
              </div>
            )}

            {tab==='trades' && (
              <>
                <div style={{overflowX:'auto'}}>
                  <table className="data-table">
                    <thead><tr>{tradeSlice.length>0&&Object.keys(tradeSlice[0]).map(k=><th key={k}>{k}</th>)}</tr></thead>
                    <tbody>
                      {tradeSlice.map((row,i)=>(
                        <tr key={i}>
                          {Object.values(row).map((v,j)=>(
                            <td key={j} style={{fontSize:'.78rem'}}>{v==null?'':String(v)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'10px 16px',borderTop:'1px solid var(--border)',background:'var(--surface-2)'}}>
                  <span style={{fontSize:'.78rem',color:'var(--text-3)'}}>{trades.length} trades · Page {tradePage_} of {pageCount}</span>
                  <div style={{display:'flex',gap:4}}>
                    <button className="page-btn" disabled={tradePage_<=1} onClick={()=>setTradePage(p=>p-1)}>‹</button>
                    {[...Array(Math.min(pageCount,7))].map((_,i)=><button key={i+1} onClick={()=>setTradePage(i+1)} className={`page-btn${i+1===tradePage_?' active':''}`}>{i+1}</button>)}
                    <button className="page-btn" disabled={tradePage_>=pageCount} onClick={()=>setTradePage(p=>p+1)}>›</button>
                  </div>
                </div>
              </>
            )}

            {tab==='per_symbol' && (
              <div style={{overflowX:'auto'}}>
                <table className="data-table">
                  <thead><tr>{perSymbol.length>0&&Object.keys(perSymbol[0]).map(k=><th key={k}>{k}</th>)}</tr></thead>
                  <tbody>
                    {perSymbol.map((row,i)=>(
                      <tr key={i}>
                        {Object.values(row).map((v,j)=><td key={j} style={{fontSize:'.78rem'}}>{v==null?'':String(v)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {perSymbol.length===0&&<div className="empty-state" style={{padding:32}}><p>No per-symbol data</p></div>}
              </div>
            )}
          </div>

          <button className="btn btn-primary" onClick={handleExport}>
            <Download size={15}/> Download Full Excel Report
          </button>
        </>
      )}
    </div>
  )
}
