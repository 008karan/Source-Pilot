"""The sourcing event as a graph: one node per real thing, one edge per real link.

Built deterministically from an immutable dataset snapshot, so the graph is never a
second copy of the truth that can drift — it is the same facts, addressable. Every
node carries the attributes that are actually present, so a field added by extraction
tomorrow is queryable tomorrow without touching this module.

    event ──has_requirement──▶ requirement ◀──for_requirement── quote
      │                                                          │
      ├──asks──▶ question ◀──answers── answer ──┐                ├──evidenced_by──▶ evidence
      │                                          │                │
      └──governed_by──▶ rule                     │                └──sourced_from──▶ document
                                                 │
    supplier ──responds_to──▶ event              │
      ├──submitted──▶ document                   │
      ├──quoted──▶ quote ───────────────────────┘
      ├──states──▶ term ──evidenced_by──▶ evidence
      └──answered──▶ answer
    review ──about_supplier──▶ supplier, ──about_requirement──▶ requirement
"""
from __future__ import annotations

import re
from typing import Any

from . import repository as repo

# Only a display convenience: an unknown kind still becomes a dimension, titled from itself.
TERM_LABELS = {'freight': 'Freight & delivery basis', 'payment': 'Payment terms', 'validity': 'Offer validity',
               'warranty': 'Warranty / service level', 'tax': 'Tax treatment', 'lead_time': 'Stated lead time',
               'currency': 'Quoting currency'}
TERM_KEYS = {
    'freight': ('freight', 'delivery charge', 'shipping', 'transport', 'carriage', 'incoterm'),
    'payment': ('payment', 'credit period', 'milestone'),
    'validity': ('validity', 'valid for', 'offer valid'),
    'warranty': ('warranty', 'guarantee', 'service level', 'amc'),
    'tax': ('tax', 'gst', 'vat', 'duty'),
    'lead_time': ('lead time', 'lead_time', 'delivery time', 'delivery lead', 'dispatch'),
}
FREIGHT_WORDS = {'included': 'Included in price', 'flat': 'Flat rate per unit', 'percent': 'Percentage of value',
                 'order_total': 'Charged once for the whole order', 'excluded': 'Charged separately',
                 'unknown': 'Not stated'}


def term_kind(text: str) -> str | None:
    text = (text or '').lower()
    return next((key for key, words in TERM_KEYS.items() if any(w in text for w in words)), None)


def question_kind(question: dict[str, Any]) -> str | None:
    """What a question is really about: its recorded topic, else its own wording.

    A question quotes the buyer's requirement after a colon. Scanning that too once
    filed the compliance question as the tax answer, because the requirement happened
    to mention GST registration.
    """
    topic = (question or {}).get('topic')
    if topic:
        return topic if topic in TERM_KEYS else None
    return term_kind(str((question or {}).get('question', '')).split(':', 1)[0])


def _clean(value: Any, limit: int = 300) -> str:
    return ' '.join(str(value).split())[:limit]


class Graph:
    def __init__(self, version: int):
        self.version = version
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, str]] = []
        self._linked: set[tuple[str, str, str]] = set()

    def add(self, node_id: str, node_type: str, label: str, **attrs) -> str:
        self.nodes[node_id] = {'id': node_id, 'type': node_type, 'label': _clean(label, 200),
                               'attrs': {k: v for k, v in attrs.items() if v is not None and v != ''}}
        return node_id

    def link(self, source: str, edge: str, target: str) -> None:
        # One edge per relationship: a node restated is still the same node.
        key = (source, edge, target)
        if source in self.nodes and target in self.nodes and key not in self._linked:
            self._linked.add(key)
            self.edges.append({'source': source, 'type': edge, 'target': target})

    def of_type(self, node_type: str) -> list[dict[str, Any]]:
        return [n for n in self.nodes.values() if n['type'] == node_type]

    def out(self, node_id: str, edge: str) -> list[dict[str, Any]]:
        return [self.nodes[e['target']] for e in self.edges if e['source'] == node_id and e['type'] == edge]

    def into(self, node_id: str, edge: str) -> list[dict[str, Any]]:
        return [self.nodes[e['source']] for e in self.edges if e['target'] == node_id and e['type'] == edge]

    def as_dict(self) -> dict[str, Any]:
        return {'dataset_version': self.version, 'nodes': list(self.nodes.values()), 'edges': self.edges,
                'counts': {t: len(self.of_type(t)) for t in sorted({n['type'] for n in self.nodes.values()})}}


def build(data: dict[str, Any] | None = None) -> Graph:
    """Every node and edge comes from the snapshot; nothing is assumed about the category."""
    data = data or repo.read()
    rfx = data['rfx']
    g = Graph(data['dataset_version'])

    event = g.add('event', 'event', rfx.get('title') or rfx['event_id'],
                  event_id=rfx['event_id'], category=rfx.get('category'), buyer=rfx.get('buyer'),
                  scope=rfx.get('scope'), status=data['rfx_status'], stage=data.get('stage'),
                  currency=rfx.get('currency'), line_count=len(rfx['items']))
    for key, value in (rfx.get('commercial_rules') or {}).items():
        g.link(event, 'governed_by', g.add(f'rule:{key}', 'rule', key.replace('_', ' '), name=key, value=value))
    for item in rfx['items']:
        node = g.add(f"requirement:{item['line_no']}", 'requirement', item.get('description') or item['sku'],
                     **{k: v for k, v in item.items() if k != 'description'})
        g.link(event, 'has_requirement', node)
    for question in rfx.get('questionnaire') or []:
        node = g.add(f"question:{question['id']}", 'question', question['question'],
                     question_id=question['id'], answer_type=question.get('type'), mandatory=question.get('mandatory'))
        g.link(event, 'asks', node)

    for eid, record in (data.get('evidence') or {}).items():
        location = ' · '.join(str(record[k]) for k in ('file', 'sheet', 'cell_range', 'page', 'table', 'row')
                              if record.get(k) is not None)
        g.add(f'evidence:{eid}', 'evidence', location or record.get('file') or 'source',
              **{k: v for k, v in record.items() if k not in ('blocks', 'raw_fact', 'source_path')})

    quotes: dict[tuple[str, int], str] = {}
    for vid, vendor in data['vendors'].items():
        supplier = g.add(f'supplier:{vid}', 'supplier', vendor['name'], vendor_id=vid, email=vendor.get('email'),
                         qualification=vendor.get('quality'), response_status=vendor.get('response_status'),
                         extraction_method=vendor.get('method'), model=vendor.get('model'),
                         lead_days=vendor.get('lead'), notes=vendor.get('unresolved') or None)
        g.link(supplier, 'responds_to', event)
        for index, document in enumerate(vendor.get('documents') or []):
            node = g.add(f'document:{vid}:{index}', 'document', document.get('filename') or f'document {index + 1}',
                         filename=document.get('filename'), index=index, vendor_id=vid)
            g.link(supplier, 'submitted', node)

        terms = vendor.get('terms') or {}
        stated: dict[str, tuple[str, str]] = {}
        # An answer to the buyer's own question states a term just as much as a cover note does.
        questions = {q['id']: q for q in rfx.get('questionnaire') or []}
        for qid, answer in sorted((vendor.get('questionnaire') or {}).items()):
            kind = question_kind(questions.get(qid))
            value = _clean(answer.get('answer'))
            if kind and value and kind not in stated:
                stated[kind] = (value, f'Answer to {qid}')
        for entry in terms.get('captured') or []:
            kind = term_kind(entry.get('term_type')) or term_kind(entry.get('value'))
            value = _clean(entry.get('value'))
            if kind and value and kind not in stated:
                stated[kind] = (value, 'Stated in the response')
        for kind, (value, origin) in stated.items():
            node = g.add(f'term:{vid}:{kind}', 'term', value, kind=kind, value=value,
                         source=origin, vendor_id=vid)
            g.link(supplier, 'states', node)
            if vendor.get('terms_evidence_id'):
                g.link(node, 'evidenced_by', f"evidence:{vendor['terms_evidence_id']}")
        # Freight and currency are decided facts, not just quoted text: record how they were settled.
        for kind, value, source in (
            ('freight', FREIGHT_WORDS.get(terms.get('freight', 'unknown'), terms.get('freight')),
             (f"Buyer decision by {terms['freight_override']['actor']}" if terms.get('freight_override')
              else f"Source: “{_clean(terms['freight_source'], 140)}”" if terms.get('freight_source')
              else 'Not stated in the response')),
            ('currency', terms.get('currency'), terms.get('currency_source')),
        ):
            if not value:
                continue
            detail = value
            if kind == 'freight' and terms.get('freight') == 'flat':
                detail += f" (INR {terms.get('freight_per_piece_inr')}/unit)"
            elif kind == 'freight' and terms.get('freight') == 'percent':
                detail += f" ({terms.get('freight_percent', 0) * 100:g}% of material value)"
            elif kind == 'freight' and terms.get('freight') == 'order_total':
                detail += f" ({terms.get('freight_currency', 'INR')} {terms.get('freight_total', 0):,.0f}, apportioned by line value)"
            node = g.add(f'term:{vid}:{kind}', 'term', detail, kind=kind, value=detail,
                         source=source or 'Derived from the response', vendor_id=vid)
            g.link(supplier, 'states', node)
            if vendor.get('terms_evidence_id'):
                g.link(node, 'evidenced_by', f"evidence:{vendor['terms_evidence_id']}")

        for qid, answer in (vendor.get('questionnaire') or {}).items():
            node = g.add(f'answer:{vid}:{qid}', 'answer', _clean(answer.get('answer')), question_id=qid,
                         answer=_clean(answer.get('answer')), confidence=answer.get('confidence'), vendor_id=vid)
            g.link(supplier, 'answered', node)
            g.link(node, 'answers', f'question:{qid}')
            if answer.get('evidence', {}).get('evidence_id'):
                g.link(node, 'evidenced_by', f"evidence:{answer['evidence']['evidence_id']}")

        for fact in vendor.get('facts') or []:
            line = fact.get('line_no')
            node = g.add(f'quote:{vid}:{line}', 'quote', f"{vendor['name']} · line {line}", vendor_id=vid,
                         **{k: v for k, v in fact.items() if k not in ('evidence', 'buyer_override')})
            if fact.get('buyer_override'):
                g.nodes[node]['attrs']['buyer_override'] = {k: fact['buyer_override'].get(k)
                                                            for k in ('actor', 'reason', 'action', 'timestamp')}
            g.link(supplier, 'quoted', node)
            g.link(node, 'for_requirement', f'requirement:{line}')
            if fact.get('evidence_id'):
                g.link(node, 'evidenced_by', f"evidence:{fact['evidence_id']}")
            filename = (fact.get('evidence') or {}).get('file')
            for index, document in enumerate(vendor.get('documents') or []):
                if document.get('filename') == filename:
                    g.link(node, 'sourced_from', f'document:{vid}:{index}')
            quotes[(vid, line)] = node

    # The comparison carries the arithmetic; it belongs on the quote it was computed for.
    for row in data.get('comparison') or []:
        for vid, cell in row['vendors'].items():
            node = quotes.get((vid, row['line_no']))
            if not node:
                continue
            g.nodes[node]['attrs'].update({k: cell[k] for k in
                                           ('unit_price', 'landed_unit_cost', 'transformation_steps',
                                            'blocking_exception', 'status', 'recurring') if k in cell})
            if cell.get('reason'):
                g.nodes[node]['attrs']['withheld_reason'] = cell['reason']

    for exception in data.get('exceptions') or []:
        node = g.add(f"review:{exception['id']}", 'review', exception['title'],
                     **{k: v for k, v in exception.items() if k not in ('title', 'vendor_id', 'line_no')})
        g.link(node, 'about_supplier', f"supplier:{exception['vendor_id']}")
        if exception.get('line_no'):
            g.link(node, 'about_requirement', f"requirement:{exception['line_no']}")
        if exception.get('evidence_id'):
            g.link(node, 'evidenced_by', f"evidence:{exception['evidence_id']}")
    return g


# ---------------------------------------------------------------- dimensions

def dimensions(g: Graph) -> list[dict[str, Any]]:
    """What this event can be compared on, read off the graph rather than a fixed list."""
    dims = [
        {'key': 'cost', 'label': 'Comparable quoted cost', 'short': 'cost', 'kind': 'number', 'better': 'low',
         'unit': 'INR', 'note': 'Same lines for every supplier compared'},
        {'key': 'delivery', 'label': 'Quoted lead time', 'short': 'lead time', 'kind': 'number', 'better': 'low',
         'unit': 'days', 'note': 'Slowest line in the compared set'},
        {'key': 'coverage', 'label': 'Requirement lines priced', 'short': 'coverage', 'kind': 'number',
         'better': 'high', 'unit': 'lines', 'note': 'Lines with a usable price'},
        {'key': 'qualification', 'label': 'Mandatory qualification', 'short': 'qualification', 'kind': 'status',
         'better': 'pass', 'note': 'Declared compliance, not a quality score'},
        {'key': 'reviews', 'label': 'Open reviews', 'short': 'open reviews', 'kind': 'number', 'better': 'low',
         'unit': 'open', 'note': 'Decisions waiting on you'},
    ]
    for kind in sorted({n['attrs'].get('kind') for n in g.of_type('term') if n['attrs'].get('kind')}):
        dims.append({'key': f'term:{kind}', 'label': TERM_LABELS.get(kind, kind.replace('_', ' ').capitalize()),
                     'short': kind.replace('_', ' '), 'kind': 'stated', 'better': None, 'note': 'Supplier’s own words'})
    for question in sorted(g.of_type('question'), key=lambda n: n['attrs'].get('question_id', '')):
        qid = question['attrs']['question_id']
        dims.append({'key': f'answer:{qid}', 'label': question['label'], 'short': f'answer to {qid}',
                     'kind': 'stated', 'better': None,
                     'note': 'Mandatory question' if question['attrs'].get('mandatory') else 'Asked in the RFx'})
    return dims


def suppliers(g: Graph) -> list[dict[str, Any]]:
    return [{'id': n['id'], 'name': n['label'], 'qualification': n['attrs'].get('qualification'),
             'responded': n['attrs'].get('response_status') == 'processed'}
            for n in sorted(g.of_type('supplier'), key=lambda n: n['label'].lower())]


def schema(g: Graph) -> dict[str, Any]:
    return {'dataset_version': g.version, 'dimensions': dimensions(g), 'suppliers': suppliers(g),
            'node_types': sorted({n['type'] for n in g.nodes.values()}),
            'edge_types': sorted({e['type'] for e in g.edges}),
            'requirements': [{'line_no': n['attrs']['line_no'], 'label': n['label']}
                             for n in sorted(g.of_type('requirement'), key=lambda n: n['attrs']['line_no'])]}


# ---------------------------------------------------------------- querying

def _usable(quote: dict[str, Any]) -> bool:
    attrs = quote['attrs']
    return attrs.get('landed_unit_cost') is not None and not attrs.get('blocking_exception') \
        and attrs.get('status') == 'quoted'


def _quotes(g: Graph, supplier_id: str) -> dict[int, dict[str, Any]]:
    return {q['attrs']['line_no']: q for q in g.out(supplier_id, 'quoted') if q['attrs'].get('line_no')}


def basket(g: Graph, supplier_ids: list[str], lines: list[int] | None = None) -> list[int]:
    """The lines every compared supplier priced — the only like-for-like basis there is."""
    priced = [set(line for line, q in _quotes(g, sid).items() if _usable(q)) for sid in supplier_ids]
    common = set.intersection(*priced) if priced and all(priced) else set()
    if lines:
        common &= set(lines)
    return sorted(common)


def _cell(value, display, numeric=None, evidence=None, source=None, detail=None):
    return {'value': value, 'display': display, 'numeric': numeric, 'evidence_id': evidence,
            'source': source, 'detail': detail}


def evaluate(g: Graph, key: str, supplier_ids: list[str], lines: list[int]) -> dict[str, dict[str, Any]]:
    """One dimension, for the suppliers asked about, on the lines they share."""
    out: dict[str, dict[str, Any]] = {}
    requirements = {n['attrs']['line_no']: n for n in g.of_type('requirement')}
    for sid in supplier_ids:
        supplier = g.nodes[sid]
        quotes = _quotes(g, sid)
        if key == 'cost':
            covered = [l for l in lines if l in quotes and _usable(quotes[l])]
            total = sum(requirements[l]['attrs'].get('annual_quantity', 0) * quotes[l]['attrs']['landed_unit_cost']
                        for l in covered) if covered and len(covered) == len(lines) else None
            out[sid] = _cell(total, f'₹{total:,.2f}' if total is not None else 'Not comparable', total,
                             detail=f"{len(covered)} of {len(lines)} compared line(s)" if lines else None)
        elif key == 'delivery':
            leads = [quotes[l]['attrs'].get('lead_days') for l in lines if l in quotes]
            leads = [x for x in leads if isinstance(x, (int, float))]
            worst = max(leads) if leads and len(leads) == len(lines) else None
            out[sid] = _cell(worst, f'{worst:g} days' if worst is not None else 'Not stated', worst)
        elif key == 'coverage':
            priced = sum(1 for q in quotes.values() if _usable(q))
            out[sid] = _cell(priced, f'{priced} / {len(requirements)} lines', priced)
        elif key == 'qualification':
            value = supplier['attrs'].get('qualification')
            label = {'pass': 'Meets requirements', 'pending': 'Needs review', 'fail': 'Does not qualify'}.get(value, value)
            out[sid] = _cell(value, label or 'Not extracted', 1 if value == 'pass' else 0)
        elif key == 'reviews':
            open_reviews = [r for r in g.into(sid, 'about_supplier') if r['attrs'].get('status') != 'resolved_by_buyer']
            out[sid] = _cell(len(open_reviews), f'{len(open_reviews)} open', len(open_reviews),
                             detail='; '.join(r['label'] for r in open_reviews[:3]) or None)
        elif key.startswith('term:'):
            kind = key.split(':', 1)[1]
            node = next((t for t in g.out(sid, 'states') if t['attrs'].get('kind') == kind), None)
            evidence = (g.out(node['id'], 'evidenced_by') or [None])[0] if node else None
            out[sid] = _cell(node['attrs']['value'] if node else None,
                             node['attrs']['value'] if node else 'Not stated', None,
                             evidence['id'].split(':', 1)[1] if evidence else None,
                             node['attrs'].get('source') if node else None)
        elif key.startswith('answer:'):
            qid = key.split(':', 1)[1]
            node = next((a for a in g.out(sid, 'answered') if a['attrs'].get('question_id') == qid), None)
            evidence = (g.out(node['id'], 'evidenced_by') or [None])[0] if node else None
            out[sid] = _cell(node['attrs']['answer'] if node else None,
                             node['attrs']['answer'] if node else 'Not answered', None,
                             evidence['id'].split(':', 1)[1] if evidence else None,
                             f'Answer to {qid}' if node else None)
        else:
            out[sid] = _cell(None, 'Not available', None)
    return out


def _winners(dim: dict[str, Any], cells: dict[str, dict[str, Any]]) -> list[str]:
    better = dim.get('better')
    if not better:
        return []
    if better == 'pass':
        return [sid for sid, cell in cells.items() if cell['value'] == 'pass']
    numbers = [(sid, cell['numeric']) for sid, cell in cells.items() if cell['numeric'] is not None]
    if not numbers:
        return []
    best = min(n for _, n in numbers) if better == 'low' else max(n for _, n in numbers)
    return [sid for sid, n in numbers if n == best]


def compare(spec: dict[str, Any], data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a comparison spec against the graph. Deterministic; nothing is invented."""
    g = build(data)
    known = {s['id']: s for s in suppliers(g)}
    wanted = spec.get('suppliers') or []
    chosen = [sid for sid in wanted if sid in known] or [s for s in known if known[s]['responded']]
    if not chosen:
        chosen = list(known)
    available = {d['key']: d for d in dimensions(g)}
    keys = [k for k in (spec.get('dimensions') or []) if k in available]
    if not keys:
        keys = [k for k in ('cost', 'delivery', 'qualification', 'coverage') if k in available]
        keys += [k for k in available if k.startswith('term:')]
    lines = basket(g, chosen, spec.get('requirements'))
    rows = []
    for key in keys:
        dim = available[key]
        cells = evaluate(g, key, chosen, lines)
        rows.append({**dim, 'cells': cells, 'winners': _winners(dim, cells)})
    segments: dict[str, list[str]] = {}
    for row in rows:
        for sid in row['winners']:
            if len(row['winners']) < len(chosen):
                segments.setdefault(sid, []).append(row.get('short') or row['label'])
    return {'dataset_version': g.version,
            'suppliers': [{'id': sid, 'name': known[sid]['name'], 'qualification': known[sid]['qualification']}
                          for sid in chosen],
            'rows': rows, 'segments': segments, 'compared_lines': lines,
            'total_lines': len(g.of_type('requirement')),
            'requirements': [{'line_no': n['attrs']['line_no'], 'label': n['label']}
                             for n in sorted(g.of_type('requirement'), key=lambda n: n['attrs']['line_no'])
                             if n['attrs']['line_no'] in lines]}


def by_line(spec: dict[str, Any], data: dict[str, Any] | None = None) -> dict[str, Any]:
    """One row per requirement line, one column per supplier: the SKU-wise view."""
    g = build(data)
    known = {s['id']: s for s in suppliers(g)}
    wanted = [sid for sid in (spec.get('suppliers') or []) if sid in known]
    chosen = wanted or [s for s in known if known[s]['responded']] or list(known)
    metric = 'delivery' if 'delivery' in (spec.get('dimensions') or []) else 'cost'
    lines = set(spec.get('requirements') or [])
    rows, priced = [], set()
    for requirement in sorted(g.of_type('requirement'), key=lambda n: n['attrs']['line_no']):
        line = requirement['attrs']['line_no']
        if lines and line not in lines:
            continue
        cells = {}
        for sid in chosen:
            quote = next((q for q in g.out(sid, 'quoted') if q['attrs'].get('line_no') == line), None)
            if quote and _usable(quote):
                attrs = quote['attrs']
                value = attrs['landed_unit_cost'] if metric == 'cost' else attrs.get('lead_days')
                evidence = (g.out(quote['id'], 'evidenced_by') or [None])[0]
                display = f'₹{value:,.2f}' if metric == 'cost' and value is not None else \
                    f'{value:g} days' if value is not None else 'Not stated'
                cells[sid] = _cell(value, display, value,
                                   evidence['id'].split(':', 1)[1] if evidence else None,
                                   detail=attrs.get('raw_basis_text'))
                if value is not None:
                    priced.add(line)
            elif quote:
                cells[sid] = _cell(None, 'Needs review', None,
                                   detail=str(quote['attrs'].get('withheld_reason') or '')[:90] or None)
            else:
                cells[sid] = _cell(None, 'Not quoted', None)
        quantity = requirement['attrs'].get('annual_quantity') or 0
        row = {'key': f'line:{line}', 'kind': 'number', 'better': 'low',
               'unit': 'INR' if metric == 'cost' else 'days',
               'label': f"{requirement['attrs'].get('sku') or 'Line ' + str(line)} · {requirement['label']}"[:110],
               'note': f"{quantity:,.0f} {requirement['attrs'].get('unit') or 'units'}"}
        row['winners'] = _winners(row, cells)
        rows.append({**row, 'cells': cells})
    return {'dataset_version': g.version, 'axis': 'requirement', 'metric': metric,
            'suppliers': [{'id': sid, 'name': known[sid]['name'], 'qualification': known[sid]['qualification']}
                          for sid in chosen],
            'rows': rows, 'compared_lines': sorted(priced), 'total_lines': len(g.of_type('requirement')),
            'segments': {}}


def line_verdict(result: dict[str, Any]) -> str:
    """Who is cheapest on how many lines — the one line a buyer actually wants."""
    names = {s['id']: s['name'] for s in result['suppliers']}
    wins: dict[str, int] = {}
    for row in result['rows']:
        if len(row['winners']) == 1:
            wins[row['winners'][0]] = wins.get(row['winners'][0], 0) + 1
    what = 'cheapest' if result.get('metric') == 'cost' else 'fastest'
    if not wins:
        return f'No line has a single {what} supplier: every compared quote ties.'
    ranked = sorted(wins.items(), key=lambda pair: -pair[1])
    lead = ' · '.join(f'{names[sid]} {what} on {count}' for sid, count in ranked)
    return f"{lead} of {len(result['rows'])} lines."


def verdict(result: dict[str, Any]) -> str:
    """One line, read off the table that was just computed. No new claims."""
    names = {s['id']: s['name'] for s in result['suppliers']}
    if len(result['suppliers']) < 2:
        return 'Only one supplier matched.'
    leads = ' · '.join(f"{names[sid]}: {', '.join(labels)}" for sid, labels in result['segments'].items())
    rankable = any(row.get('better') for row in result['rows'])
    # Stated terms have no winner; saying "no clear leader" would read as a finding.
    parts = [f'Leads — {leads}' if leads else
             'Each supplier’s own words, side by side' if not rankable else 'No clear leader']
    parts.append(f"{len(result['compared_lines'])} of {result['total_lines']} lines compared"
                 if result['compared_lines'] else 'no line priced by all')
    unqualified = [s['name'] for s in result['suppliers'] if s['qualification'] != 'pass']
    if unqualified:
        parts.append(f"{', '.join(unqualified)} not qualified")
    return '. '.join(parts[:1]) + '. ' + ' · '.join(parts[1:]) + '.'
