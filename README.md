# taxparse

**VN Tax Regulation Parser & Classifier**

Parse Vietnamese tax regulation documents (.docx) into sub-clause level items, classify by taxonomy, export to CSV/JSONL for Google Sheets / further processing.

## What it does

1. **Parse** `.docx` regulation files → structured items at Article → Clause → Letter level
2. **Classify** each item with tax-specific taxonomy codes (e.g. `CIT-08: Deductible expenses`)
3. **Export** to CSV (Excel/Google Sheets compatible) or JSONL
4. **Foundation** for downstream apps: examsgen, dbvntax, AI tax advisory

## Reg Code Format

```
CIT-Decree320-2025-Art9.1.a     ← Letter level (most granular)
CIT-Decree320-2025-Art9.2       ← Clause level (no sub-letters)
CIT-Decree320-2025-Art11        ← Article level (no clauses)
```

## Taxonomy

Each tax type has a curated taxonomy of the most important topics practitioners care about:

| Tax | Example codes |
|-----|---------------|
| CIT | CIT-08 (Deductible expenses), CIT-14 (CIT rate 20%), CIT-19 (Incentive rates) |
| VAT | VAT-02 (Exempt goods), VAT-08 (Input VAT deduction), VAT-10 (VAT refund) |
| PIT | PIT-02 (Employment income), PIT-08 (Personal deduction), PIT-12 (Tax rates) |
| FCT | FCT-03 (Deemed revenue), FCT-06 (FCT rates), FCT-09 (E-commerce) |
| TP  | TP-01 (Related parties), TP-06 (30% EBITDA cap), TP-10 (Pillar Two) |

Custom taxonomy can be defined per document via API.

## Source Documents (12 files — GDrive: `Thanh-AI/Exams/Regulations/`)

| File | Tax Type | Items |
|------|----------|-------|
| CIT - Decree 320/2025/ND-CP | CIT | ~464 |
| CIT - Law 67/2025/QH15 | CIT | ~188 |
| CIT-FCT - Circular 20/2026 | CIT/FCT | ~107 |
| FCT - Circular 103/2014 | FCT | ~39 |
| PIT - Combined Circular 02/VBHN | PIT | ~244 |
| TP - Decree 132/2020 | TP | ~173 |
| TP - Decree 20/2025 | TP | ~8 |
| TaxAdmin - VBHN 15/BTC | TaxAdmin | ~610 |
| VAT - Decree 181/2025 | VAT | ~263 |
| VAT Invoice - VBHN 18/BTC | VAT | ~324 |
| VAT - Law 48/2024 | VAT | ~148 |
| VAT-FCT - Circular 69/2025 | VAT/FCT | ~60 |
| **Total** | | **~2,628** |

## Deploy (Coolify)

- **Repo:** `phanvuhoang/taxparse`
- **Build:** Dockerfile (build frontend first, then backend serves static)
- **Port:** 8000
- **Domain:** `taxparse.gpt4vn.com`
- **Env vars:** `ANTHROPIC_API_KEY` or `CLAUDIBLE_API_KEY` (for AI enrichment)
- **Volume:** `/data/taxparse/regulations` → `/app/data/regulations` (mount regulation .docx files)

## Local Development

```bash
# Backend
pip install -r requirements.txt
uvicorn backend.main:app --reload

# Frontend
cd frontend
npm install
npm run dev   # → http://localhost:5173 (proxies to backend :8000)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/parse` | Upload .docx → parse |
| POST | `/enrich` | AI-classify parsed session |
| GET  | `/sessions/{id}` | Browse parsed items (filterable) |
| GET  | `/export/csv/{id}` | Download CSV (UTF-8 BOM, Excel-ready) |
| GET  | `/export/jsonl/{id}` | Download JSONL |
| GET  | `/taxonomy` | List taxonomy codes |
| POST | `/taxonomy` | Save custom taxonomy |
| POST | `/parse-catalog` | Parse all 12 source files (background job) |
| GET  | `/jobs/{id}` | Poll background job status |
| GET  | `/catalog` | List catalog files + availability |

## Architecture

```
taxparse (this repo)
    ↓ exports CSV/JSONL
Google Sheets → human review/editing
    ↓ import
examsgen → question generation (reg_code + paragraph_text → exam questions)
dbvntax  → AI advisory (semantic search + RAG)
```
