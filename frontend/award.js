/* Award Selection — the last step: pick the allocation that becomes the award.
   No chat, no comparison matrix, no optimizer controls. Every number here was
   calculated on the server from reviewed data; this file only shows it. */
let awardData=null,awardChoice=null;

const AWARD_STATUS={eligible:'Eligible',needs_review:'Needs review',not_eligible:'Not eligible',uncovered:'Uncovered'};
const qty=n=>n==null?'—':Number(n).toLocaleString('en-IN');
const leadLabel=d=>d==null?'—':`${d} day${d===1?'':'s'}`;
const awardCurrency=()=>awardData?.event?.currency||'INR';
const sum=(n,digits=2)=>n==null?'—':new Intl.NumberFormat('en-IN',{style:'currency',currency:awardCurrency(),maximumFractionDigits:digits}).format(n);

function awardScenario(){
 const all=awardData?.scenarios||[];
 return all.find(s=>s.id===awardChoice)||all.find(s=>s.status==='ok')||all[0]||null;
}

function awardCard(s,active){
 const unavailable=s.status!=='ok';
 const lines=unavailable
   ? `<p class="card-reason">${esc(s.reason||'Not available')}</p>`
   : `<strong>${sum(s.total_value)}</strong>
      <p>${s.supplier_count} supplier${s.supplier_count===1?'':'s'}${s.supplier_count===1&&s.supplier_names[0]?' · '+esc(s.supplier_names[0]):''}</p>
      <p>${leadLabel(s.max_lead_time)} max lead time</p>
      ${s.coverage&&s.coverage.allocated_lines<s.coverage.total_lines?`<p class="card-warn">${s.coverage.total_lines-s.coverage.allocated_lines} line(s) uncovered</p>`:''}
      ${s.stale?'<p class="card-warn">Needs recalculation</p>':''}`;
 // The remove control is a sibling, never nested: a button inside a button does not parse.
 return `<div class="award-card-wrap">
   <button class="award-card${active?' active':''}${unavailable?' unavailable':''}" data-action="awardPick" data-key="${esc(s.id)}"${unavailable?' disabled':''}>
     <span class="eyebrow">${esc(s.source==='analysis'?'From analysis':'Scenario')}</span>
     <h3>${esc(s.name)}</h3>${lines}</button>
   ${s.source==='analysis'?`<button class="card-remove" data-action="awardForget" data-key="${esc(s.id)}" title="Remove this saved scenario" aria-label="Remove ${esc(s.name)}">×</button>`:''}
  </div>`;
}

function awardKpis(s){
 const c=s.coverage||{};
 const covered=c.required_quantity?Math.round(c.allocated_quantity/c.required_quantity*100):0;
 const tiles=[['Total award value',sum(s.total_value),esc(s.currency)],
   ['Suppliers',String(s.supplier_count),s.supplier_names.slice(0,2).map(esc).join(', ')+(s.supplier_names.length>2?` +${s.supplier_names.length-2}`:'')],
   ['Max lead time',leadLabel(s.max_lead_time),'Longest quoted line'],
   ['Coverage',`${c.allocated_lines}/${c.total_lines} lines`,`${covered}% of required quantity`]];
 if(s.qualification_status)tiles.push(['Qualification',s.qualification_status==='all_qualified'?'All qualified':'Review required','Mandatory requirements']);
 return `<div class="award-kpis">${tiles.map(([label,value,note])=>`<div class="award-kpi"><label>${label}</label><strong>${value}</strong><small>${note||'&nbsp;'}</small></div>`).join('')}</div>`;
}

function awardTable(s){
 return `<div class="table-wrap"><table class="award-table"><thead><tr><th>Line</th><th>Item</th><th>Required</th><th>Supplier</th><th>Allocated</th><th>Unit price</th><th>Award value</th><th>Lead time</th><th>Status</th></tr></thead><tbody>
  ${s.allocation.map(a=>`<tr class="row-${esc(a.eligibility_status)}"><td>${a.line_item_id}</td>
    <td>${a.sku?`<b>${esc(a.sku)}</b>`:''}<small>${esc(a.description||'')}</small></td>
    <td>${qty(a.required_quantity)}</td>
    <td>${a.supplier_name?esc(a.supplier_name):'<span class="muted-inline">No eligible supplier</span>'}</td>
    <td>${qty(a.allocated_quantity)}</td>
    <td>${sum(a.normalized_unit_price)}</td>
    <td>${a.supplier_id?sum(a.line_total):'—'}</td>
    <td>${leadLabel(a.lead_time_days)}</td>
    <td><span class="award-status ${esc(a.eligibility_status)}">${AWARD_STATUS[a.eligibility_status]||esc(a.eligibility_status)}</span></td></tr>`).join('')}
 </tbody></table></div>`;
}

function awardWhy(s){
 const excluded=awardData?.exclusions||[];
 return `<div class="award-why"><div>
   <div class="chat-label">APPLIED RULES</div>
   <ul class="rule-list">${s.rules.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>
   ${s.notes?`<p class="muted">${esc(s.notes)}</p>`:''}
   ${(s.advisories||[]).length?`<div class="chat-label award-sub">NOTED ON AWARDED SUPPLIERS</div><ul class="exclusion-list">${s.advisories.map(a=>`<li><b>${esc(a.supplier_name)}</b><span>${esc(a.title)} — ${esc(a.detail||'')}</span></li>`).join('')}</ul>`:''}
  </div>${excluded.length?`<div>
   <div class="chat-label">EXCLUDED OR RESTRICTED</div>
   <ul class="exclusion-list">${excluded.map(e=>`<li><b>${esc(e.supplier_name)}</b>${e.reasons.map(r=>`<span>${esc(r)}</span>`).join('')}</li>`).join('')}</ul>
  </div>`:''}</div>`;
}

function awardConfirmedPanel(a){
 const bySupplier=new Map();
 (a.allocation||[]).filter(x=>x.supplier_id).forEach(x=>{
  const row=bySupplier.get(x.supplier_id)||{name:x.supplier_name,value:0,lines:new Set(),lead:null};
  row.value+=x.line_total||0;row.lines.add(x.line_item_id);
  if(x.lead_time_days!=null)row.lead=Math.max(row.lead??0,x.lead_time_days);
  bySupplier.set(x.supplier_id,row)});
 const suppliers=[...bySupplier.values()].sort((p,q)=>q.value-p.value);
 const total=a.total_value||0;
 const when=new Date(a.confirmed_at);
 const stamp=isNaN(when)?'':when.toLocaleString('en-IN',{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'});
 return `<section class="award-result">
  <header class="award-banner">
   <span class="award-seal">${AGENT_MARK}</span>
   <div class="award-banner-text">
    <div class="eyebrow">AWARD SELECTED</div>
    <h2>${esc(a.scenario_name)}</h2>
    <p>${esc(a.id)}${stamp?' · '+esc(stamp):''}${a.confirmed_by?' · by '+esc(a.confirmed_by):''}</p>
   </div>
   <div class="award-banner-total"><small>Total award value</small><b>${sum(a.total_value)}</b></div>
  </header>

  <div class="award-figures">
   <div><small>Suppliers</small><b>${a.supplier_ids.length}</b></div>
   <div><small>Lines allocated</small><b>${a.allocated_line_items} / ${a.total_line_items}</b></div>
   <div><small>Max lead time</small><b>${leadLabel(a.max_lead_time)}</b></div>
   <div><small>Status</small><b class="award-state">${esc(String(a.status).replace(/_/g,' '))}</b></div>
  </div>

  <div class="award-panel">
   <h3>Who won what</h3>
   <div class="award-split">${suppliers.map((s,n)=>{
     const share=total?s.value/total:0;
     return `<div class="split-row">
      <div class="split-head"><b>${esc(s.name)}</b><span>${sum(s.value)}</span></div>
      <div class="split-track"><i style="width:${Math.max(2,share*100)}%;background:${colors[n%colors.length]}"></i></div>
      <div class="split-foot"><span>${(share*100).toFixed(1)}% of award</span><span>${s.lines.size} line${s.lines.size===1?'':'s'}${s.lead!=null?' · '+leadLabel(s.lead):''}</span></div>
     </div>`}).join('')}</div>
  </div>

  <div class="award-panel">
   <h3>Awarded lines</h3>
   ${awardTable({allocation:a.allocation})}
  </div>

  <footer class="award-foot">
   <p>This award is recorded against the event. It does not raise a purchase order or notify any supplier.</p>
   ${button('Change the award','awardClear')}
  </footer>
 </section>`;
}

function renderAward(){
 const view=$('#view-award');if(!view)return;
 if(!awardData){view.innerHTML=hero('05 / AWARD THE BUSINESS','Choose the final allocation.','Loading the award scenarios…');return}
 const e=awardData.event;
 const meta=`${e.line_item_count} item${e.line_item_count===1?'':'s'} · ${e.supplier_count} supplier${e.supplier_count===1?'':'s'}${e.status?' · '+String(e.status).replace(/_/g,' '):''}`;
 const head=hero('05 / AWARD THE BUSINESS','Award Selection',`${esc(e.title||'Sourcing event')}${e.event_id?' · '+esc(e.event_id):''} — ${meta}`);
 if(!awardData.ready){view.innerHTML=head+`<div class="panel"><p>${esc(awardData.message||'Not ready yet.')}</p>${button('Back to responses','nextView','data-to="responses"','primary')}</div>`;return}
 if(awardData.award){view.innerHTML=head+awardConfirmedPanel(awardData.award);return}
 const s=awardScenario();
 if(!s){view.innerHTML=head+'<div class="panel"><p>No eligible suppliers are available for award.</p></div>';return}
 const ok=s.status==='ok';
 view.innerHTML=head+`<div class="award-cards">${awardData.scenarios.map(x=>awardCard(x,x.id===s.id)).join('')}</div>`
  +`<div class="panel"><div class="panel-head"><div><h2>${esc(s.name)}</h2><p>${ok?'Selected scenario · every figure calculated from your reviewed data':esc(s.reason||'')}</p></div></div>`
  +(ok?awardKpis(s)+`<h3 class="award-section">Award allocation</h3>`+awardTable(s)
      +`<h3 class="award-section">Why this scenario</h3>`+awardWhy(s)
      +`<div class="award-actions">${s.stale?'<p class="card-warn">Scenario requires recalculation because sourcing data has changed.</p>':button('Select this award →','awardSelect',`data-key="${esc(s.id)}"`,'primary')}</div>`
    :'')+`</div>`;
}

async function loadAward(){try{awardData=await api('/api/award');renderAward()}catch(e){toast(e.message,true)}}

const AWARD_ACTIONS=['awardPick','awardSelect','awardDo','awardClear','awardForget','saveToAward','closeDrawer'];
// Capture phase: the page-wide handler in app.js wraps EVERY data-action button in
// busy(), which blanks the button to "Working…" — on a scenario card that means
// wiping the card and rebuilding it. Claiming the event here keeps that off them.
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action]');if(!b)return;
 const action=b.dataset.action;
 if(!AWARD_ACTIONS.includes(action))return;
 e.stopPropagation();e.preventDefault();
 // Choosing a scenario is local state: render it now, do not wait on anything.
 if(action==='awardPick'){awardChoice=b.dataset.key;renderAward();return}
 if(action==='closeDrawer'){closeDrawer();return}
 await busy(b,async()=>{
  if(action==='awardForget'){await fetch('/api/award/scenarios/'+encodeURIComponent(b.dataset.key),{method:'DELETE'});if(awardChoice===b.dataset.key)awardChoice=null;await loadAward();toast('Saved scenario removed.');return}
  if(action==='awardClear'){await api('/api/award/clear',{});await loadAward();toast('Award cleared. Choose again.');return}
  if(action==='awardSelect'){
   const s=awardScenario();if(!s)return;
   const c=s.coverage||{};
   openDrawer(`<div class="eyebrow">CONFIRM AWARD</div><h2>${esc(s.name)}</h2>
    <div class="confirm-facts">
     <div><label>Total award value</label><strong>${sum(s.total_value)} ${esc(s.currency)}</strong></div>
     <div><label>Suppliers</label><strong>${s.supplier_count}</strong><small>${s.supplier_names.map(esc).join(', ')}</small></div>
     <div><label>Line items allocated</label><strong>${c.allocated_lines} / ${c.total_lines}</strong></div>
     <div><label>Max lead time</label><strong>${leadLabel(s.max_lead_time)}</strong></div>
    </div>
    ${s.uncovered_lines.length?`<p class="card-warn">Uncovered lines: ${s.uncovered_lines.join(', ')}</p>`:''}
    <label class="field">Your name<input id="awardActor" value="${esc(state.rfx.buyer||'')}"></label>
    <div class="actions">${button('Cancel','closeDrawer')}${button('Confirm award','awardDo',`data-key="${esc(s.id)}"`,'primary')}</div>`);
   return}
  if(action==='awardDo'){
   await api('/api/award/confirm',{scenario:b.dataset.key,actor:$('#awardActor')?.value||''});
   closeDrawer();await loadAward();go('award');toast('Award selected.');return}
  if(action==='saveToAward'){
   await api('/api/award/scenarios',{scenario_id:b.dataset.scenario});
   await loadAward();toast('Scenario saved to Award Selection.');return}
 })},true);
