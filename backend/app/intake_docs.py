"""Requirement documents attached by the buyer in the RFx builder.

Only what the document prints is mapped. Column roles are recognised from header
text; a table that cannot be identified is reported back instead of guessed, and
no quantity, unit, specification or date is ever inferred.
"""
from __future__ import annotations

import csv
import email
import html as html_entities
import re
from pathlib import Path
from typing import Any

import pdfplumber
from docx import Document
from openpyxl import load_workbook

SUPPORTED = {'.xlsx', '.csv', '.pdf', '.docx', '.txt', '.eml'}
MAX_ITEMS = 100
MAX_TEXT = 24000

SKU_HEADERS = ('sku', 'part number', 'part no', 'item code', 'material code', 'product code', 'code', 'model')
DESCRIPTION_HEADERS = ('description', 'item description', 'requirement', 'specification', 'specifications', 'spec',
                       'particulars', 'material', 'product', 'service', 'item', 'details', 'scope of work')
QUANTITY_HEADERS = ('annual quantity', 'annual qty', 'annual volume', 'quantity', 'qty', 'volume', 'units required',
                    'no of units', 'nos', 'count')
UNIT_HEADERS = ('unit of measure', 'units of measure', 'uom', 'unit', 'packing', 'pack size', 'basis', 'measure')
WEIGHT_HEADERS = ('unit weight', 'weight per unit', 'weight per piece', 'unit weight kg', 'weight kg', 'kg per piece',
                  'kg/piece', 'net weight', 'gross weight', 'weight')
TERM_HEADERS = ('term months', 'contract term', 'rental term', 'lease term', 'subscription term', 'term', 'duration',
                'period months', 'tenure')

FIELD_LABELS = {
    'scope': ('scope', 'purpose', 'objective', 'requirement summary', 'overview', 'background', 'need'),
    'category': ('category', 'commodity', 'spend category', 'procurement category'),
    'specifications': ('specification', 'specifications', 'technical requirement', 'acceptance criteria',
                       'quality requirement', 'standards'),
    'delivery': ('delivery', 'delivery location', 'delivery schedule', 'ship to', 'shipping address', 'destination',
                 'site', 'location', 'lead time'),
    'budget': ('budget', 'estimated value', 'target price', 'target cost', 'indicative budget', 'baseline spend'),
    'pricing': ('currency', 'tax', 'gst', 'freight', 'incoterm', 'incoterms', 'price basis', 'pricing basis'),
    'payment': ('payment terms', 'payment', 'credit period', 'milestone payment'),
    'deadline': ('response deadline', 'submission deadline', 'bid due date', 'due date', 'quote by', 'rfq deadline',
                 'closing date'),
    'compliance': ('compliance', 'certification', 'certifications', 'qualification', 'statutory', 'licence',
                   'license', 'mandatory requirement', 'safety'),
}
# Longest label first so "payment terms" wins over "payment" and "delivery location" over "location".
LABEL_LOOKUP = sorted(((label, field) for field, labels in FIELD_LABELS.items() for label in labels),
                      key=lambda pair: -len(pair[0]))


def _clean(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value)).strip() if value is not None else ''


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r'-?\d[\d,]*(?:\.\d+)?', str(value or ''))
    if not match:
        return None
    try:
        return float(match.group().replace(',', ''))
    except ValueError:
        return None


def _xlsx_rows(path: Path) -> list[list[str]]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    rows: list[list[str]] = []
    for sheet in workbook:
        for row in sheet.values:
            cells = [_clean(x) for x in row]
            if any(cells):
                rows.append(cells)
    workbook.close()
    return rows


def _csv_rows(path: Path) -> list[list[str]]:
    text = path.read_text(encoding='utf-8', errors='replace')
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    return [[_clean(c) for c in row] for row in csv.reader(text.splitlines(), dialect) if any(_clean(c) for c in row)]


def _docx_rows(path: Path) -> list[list[str]]:
    doc = Document(path)
    rows = [[_clean(p.text)] for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [_clean(c.text) for c in row.cells]
            if any(cells):
                rows.append(cells)
    return rows


def _pdf_rows(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    cells = [_clean(c) for c in row]
                    if any(cells):
                        rows.append(cells)
            for line in (page.extract_text() or '').splitlines():
                if line.strip():
                    rows.append([_clean(line)])
    return rows


TAG = re.compile(r'<[^>]+>')


def html_lines(markup: str) -> list[str]:
    """A table keeps its shape as a ' | ' line; everything else becomes plain lines."""
    if not markup:
        return []
    text = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', markup)
    lines = []
    for row in re.findall(r'(?is)<tr[^>]*>(.*?)</tr>', text):
        cells = [' '.join(html_entities.unescape(TAG.sub('', cell)).split())
                 for cell in re.findall(r'(?is)<t[dh][^>]*>(.*?)</t[dh]>', row)]
        if any(cells):
            lines.append(' | '.join(cells))
    for line in html_entities.unescape(TAG.sub('\n', re.sub(r'(?is)<table.*?</table>', ' ', text))).splitlines():
        line = ' '.join(line.split())
        if line:
            lines.append(line)
    return lines


def email_lines(path: Path) -> list[str]:
    """Plain prose plus anything only the HTML alternative carries, such as the price table."""
    from email import policy
    message = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    plain, markup = [], []
    for part in message.walk():
        kind = part.get_content_type()
        if kind == 'text/plain':
            plain.append(part.get_content())
        elif kind == 'text/html':
            markup.append(part.get_content())
    lines = [' '.join(l.split()) for l in '\n'.join(plain).splitlines()]
    lines = [l for l in lines if l]
    seen = set(lines)
    for line in html_lines('\n'.join(markup)):
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return lines


def _text_rows(path: Path) -> list[list[str]]:
    if path.suffix.lower() == '.eml':
        return [[_clean(cell) for cell in line.split(' | ')] for line in email_lines(path)]
    body = path.read_text(encoding='utf-8', errors='replace')
    return [[_clean(line)] for line in body.splitlines() if line.strip()]


READERS = {'.xlsx': _xlsx_rows, '.csv': _csv_rows, '.docx': _docx_rows, '.pdf': _pdf_rows,
           '.txt': _text_rows, '.eml': _text_rows}


def _role(cell: str) -> str | None:
    text = cell.lower().strip(' .:*#')
    if not text or len(text) > 40:
        return None
    for role, headers in (('quantity', QUANTITY_HEADERS), ('weight', WEIGHT_HEADERS), ('term', TERM_HEADERS), ('unit', UNIT_HEADERS),
                          ('sku', SKU_HEADERS), ('description', DESCRIPTION_HEADERS)):
        if any(text == h or text.startswith(h + ' ') or text.endswith(' ' + h) or f' {h} ' in f' {text} '
               for h in headers):
            return role
    return None


# A one-line requirement is often written down the page rather than across it.
ITEM_FIELDS = {
    'sku': ('sku', 'part number', 'part no', 'item code', 'material code', 'product code', 'model number'),
    'quantity': ('quantity', 'qty', 'number of units', 'units required', 'volume'),
    'unit': ('unit of measure', 'uom', 'unit'),
    'term': ('rental term', 'contract term', 'lease term', 'subscription term', 'term', 'duration', 'tenure'),
    'description': ('item', 'product', 'service', 'requirement', 'description', 'material', 'equipment',
                    'scope of supply', 'asset'),
}


def _header_rows(rows: list[list[str]]):
    """Every row that could be a header, in order; the caller decides which one works."""
    for index, row in enumerate(rows[:40]):
        roles: dict[str, int] = {}
        for column, cell in enumerate(row):
            role = _role(cell)
            if role and role not in roles:
                roles[role] = column
        if 'quantity' in roles and ('description' in roles or 'sku' in roles):
            yield index, roles


def _labelled(row: list[str]) -> tuple[str, str]:
    """A label and its value, whether they sit in two cells or in one line of text."""
    cells = [c for c in row if c]
    if not cells:
        return '', ''
    if len(cells) >= 2:
        return cells[0], ' '.join(cells[1:])
    text = cells[0]
    for labels in ITEM_FIELDS.values():
        for label in sorted(labels, key=len, reverse=True):
            if text.lower().startswith(label.lower()):
                rest = text[len(label):].lstrip(' :\t-')
                if rest:
                    return label, rest
    return '', ''


def _role_of_label(label: str) -> str | None:
    key = re.sub(r'[^a-z ]', ' ', label.lower())
    key = ' '.join(key.split())
    if not key:
        return None
    for role, labels in ITEM_FIELDS.items():
        if any(word == key or word in key.split() or word in key for word in labels):
            return role
    return None


def single_item_from_fields(rows: list[list[str]]) -> tuple[list[dict[str, Any]], str]:
    """One requirement stated as fields: Item / Quantity / Unit / Term."""
    found: dict[str, str] = {}
    for row in rows:
        label, value = _labelled(row)
        role = _role_of_label(label) if label and value else None
        if role and role not in found:
            found[role] = value
    quantity = _number(found.get('quantity'))
    description = found.get('description') or found.get('sku')
    if not description or quantity is None or quantity <= 0:
        return [], ''
    unit = found.get('unit')
    if not unit:
        # "100 devices" states its own unit; keep the buyer's word for it.
        trailing = re.sub(r'^[\d.,\s]+', '', found.get('quantity', '')).strip()
        unit = trailing.split(',')[0] if trailing and len(trailing) <= 24 else 'piece'
    item = {'description': description[:300], 'quantity': quantity, 'unit': (unit or 'piece')[:40]}
    if found.get('sku') and found.get('description'):
        item['sku'] = found['sku'][:60]
    term = _number(found.get('term'))
    if term and term > 0:
        item['term_months'] = term
    return [item], 'Read one requirement from the Item and Quantity fields.'


def items_from_rows(rows: list[list[str]]) -> tuple[list[dict[str, Any]], str]:
    # A sheet often carries more than one header-shaped row — a blank supplier-response
    # template beside the real requirement table. Score them and keep the best reading.
    candidates = []
    for index, roles in _header_rows(rows):
        found = _items_below(rows, index, roles)
        candidates.append(((len(found[0]), 'description' in roles, len(roles)), found))
    if candidates:
        score, found = max(candidates, key=lambda c: c[0])
        if found[0]:
            return found
    fallback = single_item_from_fields(rows)
    if fallback[0]:
        return fallback
    if candidates:
        return candidates[0][1]
    return [], 'No requirement table was recognised: name the columns, for example description, quantity and unit.'


def _items_below(rows: list[list[str]], index: int, roles: dict[str, int]) -> tuple[list[dict[str, Any]], str]:
    cell = lambda row, role: row[roles[role]] if role in roles and roles[role] < len(row) else ''
    items, skipped = [], 0
    for row in rows[index + 1:]:
        if not any(row):
            continue
        sku = cell(row, 'sku')
        description = cell(row, 'description') or sku
        quantity = _number(cell(row, 'quantity'))
        if not description or quantity is None or quantity <= 0:
            skipped += 1
            continue
        unit = cell(row, 'unit') or 'piece'
        item = {'description': description[:300], 'quantity': quantity, 'unit': unit[:40]}
        if sku:
            item['sku'] = sku[:60]
        weight = _number(cell(row, 'weight'))
        if weight and weight > 0:
            item['unit_weight_kg'] = weight
        term = _number(cell(row, 'term'))
        if term and term > 0:
            item['term_months'] = term
        items.append(item)
        if len(items) == MAX_ITEMS:
            break
    columns = ', '.join(sorted(roles))
    note = f'Mapped {len(items)} requirement line(s) from the {columns} columns.'
    if skipped:
        note += f' {skipped} row(s) without a description or a positive quantity were left out.'
    return items, note


def fields_from_rows(rows: list[list[str]], allowed: set[str]) -> dict[str, str]:
    """Labelled values only: "Payment terms: 45 days net" or a two-cell sheet row."""
    found: dict[str, list[str]] = {}
    for row in rows:
        pairs = []
        if len(row) >= 2 and row[0] and row[1]:
            pairs.append((row[0], ' '.join(c for c in row[1:] if c)))
        for cellvalue in row:
            match = re.match(r'^([A-Za-z][A-Za-z /&\'()\-]{2,40})\s*[:\-–]\s*(\S.*)$', cellvalue)
            if match:
                pairs.append((match.group(1), match.group(2)))
        for label, value in pairs:
            key = re.sub(r'[^a-z ]', ' ', label.lower()).strip()
            value = _clean(value)[:1000]
            if not key or not value or len(value) < 2:
                continue
            field = next((f for text, f in LABEL_LOOKUP if text in key), None)
            if field and field in allowed and value not in found.get(field, []):
                found.setdefault(field, []).append(value)
    return {field: '; '.join(values)[:6000] for field, values in found.items()}


def read(path: Path, filename: str) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    reader = READERS.get(suffix)
    if not reader:
        raise ValueError(f'{filename}: attach an Excel, CSV, PDF, Word, text or email file')
    try:
        rows = reader(path)
    except Exception as error:  # a corrupt or password-protected file must not break the conversation
        raise ValueError(f'{filename} could not be read ({type(error).__name__}). Attach it in another format.') from None
    items, note = items_from_rows(rows)
    text = '\n'.join(' | '.join(c for c in row if c) for row in rows)[:MAX_TEXT]
    return {'filename': filename, 'rows': rows[:400], 'text': text, 'items': items, 'note': note}
