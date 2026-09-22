/* Buyer-focused intake, criteria overview and visual answers. */
let visualAnswer=null,preferredChart='bar',pendingIntakeFiles=[],analysisThread=[],analysisTurns=[],liveAnswer=null;
// A re-render must not replay the entrance; only messages past this mark animate.
let seenIntake=0;
const newSessionId=()=>'chat-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,8);
let analysisSession=sessionStorage.getItem('aerchain-chat')||newSessionId();
sessionStorage.setItem('aerchain-chat',analysisSession);
const INTAKE_ACCEPT='.xlsx,.csv,.pdf,.docx,.txt,.eml';
const attachmentChip=(name,href)=>href?`<a class="attachment-chip" href="${href}" target="_blank" rel="noopener">▧ ${esc(name)} ↗</a>`:`<span class="attachment-chip">▧ ${esc(name)}</span>`;
function renderTray(){const tray=$('#intakeTray');if(!tray)return;tray.hidden=!pendingIntakeFiles.length;tray.innerHTML=pendingIntakeFiles.map((f,n)=>`<span class="attachment-chip">▧ ${esc(f.name)}<button type="button" data-action="removeIntakeFile" data-index="${n}" aria-label="Remove ${esc(f.name)}">×</button></span>`).join('')}
const navigateWorkspace=go;
go=function(view){closeDrawer();navigateWorkspace(view)};
renderRfx=function(){
 const i=intakeData||{checklist:[],messages:[],items:[],missing:[],fields:{}},released=state.rfx_status==='approved';
 const complete=i.checklist.filter(c=>c.complete).length+(i.items.length?1:0),total=i.checklist.length+1;
 seenIntake=Math.min(seenIntake,i.messages.length);
 $('#view-rfx').innerHTML=hero('01 / BUILD THE RIGHT REQUEST','What do you need to buy?','A conversation that turns your requirement into a complete, buyer-confirmed RFx.')+`<div class="intake-layout"><div class="chat-workspace"><div class="chat-stream intake-stream">${!i.messages.length?`<div class="welcome-card"><div class="welcome-symbol">${AGENT_MARK}</div><h3>Start with your requirement.</h3><div class="suggestions">${button('Use packaging example','intakeDemo','','suggestion')}</div></div>`:i.messages.map((m,n)=>`<div class="${m.role==='user'?'user-message':'intake-assistant'}${n>=seenIntake?' just-arrived':''}">${m.role==='assistant'?agentHead('RFx co-pilot'):''}<p>${esc(m.text)}</p>${(m.attachments||[]).map(a=>attachmentChip(a.filename,'/api/intake/documents/'+a.index)).join('')}</div>`).join('')}${released?`<div class="success-note">✓ RFx approved${i.shared?' and sharing step completed':''}.</div>${i.dispatch?dispatchHtml(i.dispatch):'<p>Your existing event is preserved. Continue to supplier proposals.</p>'}${next('Collect the original proposals next.','Open responses →','responses')}`:''}${released?'':i.confirmed?`<div class="intake-assistant agent-offer just-arrived">${agentHead('RFx co-pilot')}<p>Ready when you are — I'll search the supplier directory and map this requirement.</p><div class="offer-actions">${button('Yes, find suppliers & share →','intakeShare','','primary')}</div><p class="fine-print">Demo sharing only. No external email is sent.</p></div>`:!i.missing.length&&i.messages.length?`<div class="intake-assistant agent-offer just-arrived">${agentHead('RFx co-pilot')}<p>That's everything on the checklist. Look it over — once you confirm, I'll take it to suppliers.</p><div class="offer-actions">${button('Review & confirm details →','reviewChecklist','','primary')}</div></div>`:''}</div>${released?'':`<div class="composer"><textarea id="rfxChat" aria-label="Describe your sourcing requirement" placeholder="For example: We need 120 ergonomic chairs delivered to our Bengaluru office by 15 November… — or attach your requirement sheet"></textarea><div class="attachment-tray" id="intakeTray" hidden></div><div class="composer-toolbar"><label class="attach-button" title="Attach a requirement sheet, RFQ document or specification">▧ <span>Attach</span><input id="intakeFiles" type="file" multiple accept="${INTAKE_ACCEPT}" aria-label="Attach requirement documents"></label>${mic('rfxChat')}<span>${health.ai_configured?'Enter to send · Shift+Enter for a new line':'Offline: attached sheets map to the checklist · Enter to send'}</span>${button('Send ↑','intakeChat','','primary')}</div></div>`}</div><aside class="intake-checklist"><div class="checklist-head"><div class="chat-label">YOUR RFx CHECKLIST</div>${button('Start fresh','newRequest','','small-button')}</div><h3>${complete} of ${total} essentials captured</h3><div class="check-progress"><i style="width:${total?complete/total*100:0}%"></i></div><p class="muted">Captured does not mean confirmed. Review the details before sharing.</p>${i.checklist.map(c=>`<details class="check-item"><summary><span class="check-dot ${c.complete?'complete':''}">${c.complete?'✓':'○'}</span>${esc(c.label)}</summary><p>${esc(c.value||c.ask||c.question)}</p></details>`).join('')}<details class="check-item"><summary><span class="check-dot ${i.items.length?'complete':''}">${i.items.length?'✓':'○'}</span>Items, quantities & units</summary>${i.items.map(x=>`<p>${x.sku?'<b>'+esc(x.sku)+'</b> · ':''}${esc(x.description)} · ${esc(x.quantity)} ${esc(x.unit)}${x.unit_weight_kg?' · '+esc(x.unit_weight_kg)+' kg/unit':''}${x.term_months?' · '+esc(x.term_months)+'-month term':''}</p>`).join('')||'<p>Add at least one line with quantity and unit.</p>'}</details>${!released?`<div class="check-actions">${button('Edit checklist & lines','intakeEdit')}${button(i.confirmed?'Confirmed ✓':'Review & confirm all details','intakeConfirm',i.missing.length?'disabled':'','primary')}</div>`:''}<p class="fine-print">The intake works across categories. The current award engine compares landed INR rates; unsupported units and missing qualification evidence stay blocked.</p></aside></div>`;
 // A new turn pulls the thread to the newest message; an ordinary re-render does not
 // yank the view out from under someone reading further up.
 if(i.messages.length>seenIntake){const s=$('.intake-stream');if(s)s.scrollTop=s.scrollHeight}
 seenIntake=i.messages.length;
 renderTray();
};
function dispatchHtml(d){return `<div class="dispatch-card"><div class="chat-label">${d.simulated?'SIMULATED SUPPLIER MATCHING & SHARING':'SUPPLIER MAPPING'}</div><div class="dispatch-stages"><span>✓ Directory checked</span><span>✓ ${d.suppliers.length} matches</span><span>✓ ${d.suppliers.length?'Demo sharing complete':'Ready for manual proposals'}</span></div>${d.suppliers.map(s=>`<div class="mapped-supplier"><b>${esc(s.name)}</b><small>${esc(s.reason)}</small><span class="pill pass">Demo shared</span></div>`).join('')}<p>${esc(d.message)}</p></div>`}
function editIntake(){const i=intakeData;openDrawer(`<div class="eyebrow">REVIEW YOUR RFx</div><h2>Everything suppliers need to quote.</h2><p>Enter “not applicable” only when appropriate. Each answer is retained in the approved brief.</p><form id="intakeEditForm">${i.checklist.map(c=>`<label class="field">${esc(c.label)}<textarea name="${c.id}" required placeholder="${esc(c.ask||c.question)}">${esc(c.value)}</textarea></label>`).join('')}<h3>Requirement lines</h3><p>Description, quantity and the purchasing unit. Add one row per distinct requirement.</p><div id="intakeLines">${(i.items.length?i.items:[{description:'',quantity:1,unit:'piece'}]).map(itemEditor).join('')}</div>${button('+ Add requirement line','addIntakeLine')}<div class="actions"><button class="primary" type="submit">Save checklist</button></div></form>`)}
function itemEditor(x){return `<div class="item-editor"><label>SKU<input data-item="sku" placeholder="Optional" value="${esc(x.sku??'')}"></label><label>Description<input data-item="description" required value="${esc(x.description)}"></label><label>Quantity<input data-item="quantity" type="number" min="0.000001" step="any" required value="${esc(x.quantity)}"></label><label>Unit<input data-item="unit" required value="${esc(x.unit)}"></label><label>Unit weight (kg)<input data-item="unit_weight_kg" type="number" min="0.000001" step="any" placeholder="Optional" value="${esc(x.unit_weight_kg??'')}"></label><label>Term (months)<input data-item="term_months" type="number" min="0.000001" step="any" placeholder="Rental / subscription" value="${esc(x.term_months??'')}"></label><button type="button" data-action="removeIntakeLine" aria-label="Remove requirement line">×</button></div>`}
const supplierResponses=renderResponses;
renderResponses=function(){supplierResponses();const root=$('#view-responses');
 // The demo offers are five packaging quotes for the 30-line example; they cannot be
 // applied to any other event, so the control is offered only where it can work.
 const demoEvent=!!intakeData?.demo_offers,released=state.rfx_status==='approved';
 root.querySelector('.section-hero p').textContent=demoEvent?'Load the five demo offers, or add a proposal from any supplier. Receive first, then extract.':'Add a proposal from any supplier. Receive first, then extract.';
 root.querySelector('.section-hero').insertAdjacentHTML('beforeend',button('+ Add supplier proposal','newProposal',released?'':'disabled title="Approve and share your RFx first."','primary'));
 const load=root.querySelector('[data-action="demoMessages"]');
 if(!demoEvent)load.remove();
 else{load.disabled=!released;if(!released)load.title='Approve and share your RFx first.'}
 const extract=root.querySelector('[data-action="processAll"]');
 if(extract)extract.textContent='Extract information →';};
function newProposal(){openDrawer(`<div class="eyebrow">ADD A SUPPLIER PROPOSAL</div><h2>The original offer, in their own words.</h2><p>Add as many suppliers as you need. Their proposal joins the same evidence and review workflow.</p><form id="proposalForm"><label class="field">Supplier name<input name="supplier_name" maxlength="160" required placeholder="Supplier company name"></label><label class="field">Email ID<input name="email" type="email" required placeholder="quotes@supplier.com"></label><label class="field">Subject<input name="subject" value="Supplier proposal"></label><label class="field">Message body<textarea name="body" rows="7" placeholder="Paste the supplier’s email, including prices, delivery, freight and qualification answers…"></textarea></label><label class="drop-zone">Attachments<input name="files" type="file" multiple accept=".xlsx,.docx,.pdf,.eml,.txt,.jpg,.jpeg,.png,.webp"><span>Up to 5 files · 12 MB each · 24 MB total. A message or attachment is required.</span></label><div class="actions"><button class="secondary" type="submit" value="save">Add to inbox</button><button class="primary" type="submit" value="extract">Add & extract information →</button></div><p class="fine-print">Live interpretation sends proposal content to the configured AI service. Nothing is emailed to the supplier.</p></form>`)}
function criteriaTable(){const o=overviewData;if(!o?.suppliers.length)return '<div class="panel"><h3>Your comparison will appear here.</h3><p>Add supplier proposals and extract their information first.</p></div>';const rows=[['cost','Best comparable quote','Same lines, every response · green marks a qualified leader',v=>v.cost==null?'Not comparable':money(v.cost)],['delivery','Fastest comparable delivery','Slowest line lead time · lower is better',v=>v.delivery==null?'Not available':v.delivery+' days'],['quality','Meets mandatory requirements','Declared qualification · gates the award, not the price',v=>v.processed?({pass:'Meets requirements',pending:'Needs review',fail:'Does not qualify'}[v.quality]):'Not extracted'],['coverage','Most complete usable offer','Usable prices · higher is better',v=>v.processed?`${v.coverage} / ${v.total_lines} lines`:'Not extracted'],['past_deals','Previous-deal performance','Past quality and delivery reliability',()=> 'No records connected']];
 const termRows=(o.term_rows||[]).map(r=>[r.key,r.label,r.graded?'Ranked against the other responses':'Stated by the supplier in their own response',
   v=>(v.terms?.[r.key]?.standing)||(v.terms?.[r.key]?.value)||'Not stated']);return `<section class="panel criteria-overview"><div class="panel-head"><div><div class="chat-label">AT A GLANCE</div><h2>Who leads, for what?</h2><p>Different priorities, different strengths. Green marks the best qualified supplier; a better number from a supplier who has not qualified is named beside it.</p></div></div><div class="table-wrap"><table class="criteria-table"><thead><tr><th>Your priority</th>${o.suppliers.map(v=>`<th>${esc(v.name)}</th>`).join('')}</tr></thead><tbody>${rows.map(([key,title,note,fmt])=>`<tr><th>${title}<small>${note}</small></th>${o.suppliers.map(v=>{const leads=o.leaders[key]?.includes(v.id),best=o.best_overall?.[key]?.includes(v.id);return `<td class="${leads?'criteria-leader':''}">${leads?'<span class="leader-label">✓ Best qualified</span>':best?'<span class="leader-note">Best overall · '+esc(v.quality==='pending'?'qualification pending':'does not qualify')+'</span>':''}${esc(fmt(v))}</td>`}).join('')}</tr>`).join('')}${termRows.map(([key,title,note,fmt])=>`<tr><th>${title}<small>${note}</small></th>${o.suppliers.map(v=>{const cell=v.terms?.[key];const strong=cell?.standing?.startsWith('Strongest');return `<td class="${strong?'criteria-leader':''}" ${cell?.value?`title="${esc(cell.value)}"`:''}>${strong?'<span class="leader-label">✓ Strongest</span>':''}${esc(fmt(v))}${cell?.source?`<small>${esc(cell.source)}</small>`:''}</td>`}).join('')}</tr>`).join('')}</tbody></table></div>${o.questions?.length?`<details class="criteria-questions"><summary>The ${o.questions.length} questions this RFx asked suppliers</summary>${o.questions.map(q=>`<p><b>${esc(q.id)}</b> ${esc(q.question)}${q.mandatory?' <span class="pill">Mandatory</span>':''}</p>`).join('')}</details>`:''}<p class="fine-print">${esc(o.note)} Cost and speed currently share ${o.common_lines} of ${o.total_lines} lines. Green is a criterion-specific result, not an overall recommendation.</p><div class="suggestions">${button('Visualize costs ↗','compareVisual','data-question="Show a bar chart comparing supplier cost"','suggestion')}${button('Compare delivery ↗','compareVisual','data-question="Compare supplier delivery lead time"','suggestion')}${button('Explore a balanced award ↗','compareVisual','data-question="Qualified only, no supplier above 45% of award spend"','suggestion')}${button('Compare payment terms ↗','compareVisual','data-question="Compare supplier payment terms"','suggestion')}${button('Compare warranty ↗','compareVisual','data-question="Compare supplier warranty and service level"','suggestion')}</div></section>`}
const detailedCompare=renderCompare;
// <details> cannot transition display, so the height is animated by hand.
function animateDetails(details){
 if(details.dataset.eased)return;details.dataset.eased='1';
 const summary=details.querySelector(':scope > summary');if(!summary)return;
 const wrap=document.createElement('div');wrap.className='details-body';
 [...details.children].filter(n=>n!==summary).forEach(n=>wrap.append(n));
 details.append(wrap);
 summary.addEventListener('click',event=>{
  event.preventDefault();
  if(details.dataset.busy)return;details.dataset.busy='1';
  const finish=()=>{details.dataset.busy='';wrap.style.transition=''};
  wrap.style.transition='height .34s cubic-bezier(.3,.9,.3,1),opacity .26s ease';
  if(details.open){
   wrap.style.height=wrap.scrollHeight+'px';wrap.style.opacity='1';
   requestAnimationFrame(()=>{wrap.style.height='0px';wrap.style.opacity='0'});
   setTimeout(()=>{details.open=false;wrap.style.height='';wrap.style.opacity='';finish()},340);
  }else{
   details.open=true;wrap.style.height='0px';wrap.style.opacity='0';
   requestAnimationFrame(()=>{wrap.style.height=wrap.scrollHeight+'px';wrap.style.opacity='1'});
   setTimeout(()=>{wrap.style.height='auto';finish()},340);
  }
 });
}
renderCompare=function(){
 if(!state.comparison?.length){
  $('#view-compare').innerHTML=hero('03 / REVIEW WITH CONFIDENCE','Know what you can trust.',
   'Every supplier price gets one comparable basis, with its source one click away.')+waitingFor('compare');
  return}
 detailedCompare();const root=$('#view-compare');root.querySelector('.section-hero').insertAdjacentHTML('afterend',criteriaTable());const layout=root.querySelector('.compare-layout');const table=layout?.querySelector(':scope > .panel');if(table){const details=document.createElement('details');details.className='normalized-details';details.innerHTML='<summary>Explore detailed normalized prices & source evidence</summary>';table.before(details);details.append(table);animateDetails(details)}};
const analysisBase=renderAnalysis;
renderAnalysis=function(){
 if(!state.comparison?.length){
  $('#view-analysis').innerHTML=hero('04 / FIND YOUR AWARD','Ask the next “what if”.',
   'Explore supplier splits, delivery limits and cost, once there is reviewed data to ask about.')+waitingFor('analysis');
  return}
 analysisBase();if(visualAnswer)renderVisual(visualAnswer);};
const scenarioBase=renderScenario;
renderScenario=function(s){visualAnswer=null;scenarioBase(s);const root=$('#scenarioResult');if(s.status!=='ok')return;const table=root.querySelector('.table-wrap');if(table){const detail=document.createElement('details');detail.className='allocation-details';detail.innerHTML='<summary>Inspect line-level allocations and evidence</summary>';table.before(detail);detail.append(table)}const mix=root.querySelector('.mix-row');if(mix){mix.insertAdjacentHTML('beforebegin',`<div class="chart-heading"><h3>Award spend by supplier</h3><div class="chart-toggle">${button('Bars','awardChart',`data-chart="bar" data-scenario="${s.id}"`,'small-button'+(preferredChart!=='pie'?' active':''))}${button('Pie','awardChart',`data-chart="pie" data-scenario="${s.id}"`,'small-button'+(preferredChart==='pie'?' active':''))}</div></div><div class="award-chart">${awardChart(s,preferredChart)}</div>`);root.querySelectorAll('.mix-row').forEach(x=>x.remove())}const label=root.querySelector('.panel-head p');if(label){label.textContent=`Data v${s.dataset_version} · ${s.stale?'Needs recomputing':'Current'} · Calculated award`;label.title='The immutable snapshot of your reviewed data this award was calculated from'};root.querySelectorAll('.allocation-details').forEach(animateDetails)};
const colors=['#6d78d8','#7bc7ab','#f0ba78','#ad94d3','#82bed4','#cc8f9d'];
function bars(points,unit){const numbers=points.filter(p=>p.value!=null),max=Math.max(0,...numbers.map(p=>p.value));return `<div class="visual-bars" role="group" aria-label="${esc(unit)} comparison">${points.map((p,n)=>`<div class="visual-bar-row"><div><span>${esc(p.label)}</span><b>${p.value==null?'Not available':unit==='INR'?money(p.value):esc(p.value)+' '+esc(unit)}</b></div><div class="visual-track"><i style="width:${p.value==null||!max?0:Math.max(1,p.value/max*100)}%;background:${p.leading?'#83cbae':colors[n%colors.length]}"></i></div></div>`).join('')}</div>`}
function awardChart(s,type){const points=s.vendor_mix.map(m=>({label:m.vendor_name,value:m.spend}));if(type!=='pie')return bars(points,'INR');let angle=0;const slices=s.vendor_mix.map((m,n)=>{const start=angle;angle+=m.spend/s.award_total_inr*360;return `${colors[n%colors.length]} ${start}deg ${angle}deg`});return `<div class="pie-layout"><div class="pie-chart" role="img" aria-label="Award spend shares" style="background:conic-gradient(${slices.join(',')})"><div><b>${money(s.award_total_inr)}</b><small>Total award</small></div></div><div class="chart-legend">${s.vendor_mix.map((m,n)=>`<p><i style="background:${colors[n%colors.length]}"></i><span>${esc(m.vendor_name)}<small>${money(m.spend)}</small></span><b>${(m.spend/s.award_total_inr*100).toFixed(1)}%</b></p>`).join('')}</div></div>`}
function scenariosHtml(a){
 const points=a.runs.filter(r=>r.award_total_inr!=null).map(r=>({label:r.label,value:r.award_total_inr,leading:r.label===a.best}));
 return (points.length?bars(points,'INR'):'')+`<div class="fact-cards">${a.runs.map(r=>`<div class="fact-card ${r.label===a.best?'criteria-leader':''}"><b>${esc(r.label)}</b><p>${r.award_total_inr!=null?money(r.award_total_inr):esc(r.reason||'No feasible award')}</p>${(r.supplier_mix||[]).map(m=>`<small>${esc(m.name)} · ${(m.share*100).toFixed(0)}% of spend · ${m.lines} line${m.lines===1?'':'s'}</small>`).join('')}${r.allocation?.length?`<details class="allocation-details"><summary>Line by line</summary><div class="table-wrap"><table><thead><tr><th>SKU</th><th>Supplier</th><th>Share</th><th>Units</th><th>Cost</th></tr></thead><tbody>${r.allocation.map(a=>`<tr><td>${esc(a.sku)}</td><td>${esc(a.supplier)}</td><td>${(a.share*100).toFixed(0)}%</td><td>${a.units.toLocaleString('en-IN')}</td><td>${money(a.cost)}</td></tr>`).join('')}</tbody></table></div></details>`:''}${r.uncovered?.length?`<small>Uncovered lines: ${r.uncovered.join(', ')}</small>`:''}${r.status==='ok'&&r.scenario_id?saveToAward(r.scenario_id):''}</div>`).join('')}</div><p class="fine-print">Each strategy solved by the same optimizer on data v${a.dataset_version}. Uncertain prices stay out.</p>`}
// An allocation answers three things: who is in, what each one gets, what it costs.
// Those lead; the line-by-line table sits behind a drawer.
function allocationSummary(a){
 const mix=a.vendor_mix||[];
 if(!mix.length||a.award_total_inr==null)return '';
 const pie=preferredChart==='pie';
 const slices=(()=>{let angle=0;return mix.map((m,n)=>{const start=angle;angle+=(m.share||0)*360;
   return `${colors[n%colors.length]} ${start}deg ${angle}deg`})})();
 const chart=pie
  ? `<div class="pie-layout"><div class="pie-chart" role="img" aria-label="Share of award by supplier"
      style="background:conic-gradient(${slices.join(',')})"><div><b>${mix.length}</b><small>suppliers</small></div></div>
     <div class="chart-legend">${mix.map((m,n)=>`<p><i style="background:${colors[n%colors.length]}"></i><span>${esc(m.vendor_name)}<small>${m.lines} line${m.lines===1?'':'s'}</small></span><b>${((m.share||0)*100).toFixed(1)}%</b></p>`).join('')}</div></div>`
  : `<div class="alloc-bars">${mix.map((m,n)=>`<div class="alloc-bar">
      <div class="alloc-bar-head"><b>${esc(m.vendor_name)}</b><span>${money(m.spend)}</span></div>
      <div class="split-track"><i style="width:${Math.max(2,(m.share||0)*100)}%;background:${colors[n%colors.length]}"></i></div>
      <div class="split-foot"><span>${((m.share||0)*100).toFixed(1)}% of award</span><span>${m.lines} line${m.lines===1?'':'s'}</span></div>
     </div>`).join('')}</div>`;
 return `<div class="alloc-summary">
   <div class="alloc-total"><small>Total award value</small><b>${money(a.award_total_inr)}</b>
    <span>${mix.length} supplier${mix.length===1?'':'s'} · ${a.compared_lines?.length||0} of ${a.total_lines} lines${a.savings_pct!=null?` · ${a.savings_pct.toFixed(1)}% under baseline`:''}</span></div>
   <div class="chart-heading"><h3>What each supplier gets</h3><div class="chart-toggle">${button('Bars','allocChart','data-chart="bar"','small-button'+(pie?'':' active'))}${button('Share','allocChart','data-chart="pie"','small-button'+(pie?' active':''))}</div></div>
   <div class="alloc-chart">${chart}</div>
   ${a.uncovered?.length?`<p class="card-warn">Not covered by any eligible supplier: line ${a.uncovered.join(', ')}</p>`:''}
  </div>`;
}
function matrixHtml(a){
 const best=(row,id)=>row.winners.includes(id)&&row.winners.length<a.suppliers.length;
 const bar=(row,cell)=>{if(row.kind!=='number')return '';const nums=a.suppliers.map(s=>row.cells[s.id]?.numeric).filter(n=>n!=null);if(!nums.length||cell.numeric==null)return '';
  const max=Math.max(...nums),min=Math.min(...nums),span=max-min;
  const share=span?(row.better==='low'?(max-cell.numeric)/span:(cell.numeric-min)/span):1;
  return `<div class="matrix-track"><i style="width:${Math.max(6,share*100)}%"></i></div>`};
 const long=a.rows.length>5;
 const lead=a.axis==='allocation'?allocationSummary(a):'';
 const body=`<div class="table-wrap"><table class="matrix-table"><thead><tr><th>Dimension</th>${a.suppliers.map(s=>`<th>${esc(s.name)}<small>${esc(s.qualification==='pass'?'Qualified':s.qualification==='pending'?'Qualification pending':'Does not qualify')}</small></th>`).join('')}</tr></thead><tbody>${a.rows.map(row=>`<tr><th>${esc(row.label)}<small>${esc(row.note||'')}</small></th>${a.suppliers.map(s=>{const cell=row.cells[s.id]||{};return `<td class="${best(row,s.id)?'criteria-leader':''}">${best(row,s.id)?'<span class="leader-label">✓ Leads</span>':''}${esc(cell.display??'—')}${bar(row,cell)}${cell.detail?`<small>${esc(cell.detail)}</small>`:''}${cell.source?`<small>${esc(cell.source)}</small>`:''}${cell.evidence_id?button('Source ↗','evidence',`data-id="${cell.evidence_id}"`,'small-button'):''}</td>`}).join('')}</tr>`).join('')}</tbody></table></div><p class="fine-print">${a.compared_lines.length} of ${a.total_lines} lines · data v${a.dataset_version} · ✓ marks the ${a.axis==='allocation'?'supplier awarded that line':a.axis==='requirement'?(a.metric==='cost'?'cheapest supplier on that line':'fastest supplier on that line'):'better value in that row'}.</p>`;
 // Where the money sits by line, for whoever opens the detail.
 const spend=(a.line_spend||[]).slice(0,10);
 const peak=Math.max(0,...spend.map(x=>x.spend));
 const byLine=spend.length>1?`<div class="line-spend"><h4>Largest lines by award value</h4>${spend.map((x,n)=>
   `<div class="line-spend-row"><div><span>${esc(x.sku||('Line '+x.line_no))}</span><b>${money(x.spend)}</b></div>
    <div class="split-track"><i style="width:${peak?Math.max(2,x.spend/peak*100):0}%;background:${colors[n%colors.length]}"></i></div></div>`).join('')}
   ${(a.line_spend||[]).length>spend.length?`<p class="fine-print">Top ${spend.length} of ${a.line_spend.length} lines.</p>`:''}</div>`:'';
 if(!long)return lead+body;
 return lead+`<details class="matrix-details"><summary>${a.axis==='allocation'?'See the line-by-line allocation':'See the full '+a.rows.length+'-row comparison'}`
  +`<span>${a.rows.length} lines · ${a.suppliers.length} supplier${a.suppliers.length===1?'':'s'}</span></summary>${byLine}${body}</details>`}
// Only when the answer carries a solved allocation — never on prose.
// The server names it from the constraints it actually solved; a question is a poor title.
const saveToAward=scenarioId=>scenarioId
 ? `<div class="save-award">${button('Save to Award','saveToAward',`data-scenario="${esc(scenarioId)}"`)}<small>Keeps this allocation as a scenario on the Award screen.</small></div>`
 : '';
function renderVisual(answer){const root=$('#scenarioResult');root.classList.add('show');root.innerHTML=(answer.question?`<div class="user-message">${esc(answer.question)}</div>`:'')+`<div class="panel"><div class="chat-label" title="The immutable snapshot of your reviewed data this answer was calculated from">✦ EVIDENCE-BASED COMPARISON${answer.dataset_version?' · DATA v'+answer.dataset_version:''}</div><h2>${esc(answer.title)}</h2><p>${esc(answer.text)}</p>${answer.kind==='bar'?bars(answer.points,answer.unit):answer.kind==='status'?`<div class="qualification-cards">${answer.points.map(p=>`<div><b>${esc(p.label)}</b>${pill(p.status)}</div>`).join('')}</div>`:answer.kind==='scenarios'?scenariosHtml(answer):answer.kind==='matrix'?matrixHtml(answer):answer.kind==='facts'?`<div class="fact-cards">${answer.points.map(p=>`<div class="fact-card"><b>${esc(p.label)}</b><p>${esc(p.value)}</p>${p.note?`<small>${esc(p.note)}</small>`:''}${p.evidence_id?button('Source ↗','evidence',`data-id="${p.evidence_id}"`,'small-button'):''}</div>`).join('')}</div>`:''}${answer.awardable&&answer.scenario_id?saveToAward(answer.scenario_id):''}</div>`;root.querySelectorAll('.matrix-details,.allocation-details').forEach(animateDetails)}
function keepAnswer(){const answered=$('#scenarioResult')?.innerHTML;
 if(answered&&liveAnswer){analysisThread.push(answered);
  // A chart answer never triggers a full re-render, so the thread grows in place.
  $('#analysisThread')?.insertAdjacentHTML('beforeend',`<div class="thread-entry">${answered}</div>`)}
 liveAnswer=null}
function summarise(a){
 const cut=t=>String(t||'').slice(0,320);
 if(a.kind==='scenarios')return cut('Compared award strategies — '+a.runs.map(r=>`${r.label}: ${r.award_total_inr!=null?money(r.award_total_inr):r.status}`).join('; ')+'. '+a.text);
 if(a.kind==='matrix')return cut(`${a.title} (${a.axis||'supplier'} view, suppliers: ${a.suppliers.map(s=>s.name).join(', ')}). ${a.text}`);
 if(a.kind==='award')return cut(`Award ${a.scenario.award_total_inr!=null?money(a.scenario.award_total_inr):a.scenario.status} to ${(a.scenario.vendor_mix||[]).map(m=>m.vendor_name).join(', ')}.`);
 if(a.points)return cut(`${a.title}: `+a.points.map(p=>`${p.label} ${p.value!=null?p.value:p.status||''}`).join('; '));
 return cut(`${a.title}. ${a.text||''}`)}
async function askVisually(question){if(!question.trim())throw Error('Enter a question first.');
 keepAnswer();
 $('#question').value='';
 $('#scenarioResult').classList.add('show');$('#scenarioResult').innerHTML=`<div class="user-message just-arrived">${esc(question)}</div>`+agentThinking('Checking the evidence…');
 $('.analysis-conversation')?.scrollTo({top:1e6,behavior:'smooth'});
 try{const answer=await api('/api/analysis',{question,session_id:analysisSession,history:analysisTurns.slice(-6)});
  liveAnswer=question;
  analysisTurns.push({question,summary:summarise(answer)});
  if(answer.kind==='award'){visualAnswer=null;preferredChart=answer.chart;selected=answer.scenario.id;askedQuestion=question;await refresh()}
  else{visualAnswer={...answer,question};selected=null;renderVisual(visualAnswer)}
  $('.analysis-conversation')?.scrollTo({top:1e6,behavior:'smooth'})}
 catch(e){liveAnswer=null;$('#scenarioResult').innerHTML=`<div class="panel"><h3>We couldn’t complete that request.</h3><p>${esc(e.message)}</p></div>`;throw e}}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-action]');if(!b)return;const action=b.dataset.action;const actions=['newRequest','confirmNewRequest','intakeDemo','intakeChat','intakeEdit','intakeConfirm','reviewChecklist','intakeShare','addIntakeLine','removeIntakeLine','removeIntakeFile','newProposal','compareVisual','askNew','askSuggestion','awardChart','allocChart','newChat'];if(!actions.includes(action))return;e.stopImmediatePropagation();e.preventDefault();await busy(b,async()=>{
 if(action==='newRequest'){openDrawer(`<h2>Start fresh?</h2><p>Clears the checklist, requirement lines and supplier inbox. Nothing is deleted — this event stays in version history.</p>${button('Yes, start fresh','confirmNewRequest','','primary')}`);return}
 if(action==='confirmNewRequest'){await api('/api/intake/new',{});visualAnswer=null;selected=null;activeJob=null;pendingIntakeFiles=[];sessionStorage.removeItem('aerchain-job');closeDrawer();await refresh();go('rfx');toast('Fresh request started.');return}
 if(action==='intakeDemo'){await api('/api/intake/start',{mode:'demo'});await refresh();return}
 if(action==='removeIntakeFile'){pendingIntakeFiles.splice(Number(b.dataset.index),1);renderTray();return}
 if(action==='intakeChat'){const prompt=$('#rfxChat').value.trim();
  const stream=$('.intake-stream');
  if(stream&&(prompt||pendingIntakeFiles.length)){
   $('#rfxChat').value='';
   stream.insertAdjacentHTML('beforeend',`<div class="user-message just-arrived"><p>${esc(prompt||'Sending '+pendingIntakeFiles.length+' attachment'+(pendingIntakeFiles.length===1?'':'s')+'…')}</p></div>`+agentThinking(pendingIntakeFiles.length?'Reading your attachment…':'Thinking…'));
   seenIntake++;
   stream.scrollTo({top:stream.scrollHeight,behavior:'smooth'})}
  try{
  if(pendingIntakeFiles.length){const data=new FormData();data.append('prompt',prompt);pendingIntakeFiles.forEach(f=>data.append('files',f));toast('Reading your attachment and mapping it to the checklist…');const r=await fetch('/api/intake/attach',{method:'POST',body:data});const result=await r.json();if(!r.ok)throw Error(typeof result.detail==='string'?result.detail:'Check the attached files');pendingIntakeFiles=[]}
  else{if(!prompt)throw Error('Describe your requirement, answer the follow-up question, or attach a requirement sheet.');await api('/api/intake/chat',{prompt})}
  }catch(error){$('#rfxChat').value=prompt;await refresh();throw error}
  await refresh();$('.intake-stream')?.scrollTo({top:1e6,behavior:'smooth'});return}
 if(action==='intakeEdit')return editIntake();
 if(action==='addIntakeLine')return $('#intakeLines').insertAdjacentHTML('beforeend',itemEditor({description:'',quantity:1,unit:'piece'}));
 if(action==='removeIntakeLine')return b.closest('.item-editor').remove();
 if(action==='reviewChecklist'){
  // Land the buyer on the confirm control itself, with the checklist in front of them.
  const panel=$('.intake-checklist'),target=panel?.querySelector('[data-action="intakeConfirm"]');
  if(!target)return;
  if(panel.scrollHeight>panel.clientHeight+2){
   const delta=target.getBoundingClientRect().bottom-panel.getBoundingClientRect().bottom+20;
   panel.scrollTop=Math.max(0,panel.scrollTop+delta);
  }else target.scrollIntoView({behavior:'smooth',block:'center'});
  setTimeout(()=>{
   target.classList.add('pulse-focus');
   try{target.focus({preventScroll:true})}catch(e){target.focus()}
   setTimeout(()=>target.classList.remove('pulse-focus'),1900);
  },420);
  return}
 if(action==='intakeConfirm'){openDrawer(`<h2>Confirm this requirement?</h2><p>Review the checklist and requirement lines. Sharing will use these exact answers.</p>${intakeData.checklist.map(c=>`<h3>${esc(c.label)}</h3><p>${esc(c.value)}</p>`).join('')}<h3>Requirement lines</h3>${intakeData.items.map(x=>`<p>${esc(x.description)} · ${x.quantity} ${esc(x.unit)}</p>`).join('')}<form id="confirmIntakeForm"><label><input type="checkbox" required> I have reviewed and confirm these details.</label><p><button class="primary" type="submit">Confirm requirement</button></p></form>`);return}
 if(action==='intakeShare'){
  const steps=[['Reading your category and requirement lines',420],
               ['Searching the supplier directory',900],
               ['Matching capability against each line',900],
               ['Checking who can quote the full scope',760],
               ['Preparing the request to share',520]];
  openDrawer(`<div class="dispatch-progress"><div class="dispatch-head"><span class="reading-orb spinning">${AGENT_MARK}</span><div><div class="eyebrow">FINDING SUPPLIERS</div><h2>Matching your requirement</h2></div></div><ol class="dispatch-steps">${steps.map(([label],n)=>`<li id="dstep${n}"><i></i><span>${esc(label)}</span></li>`).join('')}</ol><p class="fine-print">A simulated dispatch against the local directory. No external email is sent.</p></div>`);
  // The steps are the real sequence; they run while the request is in flight.
  let cancelled=false;
  const walk=async()=>{for(let n=0;n<steps.length&&!cancelled;n++){
    $('#dstep'+n)?.classList.add('active');
    await new Promise(r=>setTimeout(r,steps[n][1]));
    if(cancelled)return;
    $('#dstep'+n)?.classList.replace('active','done');}};
  try{
   const [result]=await Promise.all([api('/api/intake/share',{}),walk()]);
   cancelled=true;
   steps.forEach((_,n)=>$('#dstep'+n)?.classList.add('done'));
   await refresh();
   openDrawer(`<div class="eyebrow">SUPPLIER MAPPING COMPLETE</div><h2>${(result.suppliers||[]).length} supplier${(result.suppliers||[]).length===1?'':'s'} matched</h2>${dispatchHtml(result)}${button('Continue to responses →','nextView','data-to="responses"','primary')}`);
  }catch(error){cancelled=true;closeDrawer();throw error}
  return}
 if(action==='newChat'){analysisThread=[];analysisTurns=[];liveAnswer=null;visualAnswer=null;selected=null;askedQuestion='';
  analysisSession=newSessionId();sessionStorage.setItem('aerchain-chat',analysisSession);renderAnalysis();return}
 if(action==='newProposal')return newProposal();
 if(action==='allocChart'){
  preferredChart=b.dataset.chart;
  if(visualAnswer)renderVisual(visualAnswer);
  return}
 if(action==='awardChart'){
  preferredChart=b.dataset.chart;
  const s=history.find(x=>x.id===(b.dataset.scenario||selected));
  const host=b.closest('.panel')?.querySelector('.award-chart');
  if(s&&host)host.innerHTML=awardChart(s,preferredChart);
  b.parentElement?.querySelectorAll('[data-action="awardChart"]')
   .forEach(x=>x.classList.toggle('active',x===b));
  return}
 if(action==='compareVisual'){go('analysis');return askVisually(b.dataset.question)}
 return askVisually(action==='askSuggestion'?b.dataset.question:$('#question').value);
 })},true);
// A composer that only answers a mouse click looks broken to anyone who types.
document.addEventListener('keydown',e=>{
 const send={rfxChat:'intakeChat',question:'askNew'}[e.target&&e.target.id];
 if(!send||e.key!=='Enter'||e.shiftKey||e.ctrlKey||e.metaKey||e.altKey||e.isComposing)return;
 const button=document.querySelector(`[data-action="${send}"]`);
 if(!button||button.disabled)return;
 e.preventDefault();button.click();
},true);
document.addEventListener('change',e=>{if(e.target.id!=='intakeFiles')return;const picked=[...e.target.files];e.target.value='';for(const file of picked){if(pendingIntakeFiles.length>=5){toast('Attach at most five files at a time.',true);break}if(file.size>12*1024*1024){toast(esc(file.name)+' is larger than 12 MB.',true);continue}pendingIntakeFiles.push(file)}renderTray()},true);
document.addEventListener('submit',async e=>{const form=e.target;if(!['proposalForm','intakeEditForm','confirmIntakeForm'].includes(form.id))return;e.preventDefault();e.stopImmediatePropagation();const submitter=e.submitter;await busy(submitter,async()=>{
 if(form.id==='confirmIntakeForm'){await api('/api/intake/save',{fields:{},confirm:true,expected_version:state.dataset_version});closeDrawer();await refresh();return}
 if(form.id==='intakeEditForm'){const data=new FormData(form),fields=Object.fromEntries(data);const items=[...form.querySelectorAll('.item-editor')].map(row=>{const weight=row.querySelector('[data-item=unit_weight_kg]').value,term=row.querySelector('[data-item=term_months]').value,sku=row.querySelector('[data-item=sku]').value.trim();const item={description:row.querySelector('[data-item=description]').value,quantity:Number(row.querySelector('[data-item=quantity]').value),unit:row.querySelector('[data-item=unit]').value};if(sku)item.sku=sku;if(weight!=='')item.unit_weight_kg=Number(weight);if(term!=='')item.term_months=Number(term);return item});await api('/api/intake/save',{fields,items,expected_version:state.dataset_version});closeDrawer();await refresh();return}
 const data=new FormData(form);if(!form.querySelector('[type=file]').files.length)data.delete('files');const r=await fetch('/api/proposals',{method:'POST',body:data}),result=await r.json();if(!r.ok)throw Error(typeof result.detail==='string'?result.detail:'Check the required proposal fields');closeDrawer();await refresh();if(submitter.value==='extract'){activeJob=await api('/api/process',{});sessionStorage.setItem('aerchain-job',activeJob.id);renderResponses();pollJob()}else toast('Supplier proposal added. Add another, or choose Extract information.');
 })},true);
