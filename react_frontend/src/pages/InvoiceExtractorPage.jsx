import React, { useState, useEffect, useRef } from 'react'
import { ieStatus, ieProcess } from '../lib/api.js'
import { Upload, FileText, Download, ScanLine } from 'lucide-react'
import toast from 'react-hot-toast'

export default function InvoiceExtractorPage() {
  const [status,  setStatus]  = useState(null)
  const [files,   setFiles]   = useState([])
  const [result,  setResult]  = useState(null)
  const [busy,    setBusy]    = useState(false)
  const [tessCmd, setTessCmd] = useState('')
  const [popBin,  setPopBin]  = useState('')
  const [showOCR, setShowOCR] = useState(false)
  const [tab,     setTab]     = useState('bank')
  const fileRef = useRef()

  useEffect(() => {
    ieStatus().then(r=>setStatus(r.data)).catch(()=>setStatus({available:false,reason:'API not reachable'}))
  }, [])

  const handleProcess = async () => {
    if (!files.length) { toast.error('Upload at least one PDF or image'); return }
    setBusy(true)
    try {
      const fd = new FormData()
      files.forEach(f => fd.append('files', f, f.name))
      if (tessCmd) fd.append('tesseract_cmd', tessCmd)
      if (popBin)  fd.append('poppler_bin',   popBin)
      const { data } = await ieProcess(fd)
      setResult(data); setTab(data.bank_transactions?.length>0?'bank':'invoices')
      toast.success(`Extracted ${data.bank_transactions?.length||0} transactions, ${data.invoices?.length||0} invoices`)
    } catch (e) { toast.error(e.response?.data?.detail||'Extraction failed') }
    finally { setBusy(false) }
  }

  const downloadExcel = () => {
    if (!result?.excel_b64) return
    const blob = new Blob([Uint8Array.from(atob(result.excel_b64),c=>c.charCodeAt(0))],
      {type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})
    const a = document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='extracted_data.xlsx'; a.click()
  }

  return (
    <div className="fade-in">
      <div style={{marginBottom:22}}>
        <h1>🔍 Invoice & Statement Extractor</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>Extract transactions and invoice data from PDF bank statements and image receipts using OCR</p>
      </div>

      {/* Dependency status */}
      {status && (
        <div className={`alert ${status.available?'alert-success':'alert-warning'}`} style={{marginBottom:16}}>
          <div>
            <strong>{status.available?'✅ Extractor ready':'⚠️ Extractor limited'}</strong>
            {!status.available&&<div style={{marginTop:4,fontSize:'.8rem'}}>{status.reason}</div>}
            {status.available&&(
              <div style={{marginTop:4,fontSize:'.78rem',display:'flex',gap:16,flexWrap:'wrap'}}>
                {[['pdfplumber','PDF text'],['tesseract','OCR (images/scanned)'],['pdf2image','PDF→image conversion']].map(([k,label])=>(
                  <span key={k}>{status[k]?'✅':'❌'} {label}</span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Upload card */}
      <div className="card" style={{marginBottom:16}}>
        <h3 style={{marginBottom:14}}>Upload Documents</h3>
        <div className="drop-zone" style={{marginBottom:12}}
          onClick={()=>fileRef.current.click()}
          onDrop={e=>{e.preventDefault();setFiles(p=>[...p,...Array.from(e.dataTransfer.files)])}}
          onDragOver={e=>e.preventDefault()}>
          <ScanLine size={22} className="drop-icon"/>
          <div style={{fontWeight:600,fontSize:'.875rem',color:'var(--text-2)'}}>Drop PDF / image files here or click to browse</div>
          <div style={{fontSize:'.75rem',color:'var(--text-3)'}}>Supports: PDF, PNG, JPG, TIFF, BMP, WEBP</div>
        </div>
        <input ref={fileRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif,.bmp,.webp" multiple style={{display:'none'}}
          onChange={e=>setFiles(p=>[...p,...Array.from(e.target.files)])}/>

        {files.length>0 && (
          <div style={{display:'flex',flexDirection:'column',gap:4,marginBottom:12}}>
            {files.map((f,i)=>(
              <div key={i} style={{display:'flex',alignItems:'center',gap:8,padding:'6px 10px',background:'var(--brand-xlight)',border:'1px solid #A7F3D0',borderRadius:'var(--r-sm)'}}>
                <FileText size={13} color="var(--brand)" style={{flexShrink:0}}/>
                <span style={{flex:1,fontSize:'.78rem',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{f.name}</span>
                <span style={{fontSize:'.72rem',color:'var(--text-3)'}}>{(f.size/1024).toFixed(0)}KB</span>
                <button onClick={()=>setFiles(p=>p.filter((_,j)=>j!==i))} style={{background:'none',border:'none',cursor:'pointer',color:'var(--text-3)',fontSize:.9}}>✕</button>
              </div>
            ))}
          </div>
        )}

        {/* OCR settings */}
        <button className="btn btn-ghost btn-sm" onClick={()=>setShowOCR(s=>!s)} style={{marginBottom:showOCR?12:0}}>
          ⚙️ OCR Settings {showOCR?'▲':'▼'}
        </button>
        {showOCR && (
          <div className="grid-2" style={{gap:12,marginBottom:12,padding:'12px',background:'var(--surface-2)',borderRadius:'var(--r-md)'}}>
            <div className="input-group">
              <label>Tesseract Path</label>
              <input className="input" value={tessCmd} onChange={e=>setTessCmd(e.target.value)} placeholder="C:\Program Files\Tesseract-OCR\tesseract.exe"/>
            </div>
            <div className="input-group">
              <label>Poppler Bin Directory</label>
              <input className="input" value={popBin} onChange={e=>setPopBin(e.target.value)} placeholder="C:\poppler\bin"/>
            </div>
          </div>
        )}

        <div style={{display:'flex',gap:8,alignItems:'center'}}>
          <button className="btn btn-primary" onClick={handleProcess} disabled={!files.length||busy}>
            {busy?<><span className="spinner spinner-sm"/>Extracting…</>:<><ScanLine size={15}/>Extract Data</>}
          </button>
          {files.length>0&&<button className="btn btn-ghost btn-sm" onClick={()=>{setFiles([]);setResult(null)}}>Clear All</button>}
          {result?.excel_b64&&<button className="btn btn-outline btn-sm" onClick={downloadExcel} style={{marginLeft:'auto'}}><Download size={13}/> Download Excel</button>}
        </div>
      </div>

      {/* Results */}
      {result && (
        <>
          <div className="tabs-bar" style={{marginBottom:0}}>
            {[['bank',`🏦 Bank Transactions (${result.bank_transactions?.length||0})`],['invoices',`📄 Invoices (${result.invoices?.length||0})`]].map(([k,label])=>(
              <button key={k} className={`tab-btn${tab===k?' active':''}`} onClick={()=>setTab(k)}>{label}</button>
            ))}
          </div>
          <div style={{background:'var(--surface)',border:'1px solid var(--border)',borderTop:'none',borderRadius:'0 0 var(--r-lg) var(--r-lg)',overflow:'hidden'}}>
            {tab==='bank' && (
              result.bank_transactions?.length>0
                ? <div style={{overflowX:'auto'}}>
                    <table className="data-table">
                      <thead><tr><th>Date</th><th>Description</th><th style={{textAlign:'right'}}>Debit</th><th style={{textAlign:'right'}}>Credit</th><th style={{textAlign:'right'}}>Balance</th><th>Bank</th><th>Source</th></tr></thead>
                      <tbody>
                        {result.bank_transactions.map((t,i)=>(
                          <tr key={i}>
                            <td className="mono" style={{fontSize:'.78rem',whiteSpace:'nowrap'}}>{t.date}</td>
                            <td style={{fontSize:'.8rem',maxWidth:240,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}} title={t.description}>{t.description}</td>
                            <td className="mono" style={{textAlign:'right',fontSize:'.78rem',color:'var(--warning)'}}>{t.debit?Number(t.debit).toFixed(2):''}</td>
                            <td className="mono" style={{textAlign:'right',fontSize:'.78rem',color:'var(--info)'}}>{t.credit?Number(t.credit).toFixed(2):''}</td>
                            <td className="mono" style={{textAlign:'right',fontSize:'.78rem'}}>{t.balance?Number(t.balance).toFixed(2):''}</td>
                            <td style={{fontSize:'.75rem'}}>{t.bank}</td>
                            <td style={{fontSize:'.72rem',color:'var(--text-3)',maxWidth:120,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}} title={t.source_file}>{t.source_file}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                : <div className="empty-state" style={{padding:40}}><p>No bank transactions extracted</p></div>
            )}
            {tab==='invoices' && (
              result.invoices?.length>0
                ? <div style={{padding:16,display:'flex',flexDirection:'column',gap:12}}>
                    {result.invoices.map((inv,i)=>(
                      <div key={i} className="card card-sm card-flat">
                        <div style={{display:'flex',gap:16,flexWrap:'wrap'}}>
                          {Object.entries(inv).filter(([k])=>k!=='source_file'&&k!=='items').map(([k,v])=>v!=null&&v!==''&&(
                            <div key={k}><div style={{fontSize:'.65rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em'}}>{k.replace(/_/g,' ')}</div><div style={{fontSize:'.8rem',fontWeight:500}}>{String(v)}</div></div>
                          ))}
                        </div>
                        {inv.source_file&&<div style={{fontSize:'.72rem',color:'var(--text-3)',marginTop:6}}>Source: {inv.source_file}</div>}
                      </div>
                    ))}
                  </div>
                : <div className="empty-state" style={{padding:40}}><p>No invoice data extracted</p></div>
            )}
          </div>
        </>
      )}

      {!result && !busy && (
        <div className="card" style={{marginTop:16}}>
          <h3 style={{marginBottom:12}}>Supported Document Types</h3>
          <div className="grid-3" style={{gap:12}}>
            {[
              {emoji:'🏦',title:'Bank Statements',desc:'PDF bank statements from ANZ, NAB, CBA, Westpac and others. Extracts transactions, dates, amounts.'},
              {emoji:'📄',title:'Invoices & Receipts',desc:'Supplier invoices and receipts. Extracts amounts, GST, vendor details, dates.'},
              {emoji:'🖼️',title:'Scanned Images',desc:'Scanned documents in PNG, JPG, TIFF. Requires Tesseract OCR installed on system.'},
            ].map(({emoji,title,desc})=>(
              <div key={title} style={{padding:'14px',background:'var(--surface-2)',borderRadius:'var(--r-md)',border:'1px solid var(--border)'}}>
                <div style={{fontSize:'1.5rem',marginBottom:8}}>{emoji}</div>
                <div style={{fontWeight:600,fontSize:'.875rem',marginBottom:4}}>{title}</div>
                <div style={{fontSize:'.8rem',color:'var(--text-3)',lineHeight:1.5}}>{desc}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
