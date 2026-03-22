# BRIEF: Fix Enrich display + Add View/Edit modal + Add Save/Load (localStorage)
## Repo: phanvuhoang/taxparse

---

## Bug 1: Enrich button works but Taxonomy/Topics columns don't update

### Root cause
After `/enrich` returns, `handleEnriched()` re-fetches from `/sessions/{id}` and calls:
```js
setSession(s => ({ ...s, items: data.items, total: data.total }))
```
But `ResultsTable` receives `session` as a prop and uses `session.items` directly. React may not re-render the table because the top-level `session` reference was updated with a functional updater that returns a new object — **but the real bug is that `GET /sessions/{id}` returns items without the enriched fields** because `get_session` in `backend/main.py` reconstructs rows via `dict(zip(cols, r))` from a DB cursor — but wait, there's no DB. Items are in `_sessions[session_id]['items']` in memory.

**Actual bug:** `GET /sessions/{session_id}` returns the live in-memory items (already enriched), but `handleEnriched` runs while enrich is still async in the background on the backend. The `/enrich` endpoint in `backend/main.py` calls `enrich_items_batch(...)` synchronously — so it should be done when it returns. The actual problem is a **stale closure / React state update** — `setSession(s => ({...s, items: data.items}))` works but `ResultsTable` is getting `session` from parent state which should update.

### Real fix: force re-render with a new object key

In `handleEnriched`, add a `_enriched_at` timestamp to force React to see the session as changed:

```js
const handleEnriched = async () => {
  if (!session) return
  try {
    const res = await fetch(`${API}/sessions/${session.session_id}?limit=5000`)
    const data = await res.json()
    // Spread into a new object + add timestamp to force re-render
    setSession({ ...session, items: data.items, total: data.total, _enriched_at: Date.now() })
  } catch (e) {
    console.error('Failed to refresh after enrich:', e)
  }
}
```

Also: after enrich completes, show a **toast notification** in `EnrichPanel`:

```jsx
// In EnrichPanel, after onEnriched() call:
const handleEnrich = async () => {
  const result = await call(async () => {
    const res = await fetch(`${API}/enrich`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, model }),
    })
    if (!res.ok) { const d = await res.json(); throw new Error(d.detail || 'Enrich failed') }
    return res.json()
  })
  if (result) {
    setLastResult(result)  // { enriched: N, total: N }
    await onEnriched()     // re-fetch session
  }
}

// Add state:
const [lastResult, setLastResult] = useState(null)

// Show result below button:
{lastResult && (
  <p className="text-xs text-green-700 font-medium">
    ✓ Tagged {lastResult.enriched}/{lastResult.total} items
  </p>
)}
```

---

## Feature 2: View Full Text + Edit item (modal)

### 2.1 Add "View / Edit" button to each table row

In `ResultsTable`, add an **Actions column** (last column):

```jsx
<th className="px-3 py-2 text-left w-20">Actions</th>
```

```jsx
<td className="px-3 py-2">
  <button onClick={() => setEditItem(item)}
    className="text-xs text-blue-600 hover:text-blue-800 underline">
    View/Edit
  </button>
</td>
```

Add state: `const [editItem, setEditItem] = useState(null)`

### 2.2 ItemModal component

Add this component (before `ResultsTable`):

```jsx
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
```

### 2.3 Wire up modal in ResultsTable

Add to `ResultsTable`:
```js
const [editItem, setEditItem] = useState(null)

const handleSaveItem = (updatedItem) => {
  // Update in local session.items
  onItemUpdate(updatedItem)  // callback to parent
}
```

Add `onItemUpdate` prop to `ResultsTable`:
```jsx
<ResultsTable session={session} onItemUpdate={handleItemUpdate} />
```

In `App`:
```js
const handleItemUpdate = (updatedItem) => {
  setSession(s => ({
    ...s,
    items: s.items.map(i => i.reg_code === updatedItem.reg_code ? updatedItem : i)
  }))
}
```

Add modal render at bottom of ResultsTable return:
```jsx
{editItem && (
  <ItemModal
    item={editItem}
    onSave={handleSaveItem}
    onClose={() => setEditItem(null)}
  />
)}
```

---

## Feature 3: Save / Load session (localStorage)

Sessions are in-memory on backend — they vanish on page refresh. Fix with **localStorage persistence** on the frontend.

### 3.1 Auto-save to localStorage after every change

In `App`, add a `useEffect` that saves session to localStorage whenever it changes:

```js
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

// Auto-restore session on mount
useEffect(() => {
  try {
    const saved = localStorage.getItem('taxparse_session')
    const savedAt = localStorage.getItem('taxparse_session_saved_at')
    if (saved) {
      const parsed = JSON.parse(saved)
      if (parsed?.items?.length > 0) {
        setSession(parsed)
        setSavedAt(savedAt)
        setRestoredFromCache(true)
      }
    }
  } catch {}
}, [])
```

Add states: `const [savedAt, setSavedAt] = useState(null)` and `const [restoredFromCache, setRestoredFromCache] = useState(false)`

### 3.2 Show restore banner + clear button

Below the header, when restored from cache:

```jsx
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
```

### 3.3 Manual Export buttons (already exist — just confirm)

The existing `⬇ Export CSV` and `⬇ Export JSONL` buttons in `ResultsTable` already work via backend `/export/csv/{id}` and `/export/jsonl/{id}`. These download files to anh's computer — that's the permanent save.

**Important:** after localStorage restore, the session_id still works for export ONLY if the backend container hasn't restarted. Add a fallback:

In `ResultsTable`, make export buttons do **client-side CSV** if backend export fails:

```jsx
const handleExportCSV = async () => {
  // Try backend export first
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

  // Fallback: client-side CSV from localStorage session
  const FIELDS = ['reg_code','tax_type','doc_ref','chapter','article_no','article_title',
                  'clause_no','letter','level','topics','taxonomy_codes','keywords',
                  'importance','cross_refs','paragraph_text','notes']
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
```

Replace the `<a href=...>` export links with `<button onClick={handleExportCSV}>`.

---

## SUMMARY — Files to Create/Modify

| Action | File | Change |
|--------|------|--------|
| MODIFY | `frontend/src/App.jsx` | Fix enrich re-render (Bug 1); Add `ItemModal` component (Feature 2); Add localStorage save/restore (Feature 3); Add `onItemUpdate` prop; Client-side CSV fallback |

**Backend: NO changes needed.**

---

## NOTES FOR CLAUDE CODE

1. **Bug 1 fix is 2 lines** — add `Date.now()` spread + `setLastResult` display
2. **ItemModal**: all fields except `paragraph_text` are editable. Full text is read-only (scrollable box).
3. **localStorage key**: `taxparse_session` — saves entire session object including items + meta
4. **Client-side CSV**: use `\ufeff` BOM prefix for Excel UTF-8 compatibility
5. **`notes` field**: not in original parser output — handle with `|| ''` default everywhere
6. **Do NOT add new npm dependencies** — use only React + fetch + browser APIs
7. After all changes: commit + push
