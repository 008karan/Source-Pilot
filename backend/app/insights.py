"""Evidence-derived supplier summaries. Missing performance is never fabricated."""
import json
import re
from . import dossier, knowledge, repository as repo
from .ai import has_ai, _structured_response

# Commercial facts the buyer asked about, wherever the supplier stated them.
TERM_KEYS = knowledge.TERM_KEYS
TERM_LABELS = knowledge.TERM_LABELS
FREIGHT_WORDS = knowledge.FREIGHT_WORDS
# Offer validity and stated lead time repeat what the table already shows, so the
# comparison leaves them out. They stay queryable in the analysis room.
COMPARISON_SKIP = {'validity', 'lead_time'}
# Where a duration decides who is stronger, the buyer wants the standing, not the prose.
GRADED = {'warranty': 'Warranty', 'payment': 'Payment terms'}
DURATION = re.compile(r'(\d+(?:\.\d+)?)\s*[-–]?\s*(years?|yrs?|months?|mos?|weeks?|days?)\b', re.I)
NET_DAYS = re.compile(r'\b(?:net|credit(?:\s+period)?)\s*[:\-]?\s*(\d{1,3})\b', re.I)

def duration_months(text, allow_net=False):
    """Months a stated period covers, or None when the supplier stated no period."""
    text = str(text or '')
    match = DURATION.search(text)
    if match:
        size, unit = float(match.group(1)), match.group(2).lower()
        if unit.startswith(('year', 'yr')):
            return size * 12
        if unit.startswith(('month', 'mo')):
            return size
        if unit.startswith('week'):
            return size / 4.345
        return size / 30.44
    if allow_net:
        net = NET_DAYS.search(text)
        if net:
            return float(net.group(1)) / 30.44
    return None

def durations_months(text, allow_net=False):
    """Every period a value states. A warranty is often quoted per SKU, not once."""
    found = []
    for size, unit in DURATION.findall(str(text or '')):
        size = float(size)
        unit = unit.lower()
        found.append(size * 12 if unit.startswith(('year', 'yr'))
                     else size if unit.startswith(('month', 'mo'))
                     else size / 4.345 if unit.startswith('week') else size / 30.44)
    if not found and allow_net:
        net = NET_DAYS.search(str(text or ''))
        if net:
            found.append(float(net.group(1)) / 30.44)
    return found

DAYS_PER_MONTH = 30.44

def _span(months):
    """Say it the way the supplier would: 45 days is not "1 month"."""
    if months >= 12 and abs(months / 12 - round(months / 12)) < .01:
        years = round(months / 12)
        return f"{years} year" + ('' if years == 1 else 's')
    if months >= 1.5:
        return f"{round(months)} month" + ('' if round(months) == 1 else 's')
    days = round(months * DAYS_PER_MONTH)
    return f"{days} day" + ('' if days == 1 else 's')

def _cover(periods):
    """How a set of quoted periods reads: one figure, or the range across the lines."""
    low, high = min(periods), max(periods)
    if low == high:
        return _span(low)
    if low >= 12 and all(abs(p / 12 - round(p / 12)) < .01 for p in (low, high)):
        return f'{round(low / 12)}\u2013{round(high / 12)} years'
    return f'{round(low)}\u2013{round(high)} months'

def grade_terms(suppliers):
    """Rank each supplier's cover against the others who answered, on the whole quote."""
    for key in GRADED:
        periods = {v['id']: durations_months((v['terms'].get(key) or {}).get('value'), allow_net=key == 'payment')
                   for v in suppliers if v['terms'].get(key)}
        # A warranty quoted per SKU is judged on the cover as a whole, not its first line.
        # Compared in whole days, so "1 month" and "30 days" rank as the same term.
        strength = {k: round(sum(v) / len(v) * DAYS_PER_MONTH) for k, v in periods.items() if v}
        for supplier in suppliers:
            cell = supplier['terms'].get(key)
            if not cell:
                continue
            quoted = periods.get(supplier['id']) or []
            if not quoted:
                cell['standing'] = 'Stated, no period given'
                continue
            cell['months'] = round(min(quoted), 2)
            cell['cover'] = _cover(quoted)
            mine = strength[supplier['id']]
            if len(strength) < 2 or max(strength.values()) == min(strength.values()):
                cell['standing'] = f'Matched · {cell["cover"]}'
                continue
            best, worst = max(strength.values()), min(strength.values())
            rank = 'Strongest' if mine == best else 'Weakest' if mine == worst else 'Middle'
            cell['standing'] = f'{rank} · {cell["cover"]}'
    return suppliers

_match = knowledge.term_kind

def supplier_terms(vendor, rfx):
    """Every answer and captured term the supplier actually stated, with its source."""
    found = {}
    def record(key, value, source, evidence_id):
        value = ' '.join(str(value).split())[:300]
        if key and value and key not in found:
            found[key] = {'value': value, 'source': source, 'evidence_id': evidence_id}
    questions = {q['id']: q for q in rfx.get('questionnaire', [])}
    for qid, answer in sorted((vendor.get('questionnaire') or {}).items()):
        record(knowledge.question_kind(questions.get(qid)), answer.get('answer'), f"Answer to {qid}",
               (answer.get('evidence') or {}).get('evidence_id'))
    for entry in (vendor.get('terms') or {}).get('captured', []):
        record(_match(entry.get('term_type')) or _match(entry.get('value')), entry.get('value'),
               'Stated in the response', vendor.get('terms_evidence_id'))
    freight = (vendor.get('terms') or {}).get('freight', 'unknown')
    if freight != 'unknown' or 'freight' not in found:
        detail = FREIGHT_WORDS.get(freight, freight)
        if freight == 'flat':
            detail += f" (INR {vendor['terms'].get('freight_per_piece_inr')}/unit)"
        elif freight == 'percent':
            detail += f" ({vendor['terms'].get('freight_percent', 0) * 100:g}% of material value)"
        override = (vendor.get('terms') or {}).get('freight_override')
        found['freight'] = {'value': detail, 'evidence_id': vendor.get('terms_evidence_id'),
                            'source': f"Buyer decision by {override['actor']}" if override else
                                      (f"Source: “{vendor['terms']['freight_source'][:120]}”" if vendor.get('terms', {}).get('freight_source') else 'Not stated in the response')}
    return found

def overview():
    d=repo.read();vendors=list(d['vendors'].values());rows=d['comparison']
    usable=lambda q:q.get('landed_unit_cost') is not None and not q.get('blocking_exception') and q.get('status')=='quoted'
    processed=[v for v in vendors if v['response_status']=='processed']
    qualified=[v for v in processed if v['quality']=='pass']
    # The like-for-like basket is set by the qualified suppliers, or by everyone who
    # responded while none is qualified yet. Any responder covering that basket is priced,
    # so a pending qualification never blanks the comparison.
    basket=qualified or processed
    common=[r for r in rows if basket and all(usable(r['vendors'].get(v['id'],{})) for v in basket)]
    result=[]
    for v in vendors:
        quotes=[r['vendors'][v['id']] for r in rows if v['id'] in r['vendors'] and usable(r['vendors'][v['id']])]
        leads=[q.get('lead_days') for q in quotes]
        covers=bool(common) and v in processed and all(usable(r['vendors'].get(v['id'],{})) for r in common)
        cost=sum(r['qty']*r['vendors'][v['id']]['landed_unit_cost'] for r in common) if covers else None
        common_leads=[r['vendors'][v['id']].get('lead_days') for r in common] if covers else []
        result.append({'id':v['id'],'name':v['name'],'quality':v['quality'],'processed':v['response_status']=='processed','coverage':len(quotes),'total_lines':len(d['rfx']['items']),'cost':round(cost,2) if cost is not None else None,'delivery':max(common_leads) if common_leads and all(x is not None for x in common_leads) else None,'reviews':sum(e['vendor_id']==v['id'] and e['status']!='resolved_by_buyer' for e in d['exceptions']),'past_deals':None,'terms':supplier_terms(v,d['rfx'])})
    leaders={};best_overall={}
    passing={v['id'] for v in qualified}
    for key,direction in [('cost','min'),('delivery','min'),('coverage','max')]:
        # Only a qualified supplier can lead, but the best number in the row is always
        # named, so the table never shows a lower figure without saying whose it is.
        pick=lambda values:(min(values) if direction=='min' else max(values)) if values else None
        usable=[x for x in result if x[key] is not None and x['processed'] and (key!='coverage' or x[key]>0)]
        best=pick([x[key] for x in usable if x['id'] in passing])
        leaders[key]=[x['id'] for x in usable if x[key]==best and best is not None and x['id'] in passing]
        overall=pick([x[key] for x in usable])
        # Only worth naming when it actually beats the qualified leader.
        beats=overall is not None and (best is None or (overall<best if direction=='min' else overall>best))
        best_overall[key]=[x['id'] for x in usable if x[key]==overall and beats]
    leaders['quality']=[x['id'] for x in result if x['quality']=='pass']
    grade_terms(result)
    term_rows=[{'key':k,'label':TERM_LABELS[k],'graded':k in GRADED}
               for k in TERM_KEYS if k not in COMPARISON_SKIP and any(x['terms'].get(k) for x in result)]
    return {'dataset_version':d['dataset_version'],'suppliers':result,'leaders':leaders,'best_overall':best_overall,'term_rows':term_rows,'questions':[{'id':q['id'],'question':q['question'],'mandatory':q['mandatory']} for q in d['rfx'].get('questionnaire',[])],'common_lines':len(common),'total_lines':len(d['rfx']['items']),'note':'Cost and speed use the same lines quoted by every supplier who responded; not a full-event award unless all lines are covered. Qualification reflects declarations, not independent quality scores. No previous-deal records are connected.'}

def interpret(question,graph_schema,history=None):
    """Turn the question into a query: which suppliers, which dimensions, which view."""
    if not has_ai():return None
    keys=[d['key'] for d in graph_schema['dimensions']]
    ids=[s['id'] for s in graph_schema['suppliers']]
    schema={'type':'object','additionalProperties':False,'properties':{
        'intent':{'type':'string','enum':['compare','award','unsupported']},
        'suppliers':{'type':'array','items':{'type':'string','enum':ids}},
        'dimensions':{'type':'array','items':{'type':'string','enum':keys}},
        'requirements':{'type':'array','items':{'type':'integer','minimum':1}},
        'breakdown':{'type':'string','enum':['supplier','requirement','allocation']},
        'scenarios':{'type':'array','maxItems':4,'items':{'type':'object','additionalProperties':False,'properties':{
            'label':{'type':'string'},
            'required_supplier_ids':{'type':'array','items':{'type':'string','enum':ids}},
            'excluded_supplier_ids':{'type':'array','items':{'type':'string','enum':ids}},
            'qualified_suppliers_only':{'type':'boolean'},
            'max_supplier_spend_share':{'anyOf':[{'type':'number','minimum':0.01,'maximum':1},{'type':'null'}]},
            'max_delivery_days':{'anyOf':[{'type':'integer','minimum':1},{'type':'null'}]},
            'allocation_granularity':{'type':'string','enum':['line_item','quantity']},
            'equal_split':{'type':'boolean'},
            'supplier_line_shares':{'type':'array','items':{'type':'object','additionalProperties':False,'properties':{
                'supplier_id':{'type':'string','enum':ids},
                'share':{'type':'number','exclusiveMinimum':0,'maximum':1}},'required':['supplier_id','share']}}},
            'required':['label','required_supplier_ids','excluded_supplier_ids','qualified_suppliers_only','max_supplier_spend_share','max_delivery_days','allocation_granularity','equal_split','supplier_line_shares']}},
        'view':{'type':'string','enum':['matrix','bar','cards','pie']},
        'headline':{'type':'string'},
        'reason':{'type':'string'}},
        'required':['intent','suppliers','dimensions','requirements','breakdown','scenarios','view','headline','reason']}
    try:
        return _structured_response(
            'You turn a procurement buyer\'s question into a query over this sourcing event. '
            'intent "compare" whenever the buyer wants to know who is better, cheaper, faster, more complete, more '
            'trustworthy, or what suppliers stated. intent "award" only when they ask to allocate, split, exclude or '
            'constrain an award, or state a numeric award limit; an optimizer handles those. intent "unsupported" only '
            'when no listed dimension can answer it, and say why in reason. '
            'suppliers: the supplier ids the buyer named, matching loosely on name; empty means every supplier. '
            'dimensions: the fewest that answer the question, and nothing else. A question about price, cost, a quote, '
            'value or who is cheaper is ["cost"] alone. A question about one stated term is that term alone. '
            'The words "overall", "total" and "for the whole requirement" describe how much of the requirement is in '
            'scope, not how many factors to compare: "the overall better quote for the whole requirement" is still '
            '["cost"]. Use several dimensions only when the buyer names more than one factor themselves, or asks to '
            'compare everything, all criteria, or every factor. '
            'requirements: line numbers only when the buyer names specific lines. '
            'breakdown "requirement" whenever the buyer wants the answer per SKU, per line, per item or line-wise '
            '— for example "SKU-wise cost per vendor" or "which supplier is cheapest for each item". '
            'breakdown "allocation" with intent "award" when the buyer asks which lines, SKUs or items an award would '
            'give to which supplier, who wins what under a split, or for a cost breakdown of an award. '
            'Otherwise "supplier", one figure per supplier. '
            'view "matrix" for more than one dimension, "bar" for a single number across suppliers, "cards" for a '
            'single stated term, "pie" only when a pie chart is requested. '
            'scenarios: when the buyer asks what an award would cost under two or more strategies — everything to one '
            'supplier, a split between named suppliers, a cap, a delivery limit — return one entry per strategy with a '
            'short label. Award everything to one supplier by putting every other supplier in excluded_supplier_ids. '
            'For a split between named suppliers, exclude the suppliers not named and leave required empty so the '
            'optimizer picks the cheapest of them per line. Set qualified_suppliers_only false when the buyer names a '
            'supplier who has not qualified, or asks to include every supplier. '
            'allocation_granularity "quantity" whenever a line\'s quantity is to be divided between suppliers — an '
            'even split, a percentage of each SKU, or dual sourcing within a line; "line_item" when each line goes '
            'wholly to one supplier. equal_split true only when every eligible supplier takes the SAME share of every line, such as "25% '
            'each to four vendors"; the optimizer derives that share. '
            'supplier_line_shares when the buyer gives particular percentages per supplier, such as "60% to QuickDeal '
            'and 40% to GlobalSource on every SKU": one entry per named supplier, share as a fraction, adding up to 1 '
            'when the buyer has divided the whole order. Use it with allocation_granularity "quantity" and leave '
            'equal_split false. A named supplier is included even if their qualification is pending. '
            'Every strategy the buyer asks to compare is its own entry in scenarios, including the one they describe '
            'first. Leave scenarios empty for any question that is not about an award. '
            'conversation_so_far lists earlier turns of this same conversation, oldest first, each with the question '
            'and what was answered. Resolve every reference against it: "that split", "those two", "it", "the cheaper '
            'one", or a bare follow-up such as "which SKUs go to each". When the buyer follows up on a scenario you '
            'already ran, restate that same scenario rather than inventing a new one. '
            'headline: at most eight words naming what is compared. reason: at most fifteen words. '
            'Never write an explanation or a recommendation; the table carries the detail.',
            json.dumps({'question':question,'available':graph_schema,'conversation_so_far':history or []}),
            'analysis_query',schema)
    except Exception:
        return None

def from_knowledge_base(question,history=None):
    """Answer in prose from the Markdown dossiers, quoting only what they contain."""
    if not has_ai():return None
    schema={'type':'object','additionalProperties':False,'properties':{
        'answer':{'type':'string'},
        'sources':{'type':'array','items':{'type':'string'}},
        'answered':{'type':'boolean'}},'required':['answer','sources','answered']}
    try:
        result=_structured_response(
            'You answer a procurement buyer from the knowledge base below, which is the complete record of this '
            'sourcing event: one Markdown document per supplier plus the requirement. Use only what these documents '
            'state. Never calculate a new total, share or ranking — those come from the optimizer, not from you; if '
            'the question needs one, set answered false. At most 45 words, plain language, no preamble. '
            'sources: the document names you used. answered false when the documents do not contain the answer.',
            json.dumps({'question':question,'conversation_so_far':history or [],
                        'knowledge_base':dossier.corpus()}),'knowledge_answer',schema)
    except Exception:
        return None
    if not result.get('answered') or not result.get('answer'):return None
    return {'kind':'text','title':'From the supplier documents','text':intake_brief(result['answer']),
            'sources':result.get('sources') or [],'dataset_version':repo.read()['dataset_version']}

def intake_brief(text,limit=45):
    words=str(text or '').split()
    return ' '.join(words) if len(words)<=limit else ' '.join(words[:limit])+'\u2026'

def chart(question,history=None):
    """Route factual comparisons, not award constraints. Unknown factors stay unknown."""
    q=question.lower()
    if any(x in q for x in ['previous','past deal','history of','experience','reliability','performance','defect','rating']):
        return {'kind':'text','title':'No past-performance records','text':'No order history or ratings are connected. Compare qualification, coverage or lead time instead.'}
    data=overview()
    if not data['suppliers']:return None
    graph=knowledge.build()
    available=knowledge.schema(graph)
    routed=interpret(question,available,history)
    if routed:
        if routed['intent']=='award':
            entries=routed.get('scenarios') or []
            if routed.get('breakdown')=='allocation':
                return {'kind':'allocation_request','scenarios':entries,'headline':routed['headline']}
            # Whatever the router worked out is the spec; never re-derive it elsewhere.
            return {'kind':'scenario_request','scenarios':entries,'headline':routed['headline']} if entries else None
        if routed['intent']=='unsupported':
            return from_knowledge_base(question,history) or {'kind':'text','title':'Not available for this event',
                    'text':routed['reason'].rstrip('.')+'. Try: '+', '.join(d.get('short') or d['label'].lower() for d in available['dimensions'][:6])+'.'}
        query={k:routed[k] for k in ('suppliers','dimensions','requirements')}
        if routed.get('breakdown')=='requirement':
            result=knowledge.by_line(query)
            if not result['rows']:return {'kind':'text','title':'No requirement lines to break down','text':'This event has no lines with comparable prices yet.'}
            return {'kind':'matrix','title':routed['headline'] or 'Cost by requirement line',
                    'text':knowledge.line_verdict(result),'dataset_version':result['dataset_version'],**result}
        result=knowledge.compare(query)
        # The chart shortcut reads whole-event aggregates, so it cannot honour a line filter.
        if len(result['rows'])==1 and routed['view'] in ('bar','cards','pie') and not routed.get('requirements'):
            single=result['rows'][0]['key']
            if single in ('cost','delivery','coverage','reviews') or single=='qualification':
                return render({'cost':'cost','delivery':'delivery','coverage':'coverage','reviews':'reviews','qualification':'quality'}[single],
                              routed['view'],data,question,[s['id'].split(':',1)[1] for s in result['suppliers']])
            if single.startswith('term:'):
                return render(single.split(':',1)[1],'cards',data,question,[s['id'].split(':',1)[1] for s in result['suppliers']])
        return {'kind':'matrix','title':routed['headline'] or 'Supplier comparison','text':knowledge.verdict(result),
                'dataset_version':result['dataset_version'],**result}
    constrained=bool(re.search(r'\d+\s*(?:%|days)|\b(?:award|allocate|allocation|split|exclude|require)\b',q))
    term=next((key for key,words in TERM_KEYS.items() if any(w in q for w in words)),None)
    if term and not constrained and term!='lead_time':
        return {'kind':'facts','title':TERM_LABELS[term],'metric':term,
                'text':'Each supplier’s own words. Blank means not stated.',
                'points':[{'label':v['name'],'value':(v['terms'].get(term) or {}).get('value','Not stated'),
                           'note':(v['terms'].get(term) or {}).get('source',''),
                           'evidence_id':(v['terms'].get(term) or {}).get('evidence_id')} for v in data['suppliers']],
                'dataset_version':data['dataset_version']}
    metric='quality' if any(x in q for x in ['quality','qualification','certif']) else 'delivery' if any(x in q for x in ['delivery','speed','lead time','fastest']) else 'coverage' if any(x in q for x in ['coverage','complete','missing']) else 'cost' if any(x in q for x in ['cost','price','quote','spend','cheap','expensive','value for money','budget']) else None
    compare=any(x in q for x in ['chart','graph','compare','comparison','bar','pie','show','which','who','best','better','cheapest','quality','qualification','coverage'])
    if constrained or not compare:return None
    if metric is None:return {'kind':'text','title':'Which comparison would help?','text':'Ask for cost, lead time, qualification or coverage.'}
    return render(metric,'pie' if 'pie' in q else 'bar',data,question)

def render(metric,chart_kind,data,question,only=None):
    """One renderer for every dimension, whichever way the question was understood."""
    values=[v for v in data['suppliers'] if not only or v['id'] in only] or data['suppliers']
    if metric in TERM_LABELS:
        return {'kind':'facts','title':TERM_LABELS[metric],'metric':metric,
                'text':'Each supplier’s own words. Blank means not stated.',
                'points':[{'label':v['name'],'value':(v['terms'].get(metric) or {}).get('value','Not stated'),
                           'note':(v['terms'].get(metric) or {}).get('source',''),
                           'evidence_id':(v['terms'].get(metric) or {}).get('evidence_id')} for v in values],
                'dataset_version':data['dataset_version']}
    q=question.lower()
    if metric=='quality':
        return {'kind':'status','title':'Supplier qualification','text':'Declared outcomes, not quality ratings. Pending suppliers are excluded from qualified-only awards.','points':[{'label':v['name'],'status':v['quality']} for v in values],'dataset_version':data['dataset_version']}
    titles={'cost':'Quoted cost on comparable lines','delivery':'Slowest quoted lead time on comparable lines','coverage':'Usable quote coverage','reviews':'Open buyer reviews'}
    unit={'cost':'INR','delivery':'days','coverage':'lines','reviews':'open'}[metric]
    return {'kind':'bar','title':titles[metric],'metric':metric,'unit':unit,'points':[{'label':v['name'],'value':v[metric],'leading':v['id'] in data['leaders'][metric]} for v in values],'text':(f"{data['common_lines']} of {data['total_lines']} lines compared." if metric in {'cost','delivery'} else f"Out of {data['total_lines']} requirement lines.")+(' Bars compare independent values more clearly than a pie.' if 'pie' in q else ' Missing stays unknown, not zero.'),'dataset_version':data['dataset_version']}
