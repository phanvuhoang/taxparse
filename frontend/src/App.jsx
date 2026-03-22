import React, { useState, useCallback, useEffect } from 'react'

const API = ''

function useApi() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const call = useCallback(async (fn) => {
    setLoading(true); setError('')
    try { return await fn() }
    catch (e) { setError(e.message); return null }
    finally { setLoading(false) }
  }, [])
  return { loading, error, call }
}

// ── Upload & Parse Panel ──────────────────────────────────────────────────────
function ParsePanel({ onParsed }) {
  const { loading, error, call } = useApi()
  const [file, setFile] = useState(null)
  const [docRef, setDocRef] = useState('')
  const [docSlug, setDocSlug] = useState('')
  const [taxType, setTaxType] = useState('CIT')

  const TAX_TYPES = ['CIT', 'VAT', 'PIT', 'FCT', 'TP', 'TaxAdmin', 'CIT/FCT', 'VAT/FCT']

  const handleFile = (e) => {
    const f = e.target.files[0]
    if (!f) return
    setFile(f)
    const base = f.name.replace(/\s*-\s*ENG\.docx?$/i, '').replace(/\s*-\s*VIE\.docx?$/i, '').trim()
    setDocRef(base)
    setDocSlug(base.replace(/[^a-zA-Z0-9]/g, '').substring(0, 25))
  }

  const handleParse = async () => {
    if (!file) return
    const result = await call(async () => {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('doc_ref', docRef)
      fd.append('doc_slug', docSlug)
      fd.append('tax_type', taxType)
      const res = await fetch(`${API}/parse`, { method: 'POST', body: fd })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || 'Parse failed') }
      return res.json()
    })
    if (result) onParsed(result)
  }

  return (
    <div className="bg-white rounded-xl border p-5 space-y-4">
      <h2 className="font-semibold text-gray-800">📄 Upload & Parse</h2>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Regulation file (.docx or .txt)</label>
        <input type="file" accept=".docx,.txt" onChange={handleFile}
          className="text-sm text-gray-600 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-xs file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100" />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Document Reference</label>
          <input value={docRef} onChange={e => setDocRef(e.target.value)}
            placeholder="e.g. Decree 320/2025/ND-CP"
            className="w-full border rounded px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Doc Slug (URL-safe)</label>
          <input value={docSlug} onChange={e => setDocSlug(e.target.value)}
            placeholder="e.g. Decree320-2025"
            className="w-full border rounded px-3 py-1.5 text-sm" />
        </div>
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Tax Type</label>
        <select value={taxType} onChange={e => setTaxType(e.target.value)}
          className="border rounded px-3 py-1.5 text-sm">
          {TAX_TYPES.map(t => <option key={t}>{t}</option>)}
        </select>
      </div>

      {error && <p className="text-red-500 text-xs">{error}</p>}

      <button onClick={handleParse} disabled={!file || loading}
        className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
        {loading ? 'Parsing...' : '▶ Parse Document'}
      </button>
    </div>
  )
}

// ── Item Modal ─────────────────────────────────────────────────────────────────
function ItemModal({ item, onSave, onClose }) {
  const [form, setForm] = useState({ ...item })

  const handleChange = (field, value) => {
    setForm(f => ({ ...f, [field]: value }))
  }

  const handleSave = () => {
    onSave(form)
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div>
            <p className="font-mono text-sm text-blue-700 font-semibold">{item.reg_code}</p>
            <p className="text-xs text-gray-500">{item.doc_ref} · {item.article_no} · {item.chapter}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none">✕</button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4">
          {/* Full text — read-only */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Full Paragraph Text</label>
            <div className="bg-gray-50 border rounded-lg p-3 text-sm text-gray-800 whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto">
              {item.paragraph_text}
            </div>
          </div>

          {/* Editable enrichment fields */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Topics</label>
              <input value={form.topics || ''} onChange={e => handleChange('topics', e.target.value)}
                className="w-full border rounded px-3 py-1.5 text-sm" placeholder="e.g. Deductible expenses — R&D" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Importance</label>
              <select value={form.importance || 'medium'} onChange={e => handleChange('importance', e.target.value)}
                className="w-full border rounded px-3 py-1.5 text-sm">
                <option value="high">High — key rule</option>
                <option value="medium">Medium — standard provision</option>
                <option value="low">Low — procedural/admin</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Taxonomy Codes (comma-separated)</label>
            <input value={form.taxonomy_codes || ''} onChange={e => handleChange('taxonomy_codes', e.target.value)}
              className="w-full border rounded px-3 py-1.5 text-sm font-mono" placeholder="e.g. CIT-08,CIT-09" />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Matched Codes (comma-separated)</label>
            <input value={form.matched_codes || ''} onChange={e => handleChange('matched_codes', e.target.value)}
              className="w-full border rounded px-3 py-1.5 text-sm font-mono"
              placeholder="e.g. A1a,B2b (from uploaded match list)" />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Keywords</label>
            <input value={form.keywords || ''} onChange={e => handleChange('keywords', e.target.value)}
              className="w-full border rounded px-3 py-1.5 text-sm" placeholder="e.g. deductible, R&D, conditions" />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Cross References</label>
            <input value={form.cross_refs || ''} onChange={e => handleChange('cross_refs', e.target.value)}
              className="w-full border rounded px-3 py-1.5 text-sm" placeholder="e.g. Article 10, Circular 78/2014" />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Notes</label>
            <textarea value={form.notes || ''} onChange={e => handleChange('notes', e.target.value)}
              rows={3} className="w-full border rounded px-3 py-1.5 text-sm resize-none"
              placeholder="Personal notes, practice tips, exam relevance..." />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t bg-gray-50">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Cancel</button>
          <button onClick={handleSave} className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
            ✓ Save Changes
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Results Table ─────────────────────────────────────────────────────────────
function ResultsTable({ session, onItemUpdate }) {
  const [filter, setFilter] = useState({ search: '', level: '', article: '', taxonomy: '' })
  const [page, setPage] = useState(0)
  const [editItem, setEditItem] = useState(null)
  const PER_PAGE = 50

  if (!session) return null

  let items = session.items || []

  if (filter.search) {
    const s = filter.search.toLowerCase()
    items = items.filter(i =>
      i.reg_code.toLowerCase().includes(s) ||
      i.paragraph_text.toLowerCase().includes(s) ||
      (i.topics || '').toLowerCase().includes(s)
    )
  }
  if (filter.level) items = items.filter(i => i.level === filter.level)
  if (filter.article) items = items.filter(i => i.article_no?.includes(filter.article))
  if (filter.taxonomy) items = items.filter(i => (i.taxonomy_codes || '').includes(filter.taxonomy))

  const total = items.length
  const paged = items.slice(page * PER_PAGE, (page + 1) * PER_PAGE)
  const pages = Math.ceil(total / PER_PAGE)

  const LEVEL_COLORS = { letter: 'bg-blue-50 text-blue-700', clause: 'bg-green-50 text-green-700', article: 'bg-purple-50 text-purple-700' }
  const IMP_COLORS = { high: 'text-red-600 font-semibold', medium: 'text-gray-700', low: 'text-gray-400' }

  const handleSaveItem = (updatedItem) => {
    onItemUpdate(updatedItem)
  }

  const handleExportCSV = async () => {
    try {
      const res = await fetch(`${API}/export/csv/${session.session_id}`)
      if (res.ok) {
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a'); a.href = url
        a.download = `${session.meta?.doc_slug || 'taxparse'}_parsed.csv`
        a.click(); URL.revokeObjectURL(url)
        return
      }
    } catch {}

    // Fallback: client-side CSV from session in memory
    const FIELDS = ['reg_code','tax_type','doc_ref','chapter','article_no','article_title',
                    'clause_no','letter','level','topics','taxonomy_codes','matched_codes',
                    'keywords','importance','cross_refs','paragraph_text','notes']
    const rows = [FIELDS.join(',')]
    for (const item of session.items) {
      rows.push(FIELDS.map(f => {
        const v = String(item[f] || '')
        return v.includes(',') || v.includes('\n') ? `"${v.replace(/"/g, '""')}"` : v
      }).join(','))
    }
    const blob = new Blob(['\ufeff' + rows.join('\n')], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url
    a.download = `${session.meta?.doc_slug || 'taxparse'}_parsed.csv`
    a.click(); URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-3">
      {/* Summary */}
      <div className="flex items-center gap-4 text-sm text-gray-600">
        <span className="font-medium">{session.total} items parsed</span>
        {Object.entries(session.levels || {}).map(([k, v]) => (
          <span key={k} className={`px-2 py-0.5 rounded text-xs ${LEVEL_COLORS[k] || 'bg-gray-100'}`}>{k}: {v}</span>
        ))}
        <button onClick={handleExportCSV}
          className="ml-auto px-3 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700">
          ⬇ Export CSV
        </button>
        <a href={`${API}/export/jsonl/${session.session_id}`}
          className="px-3 py-1 bg-gray-600 text-white text-xs rounded hover:bg-gray-700">
          ⬇ Export JSONL
        </a>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        <input value={filter.search} onChange={e => { setFilter(f => ({...f, search: e.target.value})); setPage(0) }}
          placeholder="Search text / reg_code / topic..." className="border rounded px-3 py-1.5 text-sm flex-1 min-w-48" />
        <input value={filter.article} onChange={e => { setFilter(f => ({...f, article: e.target.value})); setPage(0) }}
          placeholder="Article..." className="border rounded px-3 py-1.5 text-sm w-28" />
        <select value={filter.level} onChange={e => { setFilter(f => ({...f, level: e.target.value})); setPage(0) }}
          className="border rounded px-3 py-1.5 text-sm">
          <option value="">All levels</option>
          <option value="letter">Letter</option>
          <option value="clause">Clause</option>
        </select>
        <input value={filter.taxonomy} onChange={e => { setFilter(f => ({...f, taxonomy: e.target.value})); setPage(0) }}
          placeholder="Taxonomy code..." className="border rounded px-3 py-1.5 text-sm w-36" />
        {(filter.search || filter.level || filter.article || filter.taxonomy) && (
          <button onClick={() => { setFilter({ search:'', level:'', article:'', taxonomy:'' }); setPage(0) }}
            className="text-xs text-gray-500 underline hover:text-gray-700">Clear</button>
        )}
        <span className="text-xs text-gray-400 self-center ml-auto">Showing {paged.length} of {total}</span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto border rounded-lg">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500 uppercase">
            <tr>
              <th className="px-3 py-2 text-left w-56">Reg Code</th>
              <th className="px-3 py-2 text-left w-20">Level</th>
              <th className="px-3 py-2 text-left w-24">Article</th>
              <th className="px-3 py-2 text-left">Paragraph Text</th>
              <th className="px-3 py-2 text-left w-32">Topics</th>
              <th className="px-3 py-2 text-left w-28">Taxonomy</th>
              <th className="px-3 py-2 text-left w-28">Matched</th>
              <th className="px-3 py-2 text-left w-16">Imp.</th>
              <th className="px-3 py-2 text-left w-20">Actions</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((item, idx) => (
              <tr key={item.reg_code} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                <td className="px-3 py-2 font-mono text-blue-700 whitespace-nowrap">{item.reg_code}</td>
                <td className="px-3 py-2">
                  <span className={`px-1.5 py-0.5 rounded text-xs ${LEVEL_COLORS[item.level] || ''}`}>{item.level}</span>
                </td>
                <td className="px-3 py-2 text-gray-500 whitespace-nowrap">{item.article_no}</td>
                <td className="px-3 py-2 text-gray-700 max-w-md">
                  <div className="line-clamp-3">{item.paragraph_text}</div>
                </td>
                <td className="px-3 py-2 text-gray-600 italic">{item.topics}</td>
                <td className="px-3 py-2">
                  {(item.taxonomy_codes || '').split(',').filter(Boolean).map(c => (
                    <span key={c} className="inline-block bg-amber-100 text-amber-800 text-xs px-1 rounded mr-1 mb-0.5">{c}</span>
                  ))}
                </td>
                <td className="px-3 py-2">
                  {(item.matched_codes || '').split(',').filter(Boolean).map(c => (
                    <span key={c} className="inline-block bg-purple-100 text-purple-800 text-xs px-1 rounded mr-1 mb-0.5">{c}</span>
                  ))}
                </td>
                <td className={`px-3 py-2 text-xs ${IMP_COLORS[item.importance] || ''}`}>{item.importance}</td>
                <td className="px-3 py-2">
                  <button onClick={() => setEditItem(item)}
                    className="text-xs text-blue-600 hover:text-blue-800 underline">
                    View/Edit
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex items-center gap-2 justify-center text-sm">
          <button onClick={() => setPage(p => Math.max(0, p-1))} disabled={page === 0}
            className="px-3 py-1 border rounded disabled:opacity-40">← Prev</button>
          <span className="text-gray-500">Page {page+1} / {pages}</span>
          <button onClick={() => setPage(p => Math.min(pages-1, p+1))} disabled={page === pages-1}
            className="px-3 py-1 border rounded disabled:opacity-40">Next →</button>
        </div>
      )}

      {editItem && (
        <ItemModal
          item={editItem}
          onSave={handleSaveItem}
          onClose={() => setEditItem(null)}
        />
      )}
    </div>
  )
}

// ── Match Panel ───────────────────────────────────────────────────────────────
function MatchPanel({ sessionId, onMatched }) {
  const { loading, error, call } = useApi()
  const [file, setFile] = useState(null)
  const [listLoaded, setListLoaded] = useState(null)
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [model, setModel] = useState('claude-haiku-4.5')

  const handleUpload = async (selectedFile) => {
    const f = selectedFile || file
    if (!f) return
    setListLoaded(null)
    const result = await call(async () => {
      const fd = new FormData()
      fd.append('file', f)
      fd.append('session_id', sessionId)
      const res = await fetch(`${API}/match-list`, { method: 'POST', body: fd })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || 'Upload failed') }
      return res.json()
    })
    if (result) setListLoaded(result)
  }

  const handleMatch = async () => {
    const result = await call(async () => {
      const res = await fetch(`${API}/match`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, model }),
      })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || 'Match failed') }
      return res.json()
    })
    if (result?.job_id) {
      setJobId(result.job_id)
      setJobStatus({ status: 'running', progress: 0, total: result.total })
      pollJob(result.job_id)
    }
  }

  const pollJob = async (jid) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API}/jobs/${jid}`)
        const d = await res.json()
        setJobStatus(d)
        if (d.status === 'done' || d.status === 'failed') {
          clearInterval(interval)
          if (d.status === 'done') onMatched()
        }
      } catch { clearInterval(interval) }
    }, 1500)
  }

  const progressPct = jobStatus?.total > 0
    ? Math.round((jobStatus.progress / jobStatus.total) * 100) : 0

  return (
    <div className="bg-purple-50 border border-purple-200 rounded-xl p-4 space-y-3">
      <div className="flex items-center gap-2">
        <p className="text-sm font-medium text-purple-800">🔗 Custom Match List</p>
        <span className="text-xs text-purple-500">Upload syllabus or taxonomy CSV/JSON → AI match each item</span>
      </div>

      {/* Upload */}
      <div className="flex items-center gap-3 flex-wrap">
        <input type="file" accept=".csv,.json"
          onChange={e => { const f = e.target.files[0]; setFile(f); if(f) handleUpload(f) }}
          className="text-xs text-gray-600 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:text-xs file:bg-purple-100 file:text-purple-700" />
        {loading && <span className="text-xs text-purple-600 animate-pulse">Loading list…</span>}
        {listLoaded && (
          <span className="text-xs text-green-700 font-medium">
            ✓ {listLoaded.loaded} codes loaded
            {listLoaded.preview && (
              <span className="text-gray-500 ml-1">
                ({Object.keys(listLoaded.preview).slice(0,3).join(', ')}...)
              </span>
            )}
          </span>
        )}
      </div>

      {/* Match */}
      {listLoaded && (
        <div className="flex items-center gap-3 flex-wrap">
          <select value={model} onChange={e => setModel(e.target.value)}
            className="border rounded px-2 py-1 text-xs">
            <option value="claude-haiku-4.5">Haiku (fast)</option>
            <option value="claude-sonnet-4.6">Sonnet (accurate)</option>
          </select>
          <button onClick={handleMatch} disabled={!!jobId && jobStatus?.status === 'running'}
            className="px-3 py-1.5 bg-purple-700 text-white text-xs rounded hover:bg-purple-800 disabled:opacity-50">
            {jobStatus?.status === 'running' ? 'Matching...' : '▶ Run Match'}
          </button>

          {jobStatus?.status === 'running' && (
            <div className="flex items-center gap-2 flex-1 min-w-48">
              <div className="flex-1 bg-purple-200 rounded-full h-1.5">
                <div className="bg-purple-600 h-1.5 rounded-full transition-all"
                  style={{ width: `${progressPct}%` }} />
              </div>
              <span className="text-xs text-purple-600 whitespace-nowrap">
                {jobStatus.progress}/{jobStatus.total}
              </span>
            </div>
          )}

          {jobStatus?.status === 'done' && (
            <span className="text-xs text-green-700 font-medium">
              ✓ Matched {jobStatus.matched}/{jobStatus.total} items
            </span>
          )}
          {jobStatus?.status === 'failed' && (
            <span className="text-xs text-red-600">{jobStatus.error || 'Match failed'}</span>
          )}
        </div>
      )}

      {error && <p className="text-red-500 text-xs">{error}</p>}
    </div>
  )
}

// ── Enrich Panel ──────────────────────────────────────────────────────────────
function EnrichPanel({ sessionId, onEnriched }) {
  const [model, setModel] = useState('claude-haiku-4.5')
  const [jobStatus, setJobStatus] = useState(null)   // {status, progress, total, matched}
  const [error, setError] = useState(null)
  const running = jobStatus?.status === 'running'

  const pollJob = (jid) => {
    const iv = setInterval(async () => {
      try {
        const r = await fetch(`${API}/jobs/${jid}`)
        const d = await r.json()
        setJobStatus(d)
        if (d.status === 'done' || d.status === 'failed') {
          clearInterval(iv)
          if (d.status === 'done') onEnriched(null)  // trigger re-fetch from session
        }
      } catch { clearInterval(iv) }
    }, 1200)
  }

  const handleEnrich = async () => {
    setError(null)
    setJobStatus({ status: 'running', progress: 0, total: 0, matched: 0 })
    try {
      const res = await fetch(`${API}/enrich`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, model }),
      })
      const d = await res.json()
      if (!res.ok) { setError(d.detail || 'Enrich failed'); setJobStatus(null); return }
      setJobStatus(s => ({ ...s, total: d.total }))
      pollJob(d.job_id)
    } catch (e) {
      setError(e.message)
      setJobStatus(null)
    }
  }

  const pct = jobStatus?.total > 0 ? Math.round((jobStatus.progress / jobStatus.total) * 100) : 0

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-2">
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-amber-800">🏷 AI Taxonomy Enrichment</p>
          <p className="text-xs text-amber-600">Classify items into topics, taxonomy codes & keywords using AI</p>
        </div>
        <select value={model} onChange={e => setModel(e.target.value)}
          className="border rounded px-2 py-1 text-sm" disabled={running}>
          <option value="claude-haiku-4.5">Haiku (fast)</option>
          <option value="claude-sonnet-4.6">Sonnet (accurate)</option>
        </select>
        <button onClick={handleEnrich} disabled={running}
          className="px-4 py-2 bg-amber-600 text-white text-sm rounded hover:bg-amber-700 disabled:opacity-50 whitespace-nowrap">
          {running ? 'Enriching…' : '▶ Run AI Enrich'}
        </button>
      </div>

      {/* Progress bar */}
      {running && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-amber-700">
            <span>Processing batch {Math.ceil((jobStatus.progress||0)/15)}/{Math.ceil((jobStatus.total||1)/15)}…</span>
            <span>{jobStatus.progress||0}/{jobStatus.total||'?'} items ({pct}%)</span>
          </div>
          <div className="w-full bg-amber-200 rounded-full h-2">
            <div className="bg-amber-600 h-2 rounded-full transition-all duration-500"
              style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}

      {/* Result */}
      {jobStatus?.status === 'done' && (
        <p className="text-xs text-green-700 font-medium">
          ✓ Tagged {jobStatus.matched}/{jobStatus.total} items — download CSV to see all results
        </p>
      )}
      {jobStatus?.status === 'failed' && (
        <p className="text-xs text-red-600">⚠ {jobStatus.error || 'Enrichment failed'}</p>
      )}
      {error && <p className="text-red-500 text-xs">⚠ {error}</p>}
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [session, setSession] = useState(null)
  const [savedAt, setSavedAt] = useState(null)
  const [restoredFromCache, setRestoredFromCache] = useState(false)

  // Auto-restore session on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem('taxparse_session')
      const savedAtVal = localStorage.getItem('taxparse_session_saved_at')
      if (saved) {
        const parsed = JSON.parse(saved)
        if (parsed?.items?.length > 0) {
          setSession(parsed)
          setSavedAt(savedAtVal)
          setRestoredFromCache(true)
        }
      }
    } catch {}
  }, [])

  // Auto-save session to localStorage
  useEffect(() => {
    if (session) {
      try {
        localStorage.setItem('taxparse_session', JSON.stringify(session))
        localStorage.setItem('taxparse_session_saved_at', new Date().toISOString())
      } catch (e) {
        console.warn('localStorage save failed:', e)
      }
    }
  }, [session])

  const handleParsed = (result) => {
    setRestoredFromCache(false)
    setSession(result)
  }

  const handleEnriched = (_ignored) => {
    if (!session) return
    // Re-fetch enriched items from backend session (still in memory — same container)
    fetch(`${API}/sessions/${session.session_id}?limit=5000`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data?.items) setSession(s => ({ ...s, items: data.items, total: data.total, _enriched_at: Date.now() }))
      })
      .catch(() => {})
  }

  const handleItemUpdate = (updatedItem) => {
    setSession(s => ({
      ...s,
      items: s.items.map(i => i.reg_code === updatedItem.reg_code ? updatedItem : i)
    }))
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b px-6 py-4">
        <h1 className="text-xl font-bold text-gray-900">
          ⚖️ <span className="text-blue-600">taxparse</span>
          <span className="text-gray-400 font-normal text-sm ml-3">VN Tax Regulation Parser & Classifier</span>
        </h1>
      </header>

      {restoredFromCache && (
        <div className="bg-blue-50 border-b border-blue-200 px-6 py-2 flex items-center gap-3 text-sm text-blue-700">
          <span>📂 Restored previous session ({session?.total} items) — saved {savedAt ? new Date(savedAt).toLocaleString() : ''}</span>
          <button onClick={() => {
            localStorage.removeItem('taxparse_session')
            localStorage.removeItem('taxparse_session_saved_at')
            setSession(null)
            setRestoredFromCache(false)
          }} className="ml-auto text-xs text-blue-500 hover:text-blue-700 underline">
            Clear & start fresh
          </button>
        </div>
      )}

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-5">
        <ParsePanel onParsed={handleParsed} />

        {session && (
          <>
            <EnrichPanel sessionId={session.session_id} onEnriched={handleEnriched} />
            <MatchPanel sessionId={session.session_id} onMatched={handleEnriched} />
            <ResultsTable session={session} onItemUpdate={handleItemUpdate} />
          </>
        )}

        {!session && (
          <div className="text-center py-16 text-gray-400">
            <p className="text-4xl mb-3">📋</p>
            <p>Upload a .docx regulation file to get started</p>
            <p className="text-sm mt-1">Supports: CIT · VAT · PIT · FCT · TP · TaxAdmin</p>
          </div>
        )}
      </main>
    </div>
  )
}


