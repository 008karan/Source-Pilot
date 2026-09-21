from __future__ import annotations
from typing import TypedDict
from uuid import uuid4
import threading
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from langgraph.checkpoint.sqlite import SqliteSaver
from . import repository as repo
from .pipeline import ingest

DRIVE_LOCK=threading.RLock()
class WorkflowState(TypedDict, total=False):
    event_id: str
    stage: str
    use_ai: bool
    dataset_version: int
    job_id: str

def approval(state):
    answer=interrupt({'type':'rfx_approval','message':'Review the RFx and approve simulated release.'})
    if not answer.get('approved'):
        return Command(goto='approval',update={'stage':'rfx_review'})
    def mutate(d):
        if d.get('draft'):
            d['rfx']['scope']=d['draft']['scope']
            d['rfx']['commercial_rules']['quote_validity_days']=d['draft']['commercial_terms']['quote_validity_days']
        d.update(rfx_status='approved',stage='collecting_responses',approved_by=answer.get('actor','buyer'),approved_at=repo.now())
    data=repo.change('rfx_approved_simulated_dispatch',answer.get('actor','buyer'),mutate)
    return Command(goto='dispatch',update={'stage':'collecting_responses','dataset_version':data['dataset_version']})

def dispatch(state):
    return {'stage':'collecting_responses'}

def await_intake(state):
    interrupt({'type':'response_collection','message':'Receive vendor messages and attachments, then start extraction.'})
    return {'stage':'processing_responses'}

def gate(state):
    d=repo.read()
    pending=[e['id'] for e in d['exceptions'] if e['status']!='resolved_by_buyer']
    return Command(goto='review' if pending else 'ready',update={'stage':'exception_review' if pending else 'ready_for_analysis','dataset_version':d['dataset_version']})

def review(state):
    d=repo.read()
    interrupt({'type':'exception_review','exception_ids':[e['id'] for e in d['exceptions'] if e['status']!='resolved_by_buyer']})
    return Command(goto='gate')

def ready(state):
    d=repo.change('workflow_ready','workflow',lambda d:d.update(stage='ready_for_analysis'))
    return {'stage':'ready_for_analysis','dataset_version':d['dataset_version']}

def build_workflow(checkpointer):
    graph=StateGraph(WorkflowState)
    graph.add_node('approval',approval);graph.add_node('dispatch',dispatch)
    graph.add_node('await_intake',await_intake);graph.add_edge('dispatch','await_intake')
    names=[]
    for vid in repo.read()['vendors']:
        name='ingest_'+vid;names.append(name)
        def intake(state, vendor=vid):
            from .pipeline import ingest_received
            ingest_received(vendor,use_ai=state.get('use_ai',True),job_id=state.get('job_id'))
            return {}
        graph.add_node(name,intake);graph.add_edge('await_intake',name)
    graph.add_node('gate',gate);graph.add_node('review',review);graph.add_node('ready',ready)
    graph.add_edge(START,'approval')
    if names:graph.add_edge(names,'gate')
    else:graph.add_edge('await_intake','gate')
    graph.add_edge('ready',END)
    return graph.compile(checkpointer=checkpointer)

def run(action, approved=False, actor='buyer', use_ai=True, job_id=None):
    with DRIVE_LOCK:
        d=repo.read();wid=d.get('workflow_id')
        if action=='start':
            if wid:raise ValueError('A workflow already exists. Resume its current review step.')
            wid=str(uuid4())
            repo.change('workflow_started',actor,lambda d:d.update(workflow_id=wid,stage='rfx_review'))
        elif not wid:raise ValueError('Start the RFx review workflow first.')
        config={'configurable':{'thread_id':wid}}
        with SqliteSaver.from_conn_string(str(repo.runtime_dir()/'workflow.sqlite')) as saver:
            graph=build_workflow(saver)
            if action=='start':graph.invoke({'event_id':d['rfx']['event_id'],'stage':'rfx_review','use_ai':use_ai},config)
            elif action=='resume':
                snapshot=graph.get_state(config)
                if not snapshot.next:raise ValueError('Workflow is already complete.')
                graph.invoke(Command(resume={'approved':approved,'actor':actor}),config)
            elif action=='retry':graph.invoke(None,config)
            elif action=='process':
                if repo.read()['rfx_status']!='approved':raise ValueError('Approve the RFx first.')
                graph.update_state(config,{'job_id':job_id,'stage':'processing_responses'},as_node='await_intake')
                graph.invoke(None,config)
            snapshot=graph.get_state(config)
            return {'id':wid,'state':snapshot.values,'next':list(snapshot.next),'interrupts':[i.value for t in snapshot.tasks for i in t.interrupts]}

def status():
    d=repo.read()
    if not d.get('workflow_id'):return {'id':None,'state':{'stage':d['stage']},'next':[],'interrupts':[]}
    return run('status')
