"""
VN Tax Regulation Rule-Based Parser
====================================
Parses .docx tax regulation files into sub-clause level items.

Structure hierarchy:
  Chapter → Article → Clause → Letter/Sub-letter
  
Reg code format:
  {TAX_TYPE}-{DocSlug}-Art{N}           (article level, no clauses)
  {TAX_TYPE}-{DocSlug}-Art{N}.{C}       (clause level, no letters)
  {TAX_TYPE}-{DocSlug}-Art{N}.{C}.{L}   (letter/sub-letter level)

Examples:
  CIT-Decree320-2025-Art9.1.a
  CIT-Decree320-2025-Art9.2.i3
  VAT-Decree181-2025-Art5.2
"""
import re
import os
from typing import List, Dict, Optional

try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

# ── Regex Patterns ─────────────────────────────────────────────────────────────
# Article N. Title  OR  Article N: Title
ART_RE    = re.compile(r'^Article\s+(\d+)[\.:]?\s*(.*)$', re.IGNORECASE)
# Numbered clause: "1. text" or "2. text"
CLAUSE_RE = re.compile(r'^(\d+)\.\s+\S')
# Lettered item: "a) text", "b1) text", "dd) text", "B4) text"
LETTER_RE = re.compile(r'^([a-zA-Z]{1,2}\d*)\)\s+\S')
# Chapter/Section header
CHAPTER_RE = re.compile(r'^(Chapter|Section|Part)\s+[IVXLC\d]+', re.IGNORECASE)


def extract_text_from_file(file_path: str) -> List[str]:
    """
    Extract paragraphs from .docx or .txt file.
    Returns list of non-empty paragraph strings.
    """
    if file_path.endswith('.txt'):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return [ln.strip() for ln in f.read().splitlines() if ln.strip()]

    if not HAS_DOCX:
        raise ImportError("python-docx not installed. Run: pip install python-docx")

    if file_path.endswith('.docx'):
        doc = DocxDocument(file_path)
        return [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    # Fallback: antiword for .doc
    import subprocess
    try:
        result = subprocess.run(['antiword', file_path], capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    except Exception:
        pass

    raise ValueError(f"Cannot extract text from {file_path}: unsupported format")


def parse_regulation(
    file_path: str,
    doc_ref: str,
    doc_slug: str,
    tax_type: str,
) -> List[Dict]:
    """
    Parse a VN tax regulation file into sub-clause level items.

    Args:
        file_path: Path to .docx/.txt file
        doc_ref:   Human-readable reference, e.g. "Decree 320/2025/ND-CP"
        doc_slug:  URL-safe slug, e.g. "Decree320-2025"
        tax_type:  Tax category, e.g. "CIT", "VAT", "PIT"

    Returns:
        List of dicts with keys:
          reg_code, doc_ref, tax_type, chapter, article_no, article_title,
          clause_no, letter, level, paragraph_text
    """
    paragraphs = extract_text_from_file(file_path)
    return parse_paragraphs(paragraphs, doc_ref, doc_slug, tax_type)


def parse_paragraphs(
    paragraphs: List[str],
    doc_ref: str,
    doc_slug: str,
    tax_type: str,
) -> List[Dict]:
    """
    Core parser — accepts list of paragraph strings.
    Useful for testing or when text is already extracted.
    """
    items = []

    # State machine
    cur_chapter       : str = ''
    cur_art_no        : Optional[str] = None
    cur_art_title     : str = ''
    cur_clause_no     : Optional[str] = None
    cur_clause_lines  : List[str] = []
    cur_letter        : Optional[str] = None
    cur_letter_lines  : List[str] = []

    def _make_item(reg_code, level, text, clause_no=None, letter=None):
        return {
            'reg_code':      reg_code,
            'doc_ref':       doc_ref,
            'tax_type':      tax_type,
            'chapter':       cur_chapter,
            'article_no':    f'Article {cur_art_no}' if cur_art_no else '',
            'article_title': cur_art_title,
            'clause_no':     clause_no,
            'letter':        letter,
            'level':         level,
            'paragraph_text': text,
        }

    def flush_letter():
        if cur_letter is None:
            return
        text = '\n'.join(cur_letter_lines).strip()
        if not text:
            return
        # Prepend clause intro (first line of clause) for context
        intro = cur_clause_lines[0] if cur_clause_lines else ''
        full_text = (intro + '\n' + text) if intro and intro not in text else text
        code = f'{tax_type}-{doc_slug}-Art{cur_art_no}.{cur_clause_no}.{cur_letter}'
        items.append(_make_item(code, 'letter', full_text, cur_clause_no, cur_letter))

    def flush_clause():
        nonlocal cur_letter, cur_letter_lines
        flush_letter()
        cur_letter = None
        cur_letter_lines = []

        if cur_clause_no is None:
            return

        # Only emit clause-level item if NO letters were emitted for this clause
        clause_art = f'Article {cur_art_no}'
        had_letters = any(
            i['article_no'] == clause_art
            and i['clause_no'] == cur_clause_no
            and i['level'] == 'letter'
            for i in items[-50:]
        )
        if not had_letters and cur_clause_lines:
            text = '\n'.join(cur_clause_lines).strip()
            code = f'{tax_type}-{doc_slug}-Art{cur_art_no}.{cur_clause_no}'
            items.append(_make_item(code, 'clause', text, cur_clause_no))

    def flush_article():
        nonlocal cur_clause_no, cur_clause_lines
        flush_clause()
        cur_clause_no = None
        cur_clause_lines = []

        # If article had NO clauses at all, emit article-level item
        if cur_art_no is None:
            return
        clause_art = f'Article {cur_art_no}'
        had_items = any(i['article_no'] == clause_art for i in items[-100:])
        if not had_items:
            # Collect all prose under this article
            pass  # handled by the state machine naturally

    for para in paragraphs:
        art_m    = ART_RE.match(para)
        ch_m     = CHAPTER_RE.match(para)
        clause_m = CLAUSE_RE.match(para)
        letter_m = LETTER_RE.match(para)

        if ch_m:
            cur_chapter = para

        elif art_m:
            flush_article()
            cur_art_no    = art_m.group(1)
            cur_art_title = art_m.group(2).strip()
            cur_clause_no = None
            cur_clause_lines = []
            cur_letter = None
            cur_letter_lines = []

        elif clause_m and cur_art_no:
            flush_clause()
            cur_clause_no    = clause_m.group(1)
            cur_clause_lines = [para]
            cur_letter       = None
            cur_letter_lines = []

        elif letter_m and cur_art_no and cur_clause_no:
            flush_letter()
            # Normalize letter: lowercase, keep digits (b1→b1, B4→b4, dd→dd)
            raw_letter = letter_m.group(1)
            cur_letter = raw_letter.lower()
            cur_letter_lines = [para]

        elif cur_letter is not None:
            cur_letter_lines.append(para)

        elif cur_clause_no is not None:
            cur_clause_lines.append(para)

        # else: preamble / transition prose — skip

    flush_article()
    return items


# ── CSV Export ─────────────────────────────────────────────────────────────────
def items_to_csv(items: List[Dict], output_path: str):
    """Export parsed items to CSV (Excel/Google Sheets compatible)."""
    import csv
    FIELDS = [
        'reg_code', 'tax_type', 'doc_ref', 'chapter',
        'article_no', 'article_title', 'clause_no', 'letter',
        'level', 'paragraph_text',
        # Enrichment columns — empty by default, filled by AI enrich step
        'topics', 'taxonomy_codes', 'keywords', 'importance',
        'cross_refs', 'syllabus_codes', 'notes',
    ]
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        for item in items:
            row = dict(item)
            # Fill enrichment columns with empty string
            for col in ['topics', 'taxonomy_codes', 'keywords', 'importance',
                        'cross_refs', 'syllabus_codes', 'notes']:
                row.setdefault(col, '')
            writer.writerow(row)


def items_to_jsonl(items: List[Dict], output_path: str):
    """Export parsed items to JSONL (one JSON per line)."""
    import json
    with open(output_path, 'w', encoding='utf-8') as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import argparse, json

    parser = argparse.ArgumentParser(description='Parse VN tax regulation .docx files')
    parser.add_argument('file', help='Path to .docx or .txt file')
    parser.add_argument('--doc-ref',  required=True, help='e.g. "Decree 320/2025/ND-CP"')
    parser.add_argument('--doc-slug', required=True, help='e.g. "Decree320-2025"')
    parser.add_argument('--tax-type', required=True, help='e.g. CIT, VAT, PIT')
    parser.add_argument('--out', default=None, help='Output file (.csv or .jsonl). Default: print summary.')
    parser.add_argument('--format', choices=['csv', 'jsonl', 'summary'], default='summary')
    args = parser.parse_args()

    items = parse_regulation(args.file, args.doc_ref, args.doc_slug, args.tax_type)
    print(f'Parsed {len(items)} items from {args.file}')

    levels = {}
    for i in items:
        levels[i['level']] = levels.get(i['level'], 0) + 1
    print(f'Levels: {levels}')

    if args.out:
        if args.out.endswith('.csv') or args.format == 'csv':
            items_to_csv(items, args.out)
            print(f'CSV saved: {args.out}')
        else:
            items_to_jsonl(items, args.out)
            print(f'JSONL saved: {args.out}')
    elif args.format == 'summary':
        print('\nSample items (first 5):')
        for item in items[:5]:
            print(f'  {item["reg_code"]:50s} {item["paragraph_text"][:60]}...')
