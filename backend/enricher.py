"""
AI Enrichment for parsed regulation items.
Adds: topics, taxonomy_codes, keywords, importance, cross_refs.

Model priority:
  1. Claudible API (free, internal proxy) — env: CLAUDIBLE_API_KEY
  2. Anthropic API (paid fallback)        — env: ANTHROPIC_API_KEY
"""
import json
import re
import time
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ── Default VN Tax Taxonomy ─────────────────────────────────────────────────────
DEFAULT_TAXONOMY = {
    "CIT": {
        "CIT-01": "Taxpayers & taxable entities",
        "CIT-02": "Permanent establishment (PE)",
        "CIT-03": "Taxable income — general",
        "CIT-04": "Taxable income — capital transfer",
        "CIT-05": "Taxable income — real estate transfer",
        "CIT-06": "Taxable income — overseas income",
        "CIT-07": "CIT-exempt income",
        "CIT-08": "Deductible expenses — general conditions",
        "CIT-09": "Deductible expenses — specific categories",
        "CIT-10": "Non-deductible expenses",
        "CIT-11": "R&D expenses & additional deductions",
        "CIT-12": "Depreciation & amortization",
        "CIT-13": "Loss carry-forward",
        "CIT-14": "Standard CIT rate (20%)",
        "CIT-15": "Preferential CIT rates",
        "CIT-16": "CIT calculation method",
        "CIT-17": "Revenue recognition",
        "CIT-18": "CIT incentives — eligibility",
        "CIT-19": "CIT incentives — preferential rates",
        "CIT-20": "CIT incentives — tax exemption & reduction",
        "CIT-21": "CIT incentives — conditions & restrictions",
        "CIT-22": "Science & technology fund",
        "CIT-23": "Foreign contractor tax (CIT component)",
        "CIT-24": "Transfer pricing — related parties",
        "CIT-25": "Double tax treaty interaction",
        "CIT-26": "Tax declaration & payment",
        "CIT-27": "Transition provisions",
    },
    "VAT": {
        "VAT-01": "Taxable objects & scope",
        "VAT-02": "Non-taxable (VAT-exempt) goods & services",
        "VAT-03": "VAT rates — 0%",
        "VAT-04": "VAT rates — 5%",
        "VAT-05": "VAT rates — 10%",
        "VAT-06": "Taxable price — general",
        "VAT-07": "Taxable price — special cases",
        "VAT-08": "Input VAT deduction conditions",
        "VAT-09": "Input VAT deduction — specific cases",
        "VAT-10": "VAT refund",
        "VAT-11": "Place of supply — services",
        "VAT-12": "Time of supply",
        "VAT-13": "Invoicing obligations",
        "VAT-14": "Registration & declaration",
        "VAT-15": "E-commerce & digital services",
    },
    "PIT": {
        "PIT-01": "Tax residents vs non-residents",
        "PIT-02": "Taxable income from employment",
        "PIT-03": "PIT-exempt income",
        "PIT-04": "Taxable income — business income",
        "PIT-05": "Taxable income — investment income",
        "PIT-06": "Taxable income — capital transfer",
        "PIT-07": "Taxable income — real estate transfer",
        "PIT-08": "Deductions — personal relief",
        "PIT-09": "Deductions — dependent relief",
        "PIT-10": "Deductions — insurance & pension",
        "PIT-11": "Deductions — charitable donations",
        "PIT-12": "PIT rates — progressive schedule",
        "PIT-13": "PIT rates — flat rates (non-residents)",
        "PIT-14": "Finalization & annual declaration",
        "PIT-15": "Withholding obligations (employer)",
        "PIT-16": "Expatriate & treaty provisions",
    },
    "FCT": {
        "FCT-01": "FCT scope & taxable entities",
        "FCT-02": "FCT-exempt activities",
        "FCT-03": "FCT — deemed revenue method",
        "FCT-04": "FCT — separate accounting method",
        "FCT-05": "FCT — hybrid method",
        "FCT-06": "FCT rates — by business type",
        "FCT-07": "FCT withholding obligations",
        "FCT-08": "FCT & VAT interaction",
        "FCT-09": "E-commerce & digital FCT",
        "FCT-10": "Treaty override of FCT",
    },
    "TP": {
        "TP-01": "Related party definition & controlled transactions",
        "TP-02": "Arm's length principle",
        "TP-03": "TP methods — CUP",
        "TP-04": "TP methods — cost plus / resale",
        "TP-05": "TP methods — TNMM / profit split",
        "TP-06": "Deductibility cap — related party loans (30% EBITDA)",
        "TP-07": "TP documentation requirements",
        "TP-08": "Country-by-country reporting",
        "TP-09": "Advance pricing agreements (APA)",
        "TP-10": "Pillar Two — global minimum tax (15%)",
    },
    "TaxAdmin": {
        "ADM-01": "Tax registration",
        "ADM-02": "Tax declaration obligations",
        "ADM-03": "Tax payment deadlines",
        "ADM-04": "Tax refund procedures",
        "ADM-05": "Tax audit & inspection",
        "ADM-06": "Tax penalties & late payment interest",
        "ADM-07": "Tax dispute resolution & appeal",
        "ADM-08": "Statute of limitations",
        "ADM-09": "E-filing & digital tax",
        "ADM-10": "Tax agent obligations",
    },
}


def _get_api_config():
    """
    Returns (endpoint, api_key) — Claudible first, Anthropic fallback.
    Claudible: free internal proxy, same API format as Anthropic.
    """
    claudible_key = os.environ.get('CLAUDIBLE_API_KEY', '').strip()
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()

    if claudible_key:
        return 'https://api.claudible.com/v1/messages', claudible_key
    elif anthropic_key:
        logger.info("Claudible key not set — falling back to Anthropic API (paid)")
        return 'https://api.anthropic.com/v1/messages', anthropic_key
    else:
        return None, None


def enrich_items_batch(
    items: List[Dict],
    taxonomy: Optional[Dict] = None,
    model: str = 'claude-haiku-4-5',
    batch_size: int = 15,
    api_key: Optional[str] = None,   # kept for backward compat, ignored if env vars set
) -> List[Dict]:
    """
    AI-enrich parsed items with taxonomy codes, topics, keywords.
    Uses Claudible API (free) by default via CLAUDIBLE_API_KEY env var.
    """
    endpoint, key = _get_api_config()

    # Allow explicit override (e.g. from tests)
    if api_key and not key:
        endpoint = 'https://api.claudible.com/v1/messages'
        key = api_key

    if not key:
        logger.warning("No API key found (CLAUDIBLE_API_KEY or ANTHROPIC_API_KEY) — skipping enrichment")
        return items

    provider = "Claudible" if "claudible" in endpoint else "Anthropic"
    logger.info(f"AI enrichment: {provider} / {model} / {len(items)} items / batch={batch_size}")

    enriched = list(items)

    for i in range(0, len(enriched), batch_size):
        batch = enriched[i:i + batch_size]
        tax_type = batch[0].get('tax_type', 'CIT')

        # Build taxonomy context
        if taxonomy:
            tax_codes = taxonomy
        else:
            tax_codes = {}
            for tt in tax_type.split('/'):
                tax_codes.update(DEFAULT_TAXONOMY.get(tt.strip(), {}))

        taxonomy_list = '\n'.join(f'- [{k}] {v}' for k, v in list(tax_codes.items())[:40])

        items_text = '\n\n'.join(
            f'[{item["reg_code"]}]\n{item["paragraph_text"][:400]}'
            for item in batch
        )

        prompt = f"""You are a senior Vietnamese tax consultant with 30 years experience.
Analyze these parsed regulation paragraphs and classify each one.

TAXONOMY ({tax_type}):
{taxonomy_list}

ITEMS TO CLASSIFY:
{items_text}

Return ONLY valid JSON (no markdown), mapping reg_code to classification:
{{
  "CIT-Decree320-2025-Art9.1.a": {{
    "taxonomy_codes": ["CIT-08", "CIT-09"],
    "topics": "Deductible expenses — general conditions for R&D",
    "keywords": "deductible expenses, R&D, conditions, invoices",
    "importance": "high",
    "cross_refs": "Article 10, Circular 78/2014"
  }}
}}

Rules:
- taxonomy_codes: 1-3 codes from the taxonomy list that BEST match
- topics: concise English phrase (max 80 chars)
- keywords: 4-8 comma-separated keywords
- importance: "high" (key rule), "medium" (standard provision), "low" (procedural/admin)
- cross_refs: other articles/circulars referenced in the text (empty string if none)
- Never leave taxonomy_codes empty — use closest match
"""

        try:
            response_text = _call_ai(prompt, model, endpoint, key)
            json_match = re.search(r'\{[\s\S]+\}', response_text)
            if json_match:
                batch_result = json.loads(json_match.group())
                for item in batch:
                    code = item['reg_code']
                    if code in batch_result:
                        r = batch_result[code]
                        item['taxonomy_codes'] = ','.join(r.get('taxonomy_codes', []))
                        item['topics'] = r.get('topics', '')
                        item['keywords'] = r.get('keywords', '')
                        item['importance'] = r.get('importance', 'medium')
                        item['cross_refs'] = r.get('cross_refs', '')
                logger.info(f"Batch {i//batch_size + 1}/{(len(enriched)-1)//batch_size + 1} done")
        except Exception as e:
            logger.warning(f"Enrichment batch {i//batch_size + 1} failed: {e}")

        if i + batch_size < len(enriched):
            time.sleep(0.3)

    return enriched


def _call_ai(prompt: str, model: str, endpoint: str, api_key: str) -> str:
    """Call Claudible or Anthropic API."""
    import urllib.request

    payload = json.dumps({
        'model': model,
        'max_tokens': 3000,
        'messages': [{'role': 'user', 'content': prompt}]
    }).encode()

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        }
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        d = json.loads(resp.read())
        return d['content'][0]['text']
