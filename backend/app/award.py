"""Award selection: the final allocation, derived from already-normalized data.

Nothing in this module calls a model. The analysis room may interpret a sentence
into constraints, but every figure here is arithmetic over the reviewed snapshot,
so the same event always produces the same award.

Nothing is specific to a category either. A line is a line, a quote is a quote,
and eligibility is whatever the qualification engine already decided.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from . import repository as repo

DEFAULT_KEYS = ('lowest_cost', 'single_supplier', 'fastest_delivery')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── What may be awarded ──────────────────────────────────────────────────────

def usable(quote: dict[str, Any]) -> bool:
    """A quote we can actually award: priced, read cleanly, not blocked."""
    return (quote.get('quote_status') == 'quoted'
            and quote.get('landed_unit_cost') is not None
            and not quote.get('blocking_exception'))


def eligible(row: dict[str, Any], qualified_only: bool = True) -> dict[str, dict[str, Any]]:
    return {vid: q for vid, q in (row.get('vendors') or {}).items()
            if usable(q) and (not qualified_only or q.get('qualification') == 'pass')}


def open_reviews(data: dict[str, Any]) -> dict[str, set[int]]:
    """Which supplier/line pairs a buyer has not signed off yet."""
    out: dict[str, set[int]] = defaultdict(set)
    for e in data.get('exceptions') or []:
        if e.get('status') == 'resolved_by_buyer':
            continue
        out[e.get('vendor_id')].add(int(e.get('line_no') or 0))
    return out


def _status(quote: dict[str, Any], vendor_id: str, line_no: int, reviews: dict[str, set[int]]) -> str:
    """A line's own standing. A supplier-level note belongs in advisories, not on every row."""
    if quote.get('qualification') == 'fail':
        return 'not_eligible'
    if quote.get('qualification') != 'pass':
        return 'needs_review'
    return 'needs_review' if line_no in (reviews.get(vendor_id) or set()) else 'eligible'


def advisories(data: dict[str, Any], supplier_ids: set[str]) -> list[dict[str, Any]]:
    """Open supplier-level reviews for whoever won work: said once, not thirty times."""
    out = []
    for e in data.get('exceptions') or []:
        if e.get('status') == 'resolved_by_buyer' or int(e.get('line_no') or 0) != 0:
            continue
        if e.get('vendor_id') not in supplier_ids:
            continue
        out.append({'supplier_id': e['vendor_id'],
                    'supplier_name': (data['vendors'].get(e['vendor_id']) or {}).get('name'),
                    'title': e.get('title'), 'detail': e.get('detail'), 'exception_id': e.get('id')})
    return out


def _lead(quote: dict[str, Any]) -> int | None:
    value = quote.get('lead_days')
    return int(value) if isinstance(value, (int, float)) and value > 0 else None


# ── Building an allocation ───────────────────────────────────────────────────

Pick = Callable[[dict[str, Any], dict[str, dict[str, Any]]], str]


def allocate(data: dict[str, Any], pick: Pick, qualified_only: bool = True) -> list[dict[str, Any]]:
    """One row per requirement line, whoever wins it — or nobody."""
    reviews = open_reviews(data)
    rows: list[dict[str, Any]] = []
    for row in data.get('comparison') or []:
        line_no = row['line_no']
        options = eligible(row, qualified_only)
        base = {'line_item_id': line_no, 'sku': row.get('sku'), 'description': row.get('description'),
                'required_quantity': row.get('qty')}
        if not options:
            rows.append({**base, 'supplier_id': None, 'supplier_name': None, 'allocated_quantity': 0,
                         'normalized_unit_price': None, 'line_total': 0.0, 'lead_time_days': None,
                         'eligibility_status': 'uncovered', 'evidence_id': None})
            continue
        vid = pick(row, options)
        quote = options[vid]
        quantity = row.get('qty') or 0
        rows.append({**base,
                     'supplier_id': vid,
                     'supplier_name': (data['vendors'].get(vid) or {}).get('name'),
                     'allocated_quantity': quantity,
                     'normalized_unit_price': quote['landed_unit_cost'],
                     'line_total': round(quote['landed_unit_cost'] * quantity, 2),
                     'lead_time_days': _lead(quote),
                     'eligibility_status': _status(quote, vid, line_no, reviews),
                     'evidence_id': quote.get('evidence_id')})
    return rows


RULE_FOR_OBJECTIVE = {
    'minimize_cost': 'Each line went to the lowest normalized landed cost.',
    'minimize_lead_time': 'Each line went to the shortest quoted lead time, with landed cost as the tie-breaker.',
    'single_supplier': 'One supplier had to cover every line; the cheapest of those was chosen.',
    'custom': 'The allocation was solved against the constraints saved from your analysis.',
}


def applied_rules(objective: str, constraints: dict[str, Any]) -> list[str]:
    """Plain sentences describing what the code actually did, from its own inputs."""
    rules: list[str] = []
    if constraints.get('qualified_suppliers_only'):
        rules.append('Only suppliers meeting the mandatory requirements were considered.')
    rules.append(RULE_FOR_OBJECTIVE.get(objective, RULE_FOR_OBJECTIVE['custom']))
    if constraints.get('complete_coverage_required'):
        rules.append('Every requirement line had to be covered.')
    if constraints.get('max_suppliers'):
        rules.append(f"Maximum supplier count: {constraints['max_suppliers']}.")
    if constraints.get('max_lead_time_days'):
        rules.append(f"Maximum lead time: {constraints['max_lead_time_days']} days.")
    if constraints.get('max_supplier_share'):
        rules.append(f"No supplier above {round(constraints['max_supplier_share'] * 100)}% of award value.")
    for supplier, share in (constraints.get('supplier_shares') or {}).items():
        rules.append(f"{supplier} held to {round(share * 100)}% of every line.")
    return rules


def summarise(data: dict[str, Any], key: str, name: str, objective: str, constraints: dict[str, Any],
              allocation: list[dict[str, Any]], *, source: str = 'system', notes: str = '',
              scenario_id: str | None = None) -> dict[str, Any]:
    """An AwardScenario: the allocation plus everything the screen needs to explain it."""
    awarded = [a for a in allocation if a['supplier_id']]
    suppliers = {a['supplier_id'] for a in awarded}
    leads = [a['lead_time_days'] for a in awarded if a['lead_time_days'] is not None]
    lines = {a['line_item_id'] for a in allocation}
    awarded_lines = {a['line_item_id'] for a in awarded}
    required = sum(next(a['required_quantity'] or 0 for a in allocation if a['line_item_id'] == line)
                   for line in lines)
    allocated = sum(a['allocated_quantity'] or 0 for a in awarded)
    qualities = {(data['vendors'].get(vid) or {}).get('quality') for vid in suppliers}
    return {
        'id': scenario_id or f'{key}:{uuid4().hex[:8]}',
        'key': key,
        'event_id': (data.get('rfx') or {}).get('event_id'),
        'name': name,
        'type': key,
        'source': source,
        'objective': objective,
        'constraints': constraints,
        'allocation': allocation,
        'total_value': round(sum(a['line_total'] or 0 for a in awarded), 2),
        'currency': (data.get('rfx') or {}).get('currency') or 'INR',
        'supplier_count': len(suppliers),
        'supplier_names': sorted({a['supplier_name'] for a in awarded if a['supplier_name']}),
        'max_lead_time': max(leads) if leads else None,
        'qualification_status': 'all_qualified' if qualities and qualities <= {'pass'} else 'review_required',
        'advisories': advisories(data, suppliers),
        'coverage': {'allocated_lines': len(awarded_lines), 'total_lines': len(lines),
                     'allocated_quantity': round(allocated, 4), 'required_quantity': round(required, 4)},
        'uncovered_lines': sorted(lines - awarded_lines),
        'rules': applied_rules(objective, constraints),
        'notes': notes,
        'status': 'ok',
        'reason': None,
        'dataset_version': data.get('dataset_version'),
        'fingerprint': fingerprint(data),
        'created_at': _now(),
    }


def unavailable(data: dict[str, Any], key: str, name: str, objective: str, reason: str) -> dict[str, Any]:
    """A scenario that cannot be formed. It says so; it never invents an allocation."""
    return {'id': key, 'key': key, 'event_id': (data.get('rfx') or {}).get('event_id'), 'name': name,
            'type': key, 'source': 'system', 'objective': objective, 'constraints': {}, 'allocation': [],
            'total_value': None, 'currency': (data.get('rfx') or {}).get('currency') or 'INR',
            'supplier_count': 0, 'supplier_names': [], 'max_lead_time': None,
            'qualification_status': 'unavailable', 'coverage': None, 'uncovered_lines': [], 'rules': [],
            'advisories': [],
            'notes': '', 'status': 'infeasible', 'reason': reason,
            'dataset_version': data.get('dataset_version'), 'fingerprint': fingerprint(data),
            'created_at': _now()}


# ── The three standing scenarios ─────────────────────────────────────────────

BASE_CONSTRAINTS = {'qualified_suppliers_only': True, 'complete_coverage_required': True}


def lowest_cost(data: dict[str, Any]) -> dict[str, Any]:
    allocation = allocate(data, lambda row, options: min(options, key=lambda v: options[v]['landed_unit_cost']))
    if not any(a['supplier_id'] for a in allocation):
        return unavailable(data, 'lowest_cost', 'Lowest cost', 'minimize_cost',
                           'No eligible suppliers are available for award.')
    return summarise(data, 'lowest_cost', 'Lowest cost', 'minimize_cost', dict(BASE_CONSTRAINTS), allocation)


def fastest_delivery(data: dict[str, Any]) -> dict[str, Any]:
    def pick(row, options):
        return min(options, key=lambda v: (_lead(options[v]) if _lead(options[v]) is not None else math.inf,
                                           options[v]['landed_unit_cost']))
    allocation = allocate(data, pick)
    if not any(a['supplier_id'] for a in allocation):
        return unavailable(data, 'fastest_delivery', 'Fastest delivery', 'minimize_lead_time',
                           'No eligible suppliers are available for award.')
    scenario = summarise(data, 'fastest_delivery', 'Fastest delivery', 'minimize_lead_time',
                         dict(BASE_CONSTRAINTS), allocation)
    if scenario['max_lead_time'] is None:
        scenario['notes'] = 'No supplier stated a lead time, so this ranks on landed cost alone.'
    return scenario


def single_supplier(data: dict[str, Any]) -> dict[str, Any]:
    rows = data.get('comparison') or []
    if not rows:
        return unavailable(data, 'single_supplier', 'Single supplier', 'single_supplier',
                           'No normalized responses to award.')
    covers: set[str] | None = None
    for row in rows:
        options = set(eligible(row))
        covers = options if covers is None else covers & options
    if not covers:
        return unavailable(data, 'single_supplier', 'Single supplier', 'single_supplier',
                           'Single-supplier award is not feasible: no eligible supplier covers every line.')
    totals = {vid: sum(row['vendors'][vid]['landed_unit_cost'] * (row.get('qty') or 0) for row in rows)
              for vid in covers}
    chosen = min(totals, key=lambda v: totals[v])
    allocation = allocate(data, lambda row, options: chosen)
    return summarise(data, 'single_supplier', 'Single supplier', 'single_supplier',
                     {**BASE_CONSTRAINTS, 'max_suppliers': 1}, allocation)


def defaults(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [lowest_cost(data), single_supplier(data), fastest_delivery(data)]


# ── Naming a saved run ───────────────────────────────────────────────────────

def _pct(value: float) -> str:
    return f'{round(value * 100)}%'


def title_for(data: dict[str, Any], result: dict[str, Any]) -> str:
    """A short name taken from what the run actually constrains.

    The buyer's sentence is kept as a note; it makes a poor card title, and the
    structured spec already says what the scenario is for — in any category.
    """
    spec = result.get('spec') or {}
    named = {vid: (vendor or {}).get('name') or vid for vid, vendor in (data.get('vendors') or {}).items()}
    mix = result.get('vendor_mix') or []
    parts: list[str] = []

    shares = spec.get('supplier_line_shares') or {}
    if shares:
        ordered = sorted(shares.items(), key=lambda kv: -kv[1])
        parts.append('/'.join(str(round(value * 100)) for _, value in ordered) + ' split · '
                     + ' + '.join(named.get(vid, vid) for vid, _ in ordered))
    elif spec.get('equal_split'):
        parts.append(f'Equal split across {len(mix)} suppliers' if mix else 'Equal split')
    if spec.get('max_supplier_spend_share'):
        parts.append(f"Max {_pct(spec['max_supplier_spend_share'])} per supplier")
    if spec.get('max_delivery_days'):
        parts.append(f"Lead time under {spec['max_delivery_days']} days")
    if spec.get('required_supplier_ids'):
        parts.append('Must include ' + ', '.join(named.get(v, v) for v in spec['required_supplier_ids']))
    if spec.get('excluded_supplier_ids'):
        parts.append('Without ' + ', '.join(named.get(v, v) for v in spec['excluded_supplier_ids']))
    if not spec.get('qualified_suppliers_only', True):
        parts.append('Unqualified suppliers included')
    if spec.get('missing_quote_policy') == 'allow_uncovered':
        parts.append('Partial coverage allowed')

    if not parts:
        if len(mix) == 1:
            parts.append(f"Whole event to {mix[0].get('vendor_name') or 'one supplier'}")
        else:
            parts.append('Cheapest qualified allocation')
    return ' · '.join(parts[:2])[:80]


# ── Scenarios saved out of the analysis room ─────────────────────────────────

def from_solver(data: dict[str, Any], result: dict[str, Any], name: str,
                source: str = 'analysis') -> dict[str, Any]:
    """Convert an optimizer run into an AwardScenario without recomputing a number."""
    spec = result.get('spec') or {}
    shares = {(data['vendors'].get(vid) or {}).get('name') or vid: value
              for vid, value in (spec.get('supplier_line_shares') or {}).items()}
    constraints = {'qualified_suppliers_only': bool(spec.get('qualified_suppliers_only', True)),
                   'complete_coverage_required': spec.get('missing_quote_policy', 'disallow') == 'disallow'}
    if spec.get('max_delivery_days'):
        constraints['max_lead_time_days'] = spec['max_delivery_days']
    if spec.get('max_supplier_spend_share'):
        constraints['max_supplier_share'] = spec['max_supplier_spend_share']
    if shares:
        constraints['supplier_shares'] = shares
    objective = 'custom' if (shares or spec.get('equal_split')) else 'minimize_cost'

    by_line = {row['line_no']: row for row in data.get('comparison') or []}
    reviews = open_reviews(data)
    allocation = []
    for entry in result.get('allocation') or []:
        line_no = entry['line_no']
        row = by_line.get(line_no) or {}
        quote = (row.get('vendors') or {}).get(entry['vendor_id']) or {}
        allocation.append({'line_item_id': line_no, 'sku': entry.get('sku'),
                           'description': entry.get('description') or row.get('description'),
                           'required_quantity': entry.get('line_qty', row.get('qty')),
                           'supplier_id': entry['vendor_id'], 'supplier_name': entry.get('vendor_name'),
                           'allocated_quantity': entry.get('qty'),
                           'normalized_unit_price': entry.get('landed_unit_cost'),
                           'line_total': entry.get('total_cost'),
                           'lead_time_days': _lead(quote),
                           'eligibility_status': _status(quote, entry['vendor_id'], line_no, reviews),
                           'evidence_id': entry.get('evidence_id')})
    covered = {a['line_item_id'] for a in allocation}
    for line_no in sorted(set(by_line) - covered):
        row = by_line[line_no]
        allocation.append({'line_item_id': line_no, 'sku': row.get('sku'), 'description': row.get('description'),
                           'required_quantity': row.get('qty'), 'supplier_id': None, 'supplier_name': None,
                           'allocated_quantity': 0, 'normalized_unit_price': None, 'line_total': 0.0,
                           'lead_time_days': None, 'eligibility_status': 'uncovered', 'evidence_id': None})
    allocation.sort(key=lambda a: (a['line_item_id'], a['supplier_name'] or ''))
    scenario = summarise(data, 'analysis', name, objective, constraints, allocation, source=source,
                         notes=(result.get('question') or '').strip()[:240])
    scenario['solver_scenario_id'] = result.get('id')
    scenario['dataset_version'] = result.get('dataset_version', data.get('dataset_version'))
    return scenario


# ── Why a supplier is not in the running ─────────────────────────────────────

def exclusions(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Reasons straight from the qualification and review engines, never invented here."""
    rows = data.get('comparison') or []
    out = []
    for vid, vendor in (data.get('vendors') or {}).items():
        if vendor.get('response_status') != 'processed':
            continue
        reasons: list[str] = []
        if vendor.get('quality') != 'pass':
            reasons.append(vendor.get('quality_reason')
                           or f"Mandatory qualification {vendor.get('quality') or 'not established'}")
        blocked = sum(1 for row in rows if (row.get('vendors') or {}).get(vid, {}).get('blocking_exception'))
        if blocked:
            reasons.append(f'{blocked} of {len(rows)} lines are held by an open review')
        unpriced = sum(1 for row in rows if not usable((row.get('vendors') or {}).get(vid) or {}))
        if unpriced and unpriced != blocked:
            reasons.append(f'No usable price on {unpriced} of {len(rows)} lines')
        if reasons:
            out.append({'supplier_id': vid, 'supplier_name': vendor.get('name'),
                        'qualification_status': vendor.get('quality'), 'reasons': reasons})
    return out


# ── Has the ground moved under a saved scenario? ─────────────────────────────

def fingerprint(data: dict[str, Any]) -> str:
    """Everything an allocation depends on, and nothing else."""
    facts = []
    for row in data.get('comparison') or []:
        quotes = sorted((vid, q.get('landed_unit_cost'), q.get('lead_days'), q.get('quote_status'),
                         q.get('qualification'), bool(q.get('blocking_exception')))
                        for vid, q in (row.get('vendors') or {}).items())
        facts.append([row['line_no'], row.get('qty'), quotes])
    return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ── Reading and writing the screen's state ───────────────────────────────────

def saved(data: dict[str, Any]) -> list[dict[str, Any]]:
    current = fingerprint(data)
    out = []
    for scenario in data.get('award_scenarios') or []:
        scenario = dict(scenario)
        scenario['stale'] = scenario.get('fingerprint') != current
        out.append(scenario)
    return out


def save(scenario: dict[str, Any]) -> dict[str, Any]:
    def mutate(d):
        kept = [s for s in (d.get('award_scenarios') or []) if s['id'] != scenario['id']]
        d['award_scenarios'] = kept + [scenario]
    repo.change('award_scenario_saved', 'buyer', mutate)
    return scenario


def remove(scenario_id: str) -> None:
    def mutate(d):
        d['award_scenarios'] = [s for s in (d.get('award_scenarios') or []) if s['id'] != scenario_id]
    repo.change('award_scenario_removed', 'buyer', mutate)


def find(data: dict[str, Any], key: str) -> dict[str, Any] | None:
    if key in DEFAULT_KEYS:
        return {'lowest_cost': lowest_cost, 'single_supplier': single_supplier,
                'fastest_delivery': fastest_delivery}[key](data)
    return next((s for s in saved(data) if s['id'] == key or s.get('key') == key), None)


def view(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data if data is not None else repo.read()
    rfx = data.get('rfx') or {}
    processed = [v for v in (data.get('vendors') or {}).values() if v.get('response_status') == 'processed']
    ready = bool(data.get('comparison')) and bool(processed)
    scenarios = (defaults(data) + saved(data)) if ready else []
    return {
        'ready': ready,
        'message': None if ready else 'Complete vendor response processing before creating an award.',
        'event': {'event_id': rfx.get('event_id'), 'title': rfx.get('title'),
                  'currency': rfx.get('currency') or 'INR', 'status': data.get('stage') or data.get('rfx_status'),
                  'line_item_count': len(rfx.get('items') or []), 'supplier_count': len(processed),
                  'dataset_version': data.get('dataset_version')},
        'scenarios': scenarios,
        'exclusions': exclusions(data) if ready else [],
        'award': data.get('award'),
        'fingerprint': fingerprint(data),
    }


def confirm(key: str, actor: str) -> dict[str, Any]:
    """Freeze a scenario into the Award. Refuses anything that no longer adds up."""
    data = repo.read()
    scenario = find(data, key)
    if not scenario:
        raise ValueError('That scenario is no longer available. Pick one from the award screen.')
    if scenario.get('status') != 'ok':
        raise ValueError(scenario.get('reason') or 'That scenario cannot be awarded.')
    if scenario.get('fingerprint') != fingerprint(data):
        raise ValueError('Scenario requires recalculation because sourcing data has changed.')
    awarded = [a for a in scenario['allocation'] if a['supplier_id']]
    coverage = scenario['coverage'] or {}
    award = {
        'id': f'AWD-{uuid4().hex[:10].upper()}',
        'event_id': scenario['event_id'],
        'scenario_id': scenario['id'],
        'scenario_name': scenario['name'],
        'status': 'selected',
        'total_value': scenario['total_value'],
        'currency': scenario['currency'],
        'supplier_ids': sorted({a['supplier_id'] for a in awarded}),
        'supplier_names': scenario['supplier_names'],
        'allocation': scenario['allocation'],
        'allocated_line_items': coverage.get('allocated_lines', len({a['line_item_id'] for a in awarded})),
        'total_line_items': coverage.get('total_lines', len({a['line_item_id'] for a in scenario['allocation']})),
        'max_lead_time': scenario['max_lead_time'],
        'confirmed_by': actor,
        'confirmed_at': _now(),
        'dataset_version': data.get('dataset_version'),
        'fingerprint': scenario['fingerprint'],
    }
    repo.change('award_selected', actor, lambda d: d.update(award=award))
    return award


def revoke(actor: str) -> None:
    repo.change('award_cleared', actor, lambda d: d.update(award=None))
