# BRIEF: Port Rule-Based Parser from taxparse → examsgen
## Repo: phanvuhoang/examsgen

---

## Context

**taxparse** has a fast, deterministic rule-based parser that splits regulation documents into
sub-clause level items (Art9.1.a, Art9.1.b, etc.) without any AI calls.
This is much faster and more granular than examsgen's current AI-based chunked parser.

**Goal:** Add this rule-based parser as a "Fast Parse" option in examsgen's Knowledge Base,
alongside the existing AI parse. User can choose which to use.

**Key differences to handle:**
- examsgen uses **PostgreSQL** (not in-memory like taxparse)
- examsgen already has `rule_parser.py` in `backend/utils/` (from previous BRIEF)
- examsgen has **syllabus context** — after rule-based parse, run AI syllabus-matching in background
- reg_code format stays: `{TAX_TYPE}-{DocSlug}-Art{N}.{clause}.{letter}`

---

## What to Port (from taxparse `backend/main.py`)

The core logic to port:

### 1. `_call_ai_openai` helper

```python
def _call_ai_openai(prompt: str, model: str, endpoint: str, api_key: str) -> str:
    """
    Call Claudible (OpenAI-compatible) or Anthropic API.
    Claudible needs: Bearer auth + User-Agent: OpenClaw/1.0
    Anthropic needs: x-api-key auth
    """
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


def _get_api_config_from_env():
    """Returns (endpoint, api_key, provider) — Claudible first, Anthropic fallback."""
    import os
    claudible_key = os.environ.get('CLAUDIBLE_API_KEY', '').strip()
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if claudible_key:
        return 'https://claudible.io/v1/chat/completions', claudible_key, 'claudible'
    elif anthropic_key:
        return 'https://api.anthropic.com/v1/messages', anthropic_key, 'anthropic'
    return None, None, None
```

Add these two helpers to `backend/routes/kb.py` (near the top, after imports).

### 2. Fast parse endpoint

Replace (or add alongside) `POST /api/kb/regulations/parse-doc` with a version that:
1. Calls `rule_parser.extract_text_from_file` + `rule_parser.parse_regulation_text`  
2. Inserts all items to DB in one transaction (fast, no AI)
3. Returns job_id for a **background AI syllabus-tagging job** (optional step)

---

## Backend Changes — `backend/routes/kb.py`

### Step 1: Add helpers at top of file

After existing imports, add `_call_ai_openai` and `_get_api_config_from_env` (code above).

### Step 2: Add `_fast_parse_jobs` store near `_parse_jobs`

```python
_fast_parse_jobs: dict = {}
```

### Step 3: Update `POST /api/kb/regulations/parse-doc`

The current endpoint already calls `rule_parser` — but it's **synchronous** and doesn't return
a job_id for progress tracking. Replace it with a background-job version:

```python
@router.post("/regulations/parse-doc")
def parse_regulation_doc(data: dict, background_tasks: BackgroundTasks):
    """
    Rule-based fast parse — no AI calls, sub-clause granularity.
    Returns job_id immediately; poll /api/kb/parse-jobs/{job_id} for progress.
    """
    import os
    from backend.config import DATA_DIR
    from backend.utils.rule_parser import extract_text_from_file as rule_extract, parse_regulation_text

    session_id = data['session_id']
    tax_type   = data['tax_type']
    file_path  = data['file_path']
    doc_ref    = data.get('doc_ref', '')
    doc_slug   = data.get('doc_slug', '')

    if not doc_slug:
        base = os.path.splitext(os.path.basename(file_path))[0]
        doc_slug = re.sub(r'[^A-Za-z0-9]', '', base.replace(' ', '').replace('_', ''))[:20]

    source_file = os.path.basename(file_path)
    full_path   = os.path.join(DATA_DIR, file_path) if not file_path.startswith('/') else file_path

    if not os.path.exists(full_path):
        raise HTTPException(404, f'File not found: {file_path}')

    import uuid as _uuid
    job_id = str(_uuid.uuid4())[:8]
    _fast_parse_jobs[job_id] = {
        'status': 'running', 'parsed': 0, 'total': 0, 'cleared': 0, 'error': None
    }

    def run():
        try:
            # 1. Extract text
            text  = rule_extract(full_path)
            items = parse_regulation_text(text, doc_slug, tax_type, doc_ref)
            _fast_parse_jobs[job_id]['total'] = len(items)

            # 2. Clear existing rows for this file (idempotent re-parse)
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute(
                    'DELETE FROM kb_regulation_parsed WHERE session_id = %s AND source_file = %s',
                    (session_id, source_file)
                )
                _fast_parse_jobs[job_id]['cleared'] = cur.rowcount

            # 3. Insert all items
            inserted = 0
            with get_db() as conn:
                cur = conn.cursor()
                for item in items:
                    cur.execute("""
                        INSERT INTO kb_regulation_parsed
                          (session_id, tax_type, reg_code, doc_ref, article_no, paragraph_no,
                           paragraph_text, syllabus_codes, tags, source_file, is_active)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, TRUE)
                        ON CONFLICT (session_id, reg_code) DO UPDATE SET
                          paragraph_text = EXCLUDED.paragraph_text,
                          doc_ref        = EXCLUDED.doc_ref,
                          article_no     = EXCLUDED.article_no,
                          is_active      = TRUE
                    """, (
                        session_id, item['tax_type'], item['reg_code'], item['doc_ref'],
                        item['article_no'],
                        int(item['clause_no']) if item.get('clause_no') and str(item['clause_no']).isdigit() else 0,
                        item['paragraph_text'],
                        [],          # syllabus_codes: empty until AI-tagged
                        item['title'][:200] if item.get('title') else '',
                        source_file,
                    ))
                    inserted += 1
                    _fast_parse_jobs[job_id]['parsed'] = inserted

            _fast_parse_jobs[job_id]['status'] = 'done'
            _fast_parse_jobs[job_id]['parsed']  = inserted

        except Exception as e:
            import traceback
            _fast_parse_jobs[job_id]['status'] = 'failed'
            _fast_parse_jobs[job_id]['error']  = str(e)
            print(traceback.format_exc())

    background_tasks.add_task(run)
    return {'job_id': job_id, 'source': 'rule-based', 'file': source_file}
```

### Step 4: Add `GET /api/kb/parse-jobs/{job_id}`

```python
@router.get("/parse-jobs/{job_id}")
def get_parse_job(job_id: str):
    """Poll parse job status."""
    job = _fast_parse_jobs.get(job_id)
    if not job:
        # Also check legacy _parse_jobs
        job = _parse_jobs.get(job_id)
    if not job:
        raise HTTPException(404, f'Job {job_id} not found')
    return job
```

### Step 5: Fix `GET /api/kb/regulation-parsed` — pagination + sort

Current endpoint has `limit` hardcoded to 100 or 500. Fix to return all (up to 2000) and sort numerically:

```python
@router.get("/regulation-parsed")
def list_regulation_parsed(
    session_id: Optional[int] = None,
    tax_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 2000,    # ← was 100 or 500, now 2000
    offset: int = 0,
):
    with get_db() as conn:
        cur = conn.cursor()

        where = ['TRUE']
        params = []
        if session_id is not None:
            where.append('r.session_id = %s'); params.append(session_id)
        if tax_type:
            where.append('r.tax_type = %s'); params.append(tax_type)
        if search:
            where.append('(r.reg_code ILIKE %s OR r.paragraph_text ILIKE %s OR r.tags ILIKE %s)')
            params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])

        where_clause = ' AND '.join(where)

        cur.execute(f"""
            SELECT r.id, r.session_id, r.tax_type, r.reg_code, r.doc_ref,
                   r.article_no, r.paragraph_no, r.paragraph_text,
                   r.syllabus_codes, r.tags, r.source_file, r.is_active,
                   r.created_at
            FROM kb_regulation_parsed r
            WHERE {where_clause}
            ORDER BY
              -- Numeric sort: Art1 < Art2 < Art10 (not Art1 < Art10 < Art2)
              CAST(NULLIF(regexp_replace(r.reg_code, '.*Art(\\d+).*', '\\1'), r.reg_code) AS INTEGER) NULLS LAST,
              CAST(NULLIF(regexp_replace(r.reg_code, '.*\\.([0-9]+)(\\.[a-z])?$', '\\1'), r.reg_code) AS INTEGER) NULLS LAST,
              r.reg_code
            LIMIT %s OFFSET %s
        """, params + [limit, offset])

        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

        # Also get total count
        cur.execute(f'SELECT COUNT(*) FROM kb_regulation_parsed r WHERE {where_clause}', params)
        total = cur.fetchone()[0]

    return {
        'items': [dict(zip(cols, r)) for r in rows],
        'total': total,
        'limit': limit,
        'offset': offset,
    }
```

### Step 6: Fix bulk delete for regulation-parsed

The existing `DELETE /api/kb/regulation-parsed/bulk` may not be working (from earlier bug report).
Ensure it exists and works:

```python
@router.delete("/regulation-parsed/bulk")
def bulk_delete_regulation_parsed(data: dict):
    """Delete multiple parsed regulation items by id list."""
    ids = data.get('ids', [])
    if not ids:
        return {'deleted': 0}
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            'DELETE FROM kb_regulation_parsed WHERE id = ANY(%s) RETURNING id',
            (ids,)
        )
        deleted = len(cur.fetchall())
    return {'deleted': deleted}
```

### Step 7: Add syllabus AI-tagging endpoint (port from taxparse BRIEF)

After fast parse, user can click "🏷 Tag Syllabus" to AI-match items to syllabus codes.
This is the same as `POST /api/kb/regulations/tag-syllabus` from BRIEF-bulk-delete-smart-reparse.md —
**implement it if not already done**.

```python
@router.post("/regulations/tag-syllabus")
def tag_syllabus_codes(data: dict, background_tasks: BackgroundTasks):
    """
    Use AI to suggest syllabus_codes for untagged regulation items.
    Body: { session_id, tax_type?, force? }
    Returns job_id for polling via /api/kb/parse-jobs/{job_id}
    """
    session_id = data['session_id']
    tax_type   = data.get('tax_type')
    force      = data.get('force', False)
    model      = data.get('model', 'claude-haiku-4.5')

    # Load syllabus for context
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(syllabus_code, section_code),
                   COALESCE(topic, section_title),
                   COALESCE(detailed_syllabus, content)
            FROM kb_syllabus
            WHERE session_id = %s
              AND (%s IS NULL OR COALESCE(tax_type, sac_thue) = %s)
              AND COALESCE(syllabus_code, section_code) IS NOT NULL
            ORDER BY COALESCE(syllabus_code, section_code)
        """, (session_id, tax_type, tax_type))
        syllabus_rows = cur.fetchall()

        if not syllabus_rows:
            raise HTTPException(400, 'No syllabus loaded for this session')

        # Load untagged items
        filter_tagged = '' if force else "AND (syllabus_codes IS NULL OR syllabus_codes = '{}')"
        cur.execute(f"""
            SELECT id, reg_code, paragraph_text
            FROM kb_regulation_parsed
            WHERE session_id = %s
              AND (%s IS NULL OR tax_type = %s)
              {filter_tagged}
            ORDER BY id
        """, (session_id, tax_type, tax_type))
        items = cur.fetchall()

    if not items:
        return {'job_id': None, 'message': 'No untagged items', 'tagged': 0}

    import uuid as _uuid
    job_id = str(_uuid.uuid4())[:8]
    _fast_parse_jobs[job_id] = {'status': 'running', 'parsed': 0, 'total': len(items), 'tagged': 0}

    syllabus_list = '\n'.join(
        f'- [{r[0]}] {r[1]}: {(r[2] or "")[:80]}' for r in syllabus_rows[:80]
    )

    def run():
        endpoint, key, _ = _get_api_config_from_env()
        if not key:
            _fast_parse_jobs[job_id]['status'] = 'failed'
            _fast_parse_jobs[job_id]['error'] = 'No API key'
            return

        tagged = 0
        batch_size = 20
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            items_text = '\n\n'.join(
                f'[{item[1]}]\n{(item[2] or "")[:300]}' for item in batch
            )
            prompt = (
                'Match each regulation item to relevant syllabus codes.\n\n'
                'SYLLABUS:\n' + syllabus_list + '\n\n'
                'ITEMS:\n' + items_text + '\n\n'
                'Return ONLY JSON (no markdown): {"reg_code": ["A1a", "B2b"]}\n'
                'Rules: 1-3 codes per item, only codes from list above, [] if no match'
            )
            try:
                response = _call_ai_openai(prompt, model, endpoint, key)
                brace_s = response.find('{')
                brace_e = response.rfind('}')
                if brace_s != -1 and brace_e != -1:
                    result = json.loads(response[brace_s:brace_e+1])
                    with get_db() as conn:
                        cur = conn.cursor()
                        for item in batch:
                            codes = result.get(item[1], [])
                            if codes or force:
                                cur.execute(
                                    'UPDATE kb_regulation_parsed SET syllabus_codes = %s WHERE id = %s',
                                    (codes, item[0])
                                )
                                if codes: tagged += 1
            except Exception as e:
                print(f'Tag batch {i//batch_size+1} failed: {e}')

            _fast_parse_jobs[job_id]['parsed'] = min(i + batch_size, len(items))
            _fast_parse_jobs[job_id]['tagged'] = tagged

        _fast_parse_jobs[job_id]['status'] = 'done'
        _fast_parse_jobs[job_id]['tagged'] = tagged

    background_tasks.add_task(run)
    return {'job_id': job_id, 'total': len(items)}
```

---

## Frontend Changes — Knowledge Base Regulations Tab

The KB frontend needs UI updates to match the new fast-parse flow.

### 1. Parse button — show progress bar while parsing

Currently parse button shows "Parsing..." but there's no progress feedback.
Add progress polling after `parse-doc` returns a `job_id`:

```jsx
const handleParseDoc = async (fileItem) => {
  setParsing(true)
  setParseJob(null)
  try {
    const res = await api.parseRegDoc({
      session_id: sessionId, tax_type: activeTaxType,
      file_path: fileItem.path, doc_ref: fileItem.doc_ref || '',
      doc_slug: fileItem.slug || '',
    })
    if (res.job_id) {
      setParseJob({ id: res.job_id, status: 'running', parsed: 0, total: 0 })
      pollParseJob(res.job_id)
    }
  } catch (e) {
    setParsing(false)
    toast.error('Parse failed: ' + e.message)
  }
}

const pollParseJob = (jid) => {
  const iv = setInterval(async () => {
    try {
      const d = await api.getParseJob(jid)
      setParseJob(d)
      if (d.status === 'done' || d.status === 'failed') {
        clearInterval(iv)
        setParsing(false)
        if (d.status === 'done') {
          toast.success(`Parsed ${d.parsed} items`)
          fetchRegulationItems()
        } else {
          toast.error('Parse failed: ' + d.error)
        }
      }
    } catch { clearInterval(iv); setParsing(false) }
  }, 1000)
}
```

Show progress bar while parseJob is active:

```jsx
{parseJob?.status === 'running' && (
  <div className="mt-2 space-y-1">
    <div className="flex justify-between text-xs text-blue-600">
      <span>Fast parsing… {parseJob.parsed || 0} items</span>
      {parseJob.total > 0 && <span>{Math.round(parseJob.parsed/parseJob.total*100)}%</span>}
    </div>
    <div className="w-full bg-blue-100 rounded-full h-1.5">
      <div className="bg-blue-500 h-1.5 rounded-full transition-all"
        style={{ width: parseJob.total > 0 ? `${Math.round(parseJob.parsed/parseJob.total*100)}%` : '5%' }} />
    </div>
  </div>
)}
{parseJob?.status === 'done' && (
  <p className="text-xs text-green-600 mt-1">✓ {parseJob.parsed} items parsed</p>
)}
```

### 2. Regulation items table — fix pagination display

The table currently shows max 100 items even though backend returns up to 2000.
Ensure the fetch call passes `limit=2000`:

```js
// In fetchRegulationItems:
const params = new URLSearchParams({ session_id: sessionId, limit: 2000, offset: 0 })
if (activeTaxType) params.append('tax_type', activeTaxType)
const data = await api.getRegulationParsed(params.toString())
setRegulationItems(data.items || [])
setRegulationTotal(data.total || 0)
```

Add "Showing X of Y" counter above table:

```jsx
<div className="text-xs text-gray-500 mb-2">
  Showing {regulationItems.length} of {regulationTotal} items
  {regulationTotal > regulationItems.length && (
    <span className="text-amber-600 ml-2">
      (showing first {regulationItems.length} — use search to filter)
    </span>
  )}
</div>
```

### 3. Tag Syllabus button — add to Regulations tab toolbar

```jsx
{regulationItems.length > 0 && (
  <button onClick={handleTagSyllabus}
    disabled={tagLoading}
    className="px-3 py-1.5 text-xs bg-purple-600 hover:bg-purple-700 text-white rounded disabled:opacity-50">
    {tagLoading ? 'Tagging…' : `🏷 Tag Syllabus`}
  </button>
)}
```

```js
const handleTagSyllabus = async () => {
  setTagLoading(true)
  try {
    const res = await api.tagSyllabusItems({ session_id: sessionId, tax_type: activeTaxType })
    if (res.job_id) {
      pollTagJob(res.job_id)
    } else {
      setTagLoading(false)
      toast.info(res.message || 'Nothing to tag')
    }
  } catch (e) {
    setTagLoading(false)
    toast.error('Tag failed: ' + e.message)
  }
}

const pollTagJob = (jid) => {
  const iv = setInterval(async () => {
    try {
      const d = await api.getParseJob(jid)
      if (d.status === 'done' || d.status === 'failed') {
        clearInterval(iv)
        setTagLoading(false)
        if (d.status === 'done') {
          toast.success(`Tagged ${d.tagged}/${d.total} items`)
          fetchRegulationItems()
        }
      }
    } catch { clearInterval(iv); setTagLoading(false) }
  }, 1500)
}
```

### 4. api.js additions

```js
// Add to api.js:
getParseJob: (jobId) =>
  request(`/api/kb/parse-jobs/${jobId}`),

tagSyllabusItems: (body) =>
  request('/api/kb/regulations/tag-syllabus', { method: 'POST', body }),

getRegulationParsed: (queryString) =>
  request(`/api/kb/regulation-parsed?${queryString}`),
```

---

## SUMMARY — Files to Create/Modify

| Action | File | Change |
|--------|------|--------|
| MODIFY | `backend/routes/kb.py` | Add `_call_ai_openai` + `_get_api_config_from_env` helpers; update `parse-doc` → background job; add `GET /parse-jobs/{id}`; add `POST /regulations/tag-syllabus`; fix `GET /regulation-parsed` pagination+sort; ensure `DELETE /regulation-parsed/bulk` works |
| MODIFY | `frontend/src/pages/KnowledgeBase.jsx` | Parse progress bar; fix pagination (`limit=2000`); "Showing X of Y" counter; "🏷 Tag Syllabus" button |
| MODIFY | `frontend/src/api.js` | Add `getParseJob`, `tagSyllabusItems`, `getRegulationParsed` |

---

## NOTES FOR CLAUDE CODE

1. **Do NOT remove the existing `_run_parse_job` / `parse-file` flow** — it's used elsewhere in the app. Only update `parse-doc` and add new endpoints.
2. **`_call_ai_openai`**: use `User-Agent: OpenClaw/1.0` — Cloudflare blocks Python default UA
3. **Claudible model names**: `claude-haiku-4.5` (fast), `claude-sonnet-4.6` (accurate) — note `.` not `-`
4. **Claudible base URL**: `https://claudible.io/v1/chat/completions` — OpenAI-compatible
5. **JSON extraction**: use `response.find('{')` + `response.rfind('}')` — more reliable than regex
6. **`rule_parser.py`** is already in `backend/utils/` from previous brief — do not recreate it
7. **`BackgroundTasks`**: import from `fastapi` — already imported in main.py but may need adding to kb.py imports
8. **Progress polling interval**: 1000ms for parse, 1500ms for tag-syllabus
9. **Bulk delete**: the existing `DELETE /api/kb/regulation-parsed/bulk` may have a bug where the `ids` from frontend are not being sent correctly — verify the frontend is sending `{ ids: [...] }` in the request body
10. After done: commit + push
