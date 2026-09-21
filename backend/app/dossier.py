"""The event written down: one Markdown dossier per supplier, plus the requirement.

Rendered from the same graph the structured queries run on, so the prose and the
numbers can never disagree. Tables where the data is tabular, sentences where it is
not, and every quoted figure carries the source it came from.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import knowledge, repository as repo


def _slug(text: str) -> str:
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', str(text).lower())).strip('-') or 'supplier'


def _cell(value: Any) -> str:
    if value is None or value == '':
        return '—'
    if isinstance(value, float):
        return f'{value:,.2f}'.rstrip('0').rstrip('.')
    if isinstance(value, int):
        return f'{value:,}'
    return str(value).replace('|', '\\|').replace('\n', ' ')


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return '_None recorded._\n'
    out = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |']
    out += ['| ' + ' | '.join(_cell(c) for c in row) + ' |' for row in rows]
    return '\n'.join(out) + '\n'


def requirement_doc(g: knowledge.Graph) -> str:
    event = g.nodes['event']['attrs']
    lines = sorted(g.of_type('requirement'), key=lambda n: n['attrs']['line_no'])
    questions = sorted(g.of_type('question'), key=lambda n: n['attrs'].get('question_id', ''))
    out = [f"# Requirement — {g.nodes['event']['label']}", '',
           f"*Event `{event.get('event_id')}` · data v{g.version} · status {event.get('status')}*", '']
    if event.get('scope'):
        out += ['## Scope', '', event['scope'], '']
    out += ['## Requirement lines', '',
            _table(['#', 'SKU', 'Description', 'Quantity', 'Unit', 'Unit weight kg', 'Term months'],
                   [[n['attrs']['line_no'], n['attrs'].get('sku'), n['label'], n['attrs'].get('annual_quantity'),
                     n['attrs'].get('unit'), n['attrs'].get('unit_weight_kg'), n['attrs'].get('term_months')]
                    for n in lines]), '']
    out += ['## Questions asked of every supplier', '',
            _table(['ID', 'Question', 'Type', 'Mandatory'],
                   [[n['attrs']['question_id'], n['label'], n['attrs'].get('answer_type'),
                     'yes' if n['attrs'].get('mandatory') else 'no'] for n in questions]), '']
    rules = [[n['attrs']['name'].replace('_', ' '), n['attrs']['value']] for n in g.of_type('rule')]
    out += ['## Commercial rules', '', _table(['Rule', 'Value'], rules), '']
    return '\n'.join(out)


def supplier_doc(g: knowledge.Graph, supplier: dict[str, Any]) -> str:
    attrs = supplier['attrs']
    quotes = sorted((q for q in g.out(supplier['id'], 'quoted') if q['attrs'].get('line_no')),
                    key=lambda q: q['attrs']['line_no'])
    requirements = {n['attrs']['line_no']: n for n in g.of_type('requirement')}
    questions = {n['attrs']['question_id']: n for n in g.of_type('question')}
    out = [f"# {supplier['label']}", '',
           f"*Supplier in event `{g.nodes['event']['attrs'].get('event_id')}` · data v{g.version}*", '',
           '## At a glance', '',
           _table(['Field', 'Value'],
                  [['Qualification', attrs.get('qualification')], ['Response status', attrs.get('response_status')],
                   ['Contact', attrs.get('email')], ['Lines quoted', len(quotes)],
                   ['Extraction method', attrs.get('extraction_method')], ['Model', attrs.get('model')]]), '']

    documents = g.out(supplier['id'], 'submitted')
    out += ['## Documents received', '',
            _table(['#', 'File'], [[d['attrs'].get('index', 0) + 1, d['label']] for d in documents]), '']

    terms = g.out(supplier['id'], 'states')
    out += ['## Commercial terms stated', '',
            _table(['Term', 'Value', 'Source'],
                   [[t['attrs'].get('kind', '').replace('_', ' '), t['attrs'].get('value'), t['attrs'].get('source')]
                    for t in sorted(terms, key=lambda t: t['attrs'].get('kind', ''))]), '']

    answers = sorted(g.out(supplier['id'], 'answered'), key=lambda a: a['attrs'].get('question_id', ''))
    out += ['## Answers to the buyer’s questions', '',
            _table(['ID', 'Question', 'Answer'],
                   [[a['attrs']['question_id'],
                     questions.get(a['attrs']['question_id'], {}).get('label', '—'),
                     a['attrs'].get('answer')] for a in answers]), '']

    priced = []
    for quote in quotes:
        q = quote['attrs']
        line = requirements.get(q['line_no'], {}).get('attrs', {})
        priced.append([q['line_no'], line.get('sku'), q.get('raw_price'), q.get('raw_currency'),
                       q.get('raw_basis_text') or q.get('raw_basis'), q.get('landed_unit_cost'),
                       q.get('lead_days'), q.get('status'), q.get('withheld_reason')])
    out += ['## Quoted lines', '', '_Landed unit cost is INR per requirement unit, after the normalization below._', '',
            _table(['#', 'SKU', 'Quoted', 'Currency', 'Basis', 'Landed INR/unit', 'Lead days', 'Status', 'Withheld because'],
                   priced), '']

    traces = [q for q in quotes if q['attrs'].get('transformation_steps')]
    if traces:
        out += ['## How each price was normalized', '']
        for quote in traces:
            q = quote['attrs']
            out.append(f"**Line {q['line_no']} — {requirements.get(q['line_no'], {}).get('attrs', {}).get('sku', '')}**")
            out += [f'  {index}. {step}' for index, step in enumerate(q['transformation_steps'], 1)]
            out.append('')

    reviews = [r for r in g.into(supplier['id'], 'about_supplier')]
    out += ['## Open reviews', '',
            _table(['Severity', 'Title', 'Detail', 'Status'],
                   [[r['attrs'].get('severity'), r['label'], r['attrs'].get('detail'), r['attrs'].get('status')]
                    for r in reviews if r['attrs'].get('status') != 'resolved_by_buyer']), '']
    if attrs.get('notes'):
        out += ['## Interpretation notes', ''] + [f'- {note}' for note in attrs['notes']] + ['']
    return '\n'.join(out)


def build(data: dict[str, Any] | None = None) -> dict[str, str]:
    """Every document for the current snapshot, keyed by file name."""
    g = knowledge.build(data)
    files = {'requirement.md': requirement_doc(g)}
    for supplier in sorted(g.of_type('supplier'), key=lambda n: n['label'].lower()):
        files[f"supplier-{_slug(supplier['label'])}.md"] = supplier_doc(g, supplier)
    index = [f"# Knowledge base — {g.nodes['event']['label']}", '',
             f'*data v{g.version} · {len(files)} documents*', '',
             '| Document | Covers |', '| --- | --- |',
             '| `requirement.md` | What the buyer asked for, and the questions every supplier answered |']
    for name in list(files)[1:]:
        index.append(f"| `{name}` | One supplier: terms, answers, quoted lines and how each price was normalized |")
    files['index.md'] = '\n'.join(index) + '\n'
    return files


def write(data: dict[str, Any] | None = None) -> Path:
    """Materialise the dossiers on disk so they can be read, diffed or shipped."""
    data = data or repo.read()
    folder = repo.runtime_dir() / 'knowledge' / f"v{data['dataset_version']}"
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in build(data).items():
        (folder / name).write_text(body, encoding='utf-8')
    return folder


def corpus(data: dict[str, Any] | None = None, limit: int = 60000) -> str:
    """The whole knowledge base as one string, for answering in prose."""
    files = build(data)
    parts = [f'<<< {name} >>>\n{body}' for name, body in files.items() if name != 'index.md']
    text = '\n\n'.join(parts)
    return text[:limit]
