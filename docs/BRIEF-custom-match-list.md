# BRIEF: Upload Custom Match List (Syllabus / Taxonomy) + Match & Download
## Repo: phanvuhoang/taxparse

---

## Context

After parsing regulations, users want to match each item against a **custom list** — either:
- **ACCA TX(VNM) Syllabus** (from examsgen) — columns: Code, Topic, Detailed Syllabus
- **dbvntax Taxonomy** — columns: Code, Category, Description
- **Any custom list** — just needs Code + Description columns

The flow:
1. Parse regulation file → get items
2. Upload custom match list (CSV or JSON)
3. Click "Match" → AI maps each reg item to 1-3 codes from the list
4. Review matches in table (edit if needed)
5. Download CSV with all columns including matched codes

---

## Backend Changes

### New endpoint: `POST /match-list`

Upload and store a custom match list for the current session.

```python
@app.post("/match-list")
async def upload_match_list(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    code_column: str = Form(default='code'),         # column name for the code
    desc_column: str = Form(default='description'),  # column name for description
):
    """
    Upload CSV or JSON match list.
    Returns preview of parsed codes.
    
    Supported CSV formats:
      - code,description
      - Code,Topic,Detailed Syllabus        (examsgen syllabus)
      - code,category,description           (dbvntax taxonomy)
    
    Supported JSON formats:
      - [{"code": "A1a", "description": "..."}]
      - {"A1a": "description", "A1b": "..."}   (dict)
    """
    import csv, io
    
    content = await file.read()
    suffix = os.path.splitext(file.filename)[1].lower()
    
    codes = {}  # {code: description_text}
    
    if suffix == '.json':
        data = json.loads(content)
        if isinstance(data, list):
            for row in data:
                code = str(row.get(code_column) or row.get('code') or row.get('Code') or '').strip()
                desc_parts = []
                for col in [desc_column, 'description', 'Description', 'detailed_syllabus',
                             'Detailed Syllabus', 'topic', 'Topic']:
                    if col in row and row[col]:
                        desc_parts.append(str(row[col]).strip())
                if code:
                    codes[code] = ' — '.join(dict.fromkeys(desc_parts))[:200]
        elif isinstance(data, dict):
            codes = {str(k): str(v)[:200] for k, v in data.items()}
    
    elif suffix == '.csv':
        reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
        for row in reader:
            # Try to find code column (case-insensitive)
            code = None
            for col in [code_column, 'code', 'Code', 'CODE', 'syllabus_code', 'SyllabusCode']:
                if col in row:
                    code = str(row[col]).strip()
                    break
            
            # Build description from remaining meaningful columns
            desc_parts = []
            for col in [desc_column, 'description', 'Description', 'topic', 'Topic',
                        'detailed_syllabus', 'Detailed Syllabus', 'category', 'Category']:
                if col in row and row[col] and col != (code_column or 'code'):
                    desc_parts.append(str(row[col]).strip())
            
            if code:
                codes[code] = ' — '.join(dict.fromkeys(filter(None, desc_parts)))[:200]
    
    else:
        raise HTTPException(400, f"Unsupported file type: {suffix}. Use .csv or .json")
    
    if not codes:
        raise HTTPException(400, "No codes found in file. Check column names.")
    
    # Store in session
    if session_id not in _sessions:
        _sessions[session_id] = {'items': [], 'meta': {}}
    _sessions[session_id]['match_list'] = codes
    
    return {
        "loaded": len(codes),
        "preview": dict(list(codes.items())[:5]),
        "columns_detected": list(codes.keys())[:3],
    }
```

### New endpoint: `POST /match`

Run AI matching between parsed items and the loaded match list.

```python
@app.post("/match")
def run_match(data: dict, background_tasks: BackgroundTasks):
    """
    Match parsed items against custom list using AI.
    Body: { session_id, model?, batch_size?, force? }
    Returns job_id for polling.
    """
    session_id = data.get('session_id')
    if session_id not in _sessions:
        raise HTTPException(404, 'Session not found')
    
    match_list = _sessions[session_id].get('match_list')
    if not match_list:
        raise HTTPException(400, 'No match list loaded. Upload one first via /match-list')
    
    items = _sessions[session_id]['items']
    if not items:
        raise HTTPException(400, 'No parsed items in session')
    
    force = data.get('force', False)
    model = data.get('model', 'claude-haiku-4-5')
    batch_size = data.get('batch_size', 15)
    
    # Filter to unmatched items unless force=True
    to_match = items if force else [i for i in items if not i.get('matched_codes')]
    
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        'status': 'running',
        'progress': 0,
        'total': len(to_match),
        'matched': 0,
        'result': None,
    }
    
    def run():
        endpoint, key, provider = _get_api_config_from_env()
        if not key:
            _jobs[job_id]['status'] = 'failed'
            _jobs[job_id]['error'] = 'No API key configured'
            return
        
        match_list_text = '\n'.join(
            f'- [{code}] {desc}' for code, desc in list(match_list.items())[:80]
        )
        
        matched_count = 0
        for i in range(0, len(to_match), batch_size):
            batch = to_match[i:i + batch_size]
            items_text = '\n\n'.join(
                f'[{item["reg_code"]}]\n{item.get("paragraph_text","")[:300]}'
                for item in batch
            )
            
            prompt = f"""Match each regulation item to the most relevant codes from the list below.

MATCH LIST:
{match_list_text}

REGULATION ITEMS:
{items_text}

Return ONLY valid JSON mapping reg_code to array of matching codes:
{{
  "CIT-Decree320-2025-Art9.1.a": ["B2a", "B2b"],
  "CIT-Decree320-2025-Art23.1": ["C1a"]
}}

Rules:
- 1-3 codes per item that are DIRECTLY relevant
- Empty array [] if genuinely no match
- Use ONLY codes that appear in the match list above
"""
            try:
                response = _call_ai_openai(prompt, model, endpoint, key)
                json_match = re.search(r'\{[\s\S]+\}', response)
                if json_match:
                    result = json.loads(json_match.group())
                    for item in batch:
                        codes = result.get(item['reg_code'], [])
                        item['matched_codes'] = ','.join(codes)
                        if codes:
                            matched_count += 1
            except Exception as e:
                logger.warning(f"Match batch {i//batch_size+1} failed: {e}")
            
            _jobs[job_id]['progress'] = min(i + batch_size, len(to_match))
            _jobs[job_id]['matched'] = matched_count
            
            if i + batch_size < len(to_match):
                time.sleep(0.3)
        
        _jobs[job_id]['status'] = 'done'
        _jobs[job_id]['matched'] = matched_count
        _jobs[job_id]['total'] = len(to_match)
    
    background_tasks.add_task(run)
    return {'job_id': job_id, 'total': len(to_match)}
```

### Helper function `_get_api_config_from_env` and `_call_ai_openai`

Add these helpers (used by both `/enrich` and `/match`):

```python
def _get_api_config_from_env():
    """Returns (endpoint, api_key, provider)"""
    claudible_key = os.environ.get('CLAUDIBLE_API_KEY', '').strip()
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if claudible_key:
        return 'https://claudible.io/v1/chat/completions', claudible_key, 'claudible'
    elif anthropic_key:
        return 'https://api.anthropic.com/v1/messages', anthropic_key, 'anthropic'
    return None, None, None


def _call_ai_openai(prompt: str, model: str, endpoint: str, api_key: str) -> str:
    """Call Claudible (OpenAI-compatible) or Anthropic API."""
    import urllib.request as ureq
    is_claudible = 'claudible' in endpoint
    payload = json.dumps({
        'model': model, 'max_tokens': 3000,
        'messages': [{'role': 'user', 'content': prompt}]
    }).encode()
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'OpenClaw/1.0',
        **(
            {'Authorization': f'Bearer {api_key}'} if is_claudible
            else {'x-api-key': api_key, 'anthropic-version': '2023-06-01'}
        )
    }
    req = ureq.Request(endpoint, data=payload, headers=headers)
    with ureq.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
        return d['choices'][0]['message']['content'] if is_claudible else d['content'][0]['text']
```

**Also update `enrich_session` to use `_call_ai_openai` internally (same logic, deduplicated).**

### Update `GET /export/csv/{session_id}` to include `matched_codes`

Add `matched_codes` to `FIELDS` list in the export endpoint:

```python
FIELDS = [
    'reg_code', 'tax_type', 'doc_ref', 'chapter',
    'article_no', 'article_title', 'clause_no', 'letter', 'level',
    'topics', 'taxonomy_codes', 'matched_codes',   # ← add matched_codes
    'keywords', 'importance', 'cross_refs',
    'paragraph_text', 'notes',
]
```

---

## Frontend Changes

### New `MatchPanel` component

Add between `EnrichPanel` and `ResultsTable`:

```jsx
function MatchPanel({ sessionId, onMatched }) {
  const { loading, error, call } = useApi()
  const [file, setFile] = useState(null)
  const [listLoaded, setListLoaded] = useState(null)   // { loaded: N, preview: {...} }
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [model, setModel] = useState('claude-haiku-4-5')

  // Upload match list
  const handleUpload = async () => {
    if (!file) return
    const result = await call(async () => {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('session_id', sessionId)
      const res = await fetch('/match-list', { method: 'POST', body: fd })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || 'Upload failed') }
      return res.json()
    })
    if (result) setListLoaded(result)
  }

  // Run match (background job)
  const handleMatch = async () => {
    const result = await call(async () => {
      const res = await fetch('/match', {
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

  // Poll job status
  const pollJob = async (jid) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/jobs/${jid}`)
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
        <input type="file" accept=".csv,.json" onChange={e => setFile(e.target.files[0])}
          className="text-xs text-gray-600 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:text-xs file:bg-purple-100 file:text-purple-700" />
        <button onClick={handleUpload} disabled={!file || loading}
          className="px-3 py-1.5 bg-purple-600 text-white text-xs rounded hover:bg-purple-700 disabled:opacity-50">
          {loading ? 'Loading...' : '⬆ Load List'}
        </button>
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
            <option value="claude-haiku-4-5">Haiku (fast)</option>
            <option value="claude-sonnet-4-5">Sonnet (accurate)</option>
          </select>
          <button onClick={handleMatch} disabled={!!jobId && jobStatus?.status === 'running'}
            className="px-3 py-1.5 bg-purple-700 text-white text-xs rounded hover:bg-purple-800 disabled:opacity-50">
            {jobStatus?.status === 'running' ? 'Matching...' : '▶ Run Match'}
          </button>

          {/* Progress bar */}
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
```

### Add `MatchPanel` to `App`

```jsx
{session && (
  <>
    <EnrichPanel sessionId={session.session_id} onEnriched={handleEnriched} />
    <MatchPanel sessionId={session.session_id} onMatched={handleEnriched} />
    <ResultsTable session={session} onItemUpdate={handleItemUpdate} />
  </>
)}
```

### Add `matched_codes` column to `ResultsTable`

In the table header, add after Taxonomy:
```jsx
<th className="px-3 py-2 text-left w-28">Matched</th>
```

In the table row, add:
```jsx
<td className="px-3 py-2">
  {(item.matched_codes || '').split(',').filter(Boolean).map(c => (
    <span key={c} className="inline-block bg-purple-100 text-purple-800 text-xs px-1 rounded mr-1 mb-0.5">{c}</span>
  ))}
</td>
```

### Add `matched_codes` to `ItemModal` (editable)

In the edit modal, add after Taxonomy Codes field:
```jsx
<div>
  <label className="block text-xs font-medium text-gray-500 mb-1">Matched Codes (comma-separated)</label>
  <input value={form.matched_codes || ''} onChange={e => handleChange('matched_codes', e.target.value)}
    className="w-full border rounded px-3 py-1.5 text-sm font-mono"
    placeholder="e.g. A1a,B2b (from uploaded match list)" />
</div>
```

---

## SUMMARY — Files to Create/Modify

| Action | File | Change |
|--------|------|--------|
| MODIFY | `backend/main.py` | Add `POST /match-list`, `POST /match`; add `_get_api_config_from_env` + `_call_ai_openai` helpers; add `matched_codes` to CSV export; update `/enrich` to use shared `_call_ai_openai` |
| MODIFY | `frontend/src/App.jsx` | Add `MatchPanel` component; add to App render; add `matched_codes` column to table + modal |

---

## NOTES FOR CLAUDE CODE

1. **`/match` runs as background job** — returns `job_id` immediately, frontend polls `/jobs/{id}`
2. **Match list stored in `_sessions[session_id]['match_list']`** — dict of `{code: description}`
3. **`matched_codes` field** — comma-separated string (same pattern as `taxonomy_codes`)
4. **CSV upload**: handle UTF-8 BOM (`utf-8-sig`) for Excel-exported files
5. **Progress bar**: update `_jobs[job_id]['progress']` every batch — frontend polls every 1.5s
6. **Deduplicate AI call logic**: both `/enrich` and `/match` should use the shared `_call_ai_openai` helper — remove duplicate code
7. **Model names**: `claude-haiku-4-5` and `claude-sonnet-4-5` — these are Claudible model IDs
8. **Do NOT add new npm dependencies**
9. After done: commit + push
