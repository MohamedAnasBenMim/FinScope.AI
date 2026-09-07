import { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import { Upload, FileText, Send, Calculator, RefreshCw, Trash2, ExternalLink } from 'lucide-react'

const API = import.meta.env.VITE_API_URL || '/api'
const api = axios.create({ baseURL: API, timeout: 240000 })
const defaultFormats = '.pdf,.png,.jpg,.jpeg,.webp,.tiff,.tif,.docx,.xlsx,.xls,.csv,.txt,.md,.pptx,.html,.htm'
const message = error => error.response?.data?.detail || error.message || 'Request failed.'
const sizeLabel = size => size > 1048576 ? `${(size / 1048576).toFixed(1)} MB` : `${(size / 1024).toFixed(1)} KB`
const title = name => name.replaceAll('_', ' ')

function SourceValue({ data }) {
  if (data === null || data === undefined) return <span className="muted">Unavailable</span>
  if (typeof data !== 'object') return <span>{String(data)}</span>
  if ('value' in data && data.source) {
    const source = data.source
    return <span className="extracted-value"><strong>{String(data.value)}</strong><small>{[
      source.page ? `Page ${source.page}` : null, source.sheet, source.cell_range, source.section,
    ].filter(Boolean).join(' · ') || source.filename}</small></span>
  }
  if (Array.isArray(data)) {
    if (!data.length) return <span className="muted">None detected</span>
    return <div className="nested">{data.map((item, i) => <div key={i}><SourceValue data={item} /></div>)}</div>
  }
  return <dl className="fields">{Object.entries(data).map(([key, value]) => <div key={key}><dt>{title(key)}</dt><dd><SourceValue data={value} /></dd></div>)}</dl>
}

export default function App() {
  const [documents, setDocuments] = useState([])
  const [selected, setSelected] = useState([])
  const [type, setType] = useState('')
  const [detailId, setDetailId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [job, setJob] = useState(null)
  const [query, setQuery] = useState('')
  const [messages, setMessages] = useState([])
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [asking, setAsking] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [capabilities, setCapabilities] = useState(null)
  const [health, setHealth] = useState(null)
  const [params, setParams] = useState(['1580', '1250'])
  const [calculation, setCalculation] = useState(null)
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)
  const inputRef = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get('/documents', { params: { limit: 500 } })
      setDocuments(data.documents)
      setSelected(ids => ids.filter(id => data.documents.some(doc => doc.id === id)))
    } catch (err) { setError(message(err)) }
  }, [])

  useEffect(() => {
    refresh()
    api.get('/capabilities').then(({ data }) => setCapabilities(data)).catch(err => setError(message(err)))
    const interval = setInterval(refresh, 2500)
    const checkHealth = () => api.get('/ready').then(({ data }) => setHealth(data)).catch(err => setHealth(err.response?.data || { ready: false }))
    checkHealth()
    const healthInterval = setInterval(checkHealth, 15000)
    return () => { clearInterval(interval); clearInterval(healthInterval) }
  }, [refresh])

  useEffect(() => {
    let active = true
    const load = async () => {
      if (!detailId) return
      try {
        const [doc, status] = await Promise.all([api.get(`/documents/${detailId}`), api.get(`/documents/${detailId}/status`)])
        if (active) { setDetail(doc.data); setJob(status.data.job) }
      } catch (err) { if (active) setError(message(err)) }
    }
    load()
    const interval = setInterval(load, 2500)
    return () => { active = false; clearInterval(interval) }
  }, [detailId])

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, asking])

  const upload = async files => {
    if (!files.length || uploading) return
    if (capabilities && files.length > capabilities.max_files_per_upload) {
      setError(`Choose at most ${capabilities.max_files_per_upload} files.`); return
    }
    setUploading(true); setProgress(0); setError(''); setNotice('')
    const body = new FormData()
    Array.from(files).forEach(file => body.append('files', file))
    try {
      const { data } = await api.post('/documents/upload', body, { onUploadProgress: event => setProgress(Math.round((event.loaded / (event.total || event.loaded)) * 100)) })
      setNotice(`${data.documents.length} file(s) accepted. Processing continues in the background.`)
      if (data.errors.length) setError(data.errors.map(item => `${item.filename}: ${item.error}`).join('\n'))
      await refresh()
    } catch (err) {
      setError(err.response?.data?.errors?.map(item => `${item.filename}: ${item.error}`).join('\n') || message(err))
    } finally { setUploading(false); if (inputRef.current) inputRef.current.value = '' }
  }

  const ask = async event => {
    event.preventDefault()
    if (!query.trim() || asking) return
    const question = query.trim()
    setMessages(previous => [...previous, { role: 'user', text: question }])
    setQuery(''); setAsking(true)
    try {
      const { data } = await api.post('/chat/query', { question, document_ids: selected, document_types: type ? [type] : [] })
      setMessages(previous => [...previous, { role: 'assistant', text: data.answer, citations: data.citations, mode: data.answer_mode }])
    } catch (err) {
      setMessages(previous => [...previous, { role: 'assistant', text: message(err), error: true }])
    } finally { setAsking(false) }
  }

  const action = async (doc, operation) => {
    setBusy(true); setError('')
    try {
      if (operation === 'delete') {
        await api.delete(`/documents/${doc.id}`)
        if (detailId === doc.id) { setDetailId(null); setDetail(null) }
      } else {
        await api.post(`/documents/${doc.id}/reindex`)
        setNotice(`${doc.original_filename} queued for reindexing.`)
      }
      await refresh()
    } catch (err) { setError(message(err)) }
    finally { setBusy(false) }
  }

  const calculate = async event => {
    event.preventDefault()
    try {
      const { data } = await api.post('/analysis/calculate', { calc_type: 'yoy', param1: params[0], param2: params[1], metric_name: 'Revenue' })
      setCalculation(data.result); setError('')
    } catch (err) { setError(message(err)) }
  }
  const visible = documents.filter(doc => !type || doc.document_type === type)

  return <div className="app-container">
    <header className="topbar"><div><h1>FinScope<span>.AI</span></h1><p>Financial documents, connected to their evidence.</p></div>
      <div className={`service-state ${health?.ready ? 'ready' : ''}`} title={JSON.stringify(health?.checks || {})}>{health?.ready ? 'Services ready' : 'Services starting or unavailable'}</div>
    </header>
    <main className="workspace">
      <section className="document-panel" aria-label="Document workspace">
        <div className={`upload-area ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); upload(e.dataTransfer.files) }}>
          <Upload size={26} /><div><strong>Drop your documents here</strong><p>PDF, images, Word, Excel, CSV, text, Markdown, PowerPoint and HTML</p>
          <small>{capabilities ? `Up to ${capabilities.max_files_per_upload} files · ${sizeLabel(capabilities.max_file_size)} per file` : 'Multiple files supported'}</small></div>
          <label className="button primary">{uploading ? `Uploading ${progress}%` : 'Choose files'}<input ref={inputRef} type="file" multiple accept={capabilities?.supported_formats.join(',') || defaultFormats} disabled={uploading} onChange={e => upload(e.target.files)} /></label>
          {uploading && <progress value={progress} max="100" aria-label="Upload progress" />}
        </div>
        {error && <div role="alert" className="notice error">{error}<button aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
        {notice && <div role="status" className="notice">{notice}<button aria-label="Dismiss notice" onClick={() => setNotice('')}>×</button></div>}
        <div className="section-toolbar"><h2>Documents <span className="muted">{documents.length}</span></h2><div className="row">
          <select aria-label="Filter document type" value={type} onChange={e => setType(e.target.value)}><option value="">All types</option>{['invoice', 'devis', 'bilan', 'other'].map(value => <option key={value}>{value}</option>)}</select>
          <button onClick={refresh} aria-label="Refresh documents"><RefreshCw size={16} /></button></div></div>
        <div className="table-scroll"><table className="documents"><thead><tr><th><span className="sr-only">Select</span></th><th>Filename</th><th>Type</th><th>Confidence</th><th>Status</th><th>Size</th><th>Uploaded</th><th>Actions</th></tr></thead>
          <tbody>{visible.map(doc => <tr key={doc.id} className={detailId === doc.id ? 'active' : ''}>
            <td><input aria-label={`Select ${doc.original_filename} for chat`} type="checkbox" checked={selected.includes(doc.id)} onChange={e => setSelected(ids => e.target.checked ? [...ids, doc.id] : ids.filter(id => id !== doc.id))} /></td>
            <td><button className="filename" onClick={() => { setDetailId(doc.id); setDetail(null) }}><FileText size={15} />{doc.original_filename}</button></td>
            <td>{doc.document_type}</td><td>{Math.round(doc.classification_confidence * 100)}%</td><td><span className={`status ${doc.status.toLowerCase()}`}>{doc.status}</span></td>
            <td>{sizeLabel(doc.size)}</td><td>{new Date(doc.created_at).toLocaleDateString()}</td><td><div className="row"><button aria-label={`Reindex ${doc.original_filename}`} disabled={busy || ['PROCESSING', 'PENDING', 'DELETING'].includes(doc.status)} onClick={() => action(doc, 'reindex')}><RefreshCw size={14} /></button><button aria-label={`Delete ${doc.original_filename}`} disabled={busy || doc.status === 'PROCESSING'} onClick={() => action(doc, 'delete')}><Trash2 size={14} /></button></div></td>
          </tr>)}</tbody></table>{!visible.length && <p className="empty-state">Upload documents to start. Processing status and extracted fields will appear here.</p>}</div>
        {detailId && <section className="detail-card"><div className="section-toolbar"><h2>{detail?.original_filename || 'Loading document…'}</h2><button onClick={() => { setDetailId(null); setDetail(null) }}>Close</button></div>
          {detail && <><p><strong>{detail.document_type}</strong> · {Math.round(detail.classification_confidence * 100)}% confidence · {detail.status}</p>
            {job && <p className={job.error ? 'error-text' : 'muted'}>{job.error || `${job.stage} · ${job.progress}%`}</p>}
            <p>{detail.extraction_metadata.classification?.reason}</p>
            <a href={`${API}/documents/${detail.id}/file`} target="_blank" rel="noreferrer">Open original document <ExternalLink size={13} /></a>
            <details open><summary>Structured extraction</summary><SourceValue data={detail.structured_data} /></details>
            <details><summary>Classification & processing metadata</summary><pre>{JSON.stringify(detail.extraction_metadata, null, 2)}</pre></details>
            <details><summary>Normalized content & table locations</summary>{detail.blocks.map(block => <article className="source-block" key={block.block_id}><small>{[block.type, block.page ? `Page ${block.page}` : null, block.sheet_name, block.cell_range, block.section].filter(Boolean).join(' · ')}</small><pre>{block.text}</pre></article>)}</details>
          </>}
        </section>}
        <details className="calculator"><summary><Calculator size={16} /> Financial calculator</summary><form onSubmit={calculate}><label>Current period<input value={params[0]} onChange={e => setParams([e.target.value, params[1]])} required /></label><label>Prior period<input value={params[1]} onChange={e => setParams([params[0], e.target.value])} required /></label><button type="submit">Calculate YoY growth</button></form>{calculation && <p><strong>{calculation.formatted_result}</strong> · {calculation.formula_used}</p>}</details>
      </section>
      <aside className="chat-panel" aria-label="Document chat"><div className="chat-heading"><h2>Ask your documents</h2><p>{selected.length ? `${selected.length} selected document(s)` : 'All completed documents'}{type ? ` · ${type}` : ''}</p>{selected.length > 0 && <button onClick={() => setSelected([])}>Clear selection</button>}</div>
        <div className="chat-messages" aria-live="polite">{!messages.length && <div className="chat-intro"><FileText size={28} /><h3>Answers with traceable sources</h3><p>Ask in French or English. Select documents to narrow your search.</p><button onClick={() => setQuery('Quel est le montant total de la facture ?')}>Find an invoice total</button><button onClick={() => setQuery('Compare le devis avec la facture.')}>Compare a quote and invoice</button><button onClick={() => setQuery('Quel est le résultat net indiqué dans le bilan ?')}>Find net income</button></div>}
          {messages.map((item, index) => <article key={index} className={`chat-message ${item.role} ${item.error ? 'error' : ''}`}><small>{item.role === 'user' ? 'You' : `FinScope · ${item.mode || 'assistant'}`}</small><div className="answer-text">{item.text}</div>
            {item.citations?.length > 0 && <div className="citations">{item.citations.map(citation => <details key={citation.citation_id}><summary>[{citation.citation_id}] {citation.label}</summary><blockquote>{citation.excerpt}</blockquote><div className="row"><a href={`${API}/documents/${citation.document_id}/file${citation.page ? `#page=${citation.page}` : ''}`} target="_blank" rel="noreferrer">Open source</a><button onClick={() => { setDetailId(citation.document_id); setDetail(null) }}>View extraction</button></div></details>)}</div>}
          </article>)}{asking && <p className="muted">Retrieving evidence and preparing an answer…</p>}<div ref={endRef} />
        </div><form className="chat-form" onSubmit={ask}><label className="sr-only" htmlFor="question">Question</label><textarea id="question" value={query} onChange={e => setQuery(e.target.value)} maxLength={4000} placeholder="Ask a question about your documents…" rows={3} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(e) } }} /><button className="primary" disabled={asking || !query.trim()} type="submit" aria-label="Send question"><Send size={18} /></button></form>
      </aside>
    </main>
  </div>
}
