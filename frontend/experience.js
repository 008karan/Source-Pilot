/* Guided experience layered onto the existing comparison and evidence components. */
let currentView='rfx',activeJob=null,jobTimer=null,recorder=null,recordStream=null,recordTarget=null,askedQuestion='';
const originalGo=go;
go=function(view){currentView=view;document.body.dataset.view=view;originalGo(view)};
document.body.dataset.view='rfx';
const hero=(step,title,description,action='')=>`<div class="section-hero"><div><div class="step-label">${step}</div><h2>${title}</h2><p>${description}</p></div>${action}</div>`;
const next=(text,label,view)=>`<div class="next-step"><span>${text}</span>${button(label,'nextView',`data-to="${view}"`,'primary')}</div>`;
const mic=target=>`<button class="voice-button" data-action="voice" data-target="${target}" aria-label="Record voice request" title="Record a request; Co-pilot transcribes it for your review">◉ <span>Voice</span></button>`;
const tableLines=()=>`<div class="table-wrap"><table><thead><tr><th>SKU</th><th>Annual quantity</th><th>Specification</th></tr></thead><tbody>${state.rfx.items.map(i=>`<tr><td>${esc(i.sku)}</td><td>${i.annual_quantity.toLocaleString('en-IN')}</td><td>${esc(i.description)}</td></tr>`).join('')}</tbody></table></div>`;
renderRfx=function(){const d=state.draft,r=state.rfx,released=state.rfx_status==='approved';$('#view-rfx').innerHTML=hero('01 / CREATE YOUR RFx','Start with what you need.','Describe the purchase. Review a structured brief. You decide when it goes out.')+`<div class="chat-workspace"><div class="chat-stream">${d?`<div class="user-message">${esc(d.buyer_summary)}</div><div class="assistant-message"><div class="assistant-avatar">a.</div><div class="assistant-content"><div class="chat-label">RFx co-pilot · ${esc(state.draft_mode==='gemini'?'Sourcing co-pilot':'offline template')}</div><h3>Your sourcing brief is ready to review.</h3><p>${esc(d.scope)}</p><div class="brief-metrics"><div><strong>30</strong><span>line items</span></div><div><strong>5</strong><span>suppliers</span></div><div><strong>${d.commercial_terms.quote_validity_days} days</strong><span>quote validity</span></div></div><div class="brief-detail"><details><summary>Scope & line items <span>30 baseline specifications</span></summary><p>${esc(d.line_item_strategy)}</p>${tableLines()}</details><details><summary>Quality requirements <span>8 reviewable rules</span></summary>${r.questionnaire.map(q=>`<p><b>${q.id}.</b> ${esc(q.question)} ${q.mandatory?'<span class="pill">Required</span>':''}</p>`).join('')}<p class="muted">Baseline qualification IDs are preserved. Co-pilot suggestions are advisory.</p></details><details><summary>Commercial terms <span>INR · landed · ex-GST</span></summary><p>Fixed buyer comparison FX: ₹${r.commercial_rules.fx_rate_usd_inr}/USD. Freight must be explicit. Conditional rebates are shown separately.</p><p>${esc(d.commercial_terms.freight_requirement)}</p></details><details><summary>Before you send <span>${d.buyer_review_points.length} review points</span></summary><ul>${d.buyer_review_points.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details></div>${released?`<div class="success-note">✓ Approved by ${esc(state.approved_by)}. Demo invitations released.</div>${next('Next: collect supplier replies.','Open response inbox','responses')}`:`<div class="approval-row"><span>Ready to invite the five demo suppliers?</span>${button('Approve & release RFx →','release','','primary')}</div><p class="fine-print">Delivery is simulated. No external email is sent.</p>`}</div></div>`:`<div class="welcome-card"><div class="welcome-symbol">✦</div><h3>A sourcing event, from a conversation.</h3><p>Use the 30-line corrugated packaging brief to start your demo. The co-pilot will prepare scope, questionnaire and terms.</p><div class="suggestions">${button('Use the packaging brief ↗','suggestRfx','','suggestion')}${button('View buyer reference','buyerReference','','suggestion')}</div></div>`}</div>${!released?`<div class="composer"><textarea id="rfxChat" aria-label="Describe your sourcing requirement" placeholder="Describe what you need to buy…">${!d?'Create the FY27 corrugated packaging RFx for Bengaluru and Hosur. Retain the 30 baseline items and quality gates. Compare landed costs in INR excluding GST. Quotes valid for 60 days.':''}</textarea><div class="composer-toolbar">${mic('rfxChat')}<span>Sourcing co-pilot · buyer approval required</span>${button(d?'Refine brief ↑':'Build my RFx ↑','composeRfx','','primary')}</div></div>`:''}</div>`;};
renderResponses=function(){const vs=Object.values(state.vendors),received=vs.filter(v=>v.documents?.length).length,processed=vs.filter(v=>v.response_status==='processed').length;$('#view-responses').innerHTML=hero('02 / COLLECT & UNDERSTAND','Their format. Your clarity.','Paste an email, attach a quote, or load the five demo messages. Extraction starts only when you ask.',button('Load demo messages','demoMessages',state.rfx_status!=='approved'?'disabled':''))+`${state.rfx_status!=='approved'?next('First, build and approve your RFx.','Back to RFx','rfx'):''}${vs.length?'':emptyInbox()}${vs.length?`<div class="inbox-toolbar"><div><b>${received} of ${vs.length} responses received</b><span>${processed} processed · Excel, PDF, Word, photo and email</span></div>${button('Extract & normalize →','processAll',(!received||activeJob?.status==='running')?'disabled':'','primary')}</div>`:''}<div id="processingPanel">${processingHtml()}</div><div class="supplier-grid">${vs.map((v,i)=>{const open=state.exceptions.filter(e=>e.vendor_id===v.id&&e.status!=='resolved_by_buyer').length;return `<article class="supplier-card"><div class="supplier-top"><div class="supplier-avatar color-${i}">${esc(v.name.slice(0,1))}</div>${pill(v.response_status==='processed'?'processed':v.documents?.length?'received':'waiting')}</div><h3>${esc(v.name)}</h3><p class="muted">${esc(v.email||'Demo supplier')}</p><p class="supplier-format">${({xlsx:'Excel workbook',pdf:'PDF proposal',docx:'Word offer',jpg:'Phone photo',eml:'Email reply'})[v.format]||esc(v.format)}</p>${v.documents?.length?`<div class="message-preview"><b>${esc(v.subject||'Supplier quote')}</b><p>${esc(v.message?.slice(0,120)||'Supplier attachments received. Ready to read their original response.')}</p><button class="attachment-link" data-action="packet" data-id="${v.id}">▧ ${v.documents.length} source ${v.documents.length===1?'document':'documents'} ↗</button></div>`:'<div class="waiting-note">No response yet. Add the supplier’s message to begin.</div>'}${v.response_status==='processed'?`<div class="supplier-facts"><span><b>${v.facts.length}/${state.rfx.items.length}</b> line attempts</span><span>${pill(v.quality)}</span></div><button class="review-link" data-action="vendorReview" data-id="${v.id}">${open?open+' points need attention →':'Review extracted details →'}</button>`:''}<div class="supplier-actions">${button(v.documents?.length?'Replace message':'Add supplier response','receiveMessage',`data-id="${v.id}" ${state.rfx_status!=='approved'?'disabled':''}`)}${v.response_status==='processed'?button('Details','inspect',`data-id="${v.id}"`):''}</div></article>`}).join('')}</div>${processed?next('Responses are ready. Review uncertainty before choosing an award.','Review & compare →','compare'):''}`;};
// Extraction is the moment the product earns trust, so it should look like work:
// the mark turns, the stage names change, each supplier reports its own progress.
const READING_STAGES=['Reading the source files','Detecting each supplier\u2019s format',
 'Extracting quoted line items','Mapping lines to your requirement','Normalizing to one comparable basis'];
let stageTimer=null,stageAt=0;
function stageTick(){
 const el=$('#readingStage');if(!el)return;
 stageAt=(stageAt+1)%READING_STAGES.length;
 el.classList.remove('stage-in');void el.offsetWidth;
 el.textContent=READING_STAGES[stageAt];el.classList.add('stage-in');
}
function stageLoop(on){
 clearInterval(stageTimer);stageTimer=null;
 if(on)stageTimer=setInterval(stageTick,2200);
}
const VENDOR_STEPS=['queued','reading','extracting','mapping','normalizing','done'];
function vendorProgress(stage){
 const name=String(stage||'queued').toLowerCase();
 const hit=VENDOR_STEPS.findIndex(s=>name.includes(s));
 if(name.includes('complete')||name.includes('done')||name.includes('processed'))return 1;
 return hit<0?0.12:Math.max(0.12,hit/(VENDOR_STEPS.length-1));
}
// Nothing has arrived yet: say what arrives, how it gets here, and what happens next.
const INBOX_FORMATS=[['Excel workbook','A priced line-item sheet'],['PDF proposal','A formatted commercial offer'],
 ['Word offer','A letter with a price table'],['Photo of a rate card','Read with the vision model'],
 ['Email reply','Prices written in the body']];
// A screen with nothing on it should say what it is waiting for, and how far the
// event has got. The same three gates drive Compare, Analysis and Award.
function pipelineSteps(){
 const vs=Object.values(state.vendors||{});
 return [
  ['RFx released to suppliers', state.rfx_status==='approved'],
  ['Supplier responses received', vs.some(v=>v.documents?.length)],
  ['Responses extracted and normalized', !!state.comparison?.length],
 ];
}
function waitingPanel(title,note,action=''){
 const steps=pipelineSteps();
 const next=steps.findIndex(([,done])=>!done);
 return `<section class="waiting-panel">
  <div class="waiting-head"><span class="reading-orb">${AGENT_MARK}</span>
   <div><h3>${esc(title)}</h3><p>${esc(note)}</p></div></div>
  <ol class="waiting-steps">${steps.map(([label,done],n)=>
    `<li class="${done?'done':n===next?'next':'pending'}"><i></i><span>${esc(label)}</span>${n===next?'<b>Next</b>':''}</li>`).join('')}</ol>
  ${action}</section>`;
}
function waitingFor(screen){
 const vs=Object.values(state.vendors||{});
 const released=state.rfx_status==='approved';
 const received=vs.some(v=>v.documents?.length);
 if(!released)
  return waitingPanel('Waiting for the request to go out',
   'Finish the checklist and share your RFx. Everything on this screen is built from what suppliers send back.',
   next('Start with your requirement.','Open RFx builder','rfx'));
 if(!received)
  return waitingPanel('Waiting for supplier responses',
   'Nothing has arrived yet. Add each reply in whatever format the supplier sent — this screen fills in once they are extracted.',
   next('Collect the responses first.','Open response inbox','responses'));
 return waitingPanel('Waiting for extraction',
  {compare:'Responses are in, but nothing is comparable until they are read and put on one basis.',
   analysis:'Responses are in. Extract them and every answer here will be calculated from that reviewed data.',
   award:'Responses are in. Extract them and the award scenarios will be built from the normalized prices.'}[screen]
   ||'Responses are in and waiting to be read.',
  next('Run extraction to continue.','Extract responses','responses'));
}
function emptyInbox(){
 const shared=intakeData?.dispatch?.suppliers?.length||0;
 const released=state.rfx_status==='approved';
 return `<section class="empty-inbox">
  <div class="empty-inbox-head">
   <span class="reading-orb">${AGENT_MARK}</span>
   <div>
    <h3>No responses yet</h3>
    <p>${released
      ? (shared?`Your request is with ${shared} supplier${shared===1?'':'s'}. Add each reply as it arrives — in whatever format they send.`
               :'Your request is released. Add each supplier reply as it arrives — in whatever format they send.')
      : 'Approve and share your RFx first, then supplier replies land here.'}</p>
   </div>
  </div>
  <div class="empty-inbox-formats">${INBOX_FORMATS.map(([name,note])=>
    `<div><b>${esc(name)}</b><small>${esc(note)}</small></div>`).join('')}</div>
  <ol class="empty-inbox-steps">
   <li><b>Add what they sent</b><span>Paste the email or attach the file. Nothing is read yet.</span></li>
   <li><b>Extract &amp; normalize</b><span>Runs only when you ask, and shows its progress per supplier.</span></li>
   <li><b>Compare on one basis</b><span>Landed cost in one currency and unit, with every figure traceable.</span></li>
  </ol>
 </section>`;
}
function processingHtml(){
 if(!activeJob)return '';
 const j=activeJob,running=j.status==='running',done=j.status==='completed';
 const vendors=Object.values(state.vendors);
 const finished=vendors.filter(v=>vendorProgress(j.vendors[v.id]?.stage)>=1).length;
 return `<div class="processing-card${running?' running':''}${done?' done':''}">
  <div class="processing-title">
   <span class="reading-orb${running?' spinning':''}">${AGENT_MARK}</span>
   <div>
    <h3>${running?'Reading the supplier responses'+dots():done?'Your comparison is ready.':'Processing needs attention'}</h3>
    ${running?`<p class="reading-stage stage-in" id="readingStage">${esc(READING_STAGES[stageAt])}</p>`
             :`<p>${esc(j.error||'Prices, qualification and source references have been saved.')}</p>`}
   </div>
   <div class="processing-count"><b>${finished}</b><small>of ${vendors.length} read</small></div>
  </div>
  <div class="processing-vendors">${vendors.map(v=>{
    const p=j.vendors[v.id],pct=Math.round(vendorProgress(p?.stage)*100);
    return `<div class="${pct>=100?'vendor-done':pct>12?'vendor-live':''}">
      <span>${esc(v.name)}</span>
      <b>${esc(p?.stage||'Queued')}</b>
      <div class="vendor-track"><i style="width:${pct}%"></i></div>
      <small>${esc(p?.message||'Waiting to start')}</small></div>`}).join('')}</div>
 </div>`;
}
const dots=()=>'<span class="ell"><i>.</i><i>.</i><i>.</i></span>';
async function pollJob(){if(!activeJob)return;try{activeJob=await api('/api/jobs/'+activeJob.id);$('#processingPanel').innerHTML=processingHtml();stageLoop(activeJob.status==='running');if(activeJob.status==='running'){jobTimer=setTimeout(pollJob,900)}else{sessionStorage.removeItem('aerchain-job');await refresh();if(activeJob.status==='completed')toast('Extraction complete. Review the source-backed comparison.');else toast(activeJob.error,true)}}catch(e){toast(e.message,true);jobTimer=setTimeout(pollJob,2500)}}
const originalRenderCompare=renderCompare;
renderCompare=function(){originalRenderCompare();$('#view-compare').insertAdjacentHTML('afterbegin',hero('03 / REVIEW WITH CONFIDENCE','Know what you can trust.','Click any price for its source and calculation. Uncertain values stay out of award scenarios.',button('Analyze this event →','nextView','data-to="analysis"','primary')));};
const scenarioPrompts=[['Cheapest qualified supplier per line','Find the lowest-cost qualified award'],['Qualified only, no supplier above 45% of award spend','Balance cost and concentration risk'],['Qualified suppliers with delivery within 14 days','See the cost of faster delivery'],['Compare supplier payment terms','Read the payment terms each supplier stated'],['Compare supplier warranty and service level','Read the warranty each supplier stated'],['Qualified suppliers with delivery within 1 day','Test an infeasible constraint']];
renderAnalysis=function(){const question=$('#question')?.value||'';$('#view-analysis').innerHTML=hero('04 / FIND YOUR AWARD','Ask the next “what if”.','Explore supplier splits, delivery limits and cost. Every result is calculated from your reviewed data.',button('Start new chat','newChat','','small-button'))+`<div class="analysis-layout"><div class="analysis-conversation"><div id="analysisThread">${analysisThread.map(entry=>`<div class="thread-entry">${entry}</div>`).join('')}</div><div id="scenarioResult" class="scenario-result ${selected?'show':''}">${!selected?`<div class="welcome-card analysis-welcome"><div class="welcome-symbol">✦</div><h3>What would you like to understand?</h3><p>Try one of these scenarios, or ask your own question.</p><div class="scenario-suggestions">${scenarioPrompts.map(([q,label])=>button(label+' ↗','askSuggestion',`data-question="${esc(q)}"`,'suggestion')).join('')}</div></div>`:''}</div><div class="composer analyst-composer"><textarea id="question" aria-label="Scenario question" placeholder="What if no supplier gets more than 45% of the award?">${esc(question)}</textarea><div class="composer-toolbar">${mic('question')}<span>Enter to send · Co-pilot interprets, optimizer calculates</span>${button('Analyze ↑','askNew','','primary')}</div></div></div></div>`;if(selected){const s=history.find(x=>x.id===selected);if(s)renderScenario(s)}else $('#scenarioResult').classList.add('show');};
const originalRenderScenario=renderScenario;
renderScenario=function(s){originalRenderScenario(s);$('#scenarioResult').insertAdjacentHTML('afterbegin',`<div class="user-message">${esc(askedQuestion||s.question||'Run an award scenario')}</div>`);if(s.status==='ok'){$('#scenarioResult .panel').insertAdjacentHTML('afterbegin',`<div class="chat-label">✦ Decision analyst · source data v${s.dataset_version}</div>`);}/* history sidebar removed */};
const originalShowEvidence=showEvidence;
showEvidence=async function(id,version){await originalShowEvidence(id,version);const e=await api('/api/evidence/'+id+(version?'?version='+version:''));if(e.source_path){$('#drawerBody').insertAdjacentHTML('beforeend',`<div class="inline-source"><h3>Original document</h3>${e.type==='pdf'?`<iframe title="Original PDF source" src="/api/evidence/${id}/source#page=${e.page||1}"></iframe>`:e.type==='jpg'||e.type==='png'?'':`<p>Native source excerpt is shown above with its location. Download the original to inspect the full workbook or document.</p>`}</div>`)};};
function packet(id){const v=state.vendors[id];openDrawer(`<div class="eyebrow">SUPPLIER MESSAGE</div><h2>${esc(v.name)}</h2><h3>${esc(v.subject)}</h3><pre class="email-body">${esc(v.message||'See the attached supplier document below.')}</pre>${(v.documents||[]).map((d,i)=>{const ext=d.filename.split('.').pop().toLowerCase();return `<div class="source-card"><b>${esc(d.filename)}</b>${['jpg','jpeg','png'].includes(ext)?`<img class="source-preview" src="/api/responses/${id}/documents/${i}" alt="Supplier attachment">`:ext==='pdf'?`<iframe class="document-frame" title="Supplier PDF" src="/api/responses/${id}/documents/${i}"></iframe>`:''}<a class="filelink" href="/api/responses/${id}/documents/${i}" target="_blank" rel="noopener">Open original file ↗</a></div>`}).join('')}`)}
function receiveForm(id){const v=state.vendors[id];openDrawer(`<div class="eyebrow">SIMULATE A SUPPLIER REPLY</div><h2>${esc(v.name)}</h2><p>Paste the message and attach the original quote. Nothing is extracted until you start processing.</p><form id="receiveForm" data-id="${id}"><label class="field">Email subject<input name="subject" value="FY27 corrugated packaging — supplier offer" required></label><label class="field">Email body<textarea name="body" placeholder="Dear Priya, please find our quotation attached…" rows="6"></textarea></label><label class="drop-zone">Attach quote files<input name="files" type="file" multiple accept=".xlsx,.docx,.pdf,.eml,.txt,.jpg,.jpeg,.png,.webp"><span>Excel, PDF, Word, photo or email · up to 12 MB each</span></label><button type="submit" class="primary">Receive this response</button></form>`)}
async function recordVoice(target,b){if(recorder?.state==='recording'){recorder.stop();b.textContent='Transcribing…';return}if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)throw Error('Voice recording is unavailable in this browser. Use text, or open the app in Chrome.');recordStream=await navigator.mediaDevices.getUserMedia({audio:true});recordTarget=target;const mimeType=MediaRecorder.isTypeSupported('audio/webm')?'audio/webm':'audio/mp4';recorder=new MediaRecorder(recordStream,{mimeType});const chunks=[];recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};recorder.onstop=async()=>{recordStream.getTracks().forEach(t=>t.stop());try{const f=new FormData();f.append('file',new Blob(chunks,{type:mimeType}),'request.'+(mimeType==='audio/webm'?'webm':'mp4'));const r=await fetch('/api/transcribe',{method:'POST',body:f});const result=await r.json();if(!r.ok)throw Error(result.detail);$('#'+recordTarget).value=result.text;toast('Transcript ready. Review it, then send your request.')}catch(e){toast(e.message,true)}finally{b.innerHTML='◉ <span>Voice</span>';recorder=null}};recorder.start();b.textContent='■ Stop recording';toast('Recording your request. Click Stop when finished.');setTimeout(()=>{if(recorder?.state==='recording')recorder.stop()},60000)}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-action]');if(!b)return;const a=b.dataset.action;if(!['nextView','suggestRfx','buyerReference','composeRfx','release','demoMessages','processAll','receiveMessage','packet','vendorReview','voice'].includes(a))return;if(a==='voice'){try{await recordVoice(b.dataset.target,b)}catch(err){toast(err.message,true)}return}await busy(b,async()=>{if(a==='nextView')return go(b.dataset.to);if(a==='suggestRfx'){const el=$('#rfxChat');el.value='Create the FY27 corrugated packaging RFx for Bengaluru and Hosur. Retain the 30 baseline items and quality gates. Compare landed INR costs excluding GST; quotes valid for 60 days.';el.focus();return}if(a==='buyerReference')return openDrawer(`<h2>Buyer requirement baseline</h2><p>30 line items · baseline annual spend ${cr(state.rfx.expected_annual_spend_inr)}. Imported from the handoff buyer reference.</p>${tableLines()}<a class="filelink" href="/demo-files/buyer_rfx_reference.xlsx">Download original buyer workbook</a>`);if(a==='composeRfx'){const prompt=$('#rfxChat').value;if(!prompt.trim())throw Error('Describe your requirement first.');toast('Your co-pilot is drafting scope, quality questions and terms…');await api('/api/rfx/draft',{prompt});await refresh();return}if(a==='release'){if(!state.workflow_id)await api('/api/workflow',{action:'start',use_ai:true});await api('/api/workflow',{action:'resume',approved:true,actor:state.rfx.buyer});await refresh();go('responses');toast('RFx approved. Add supplier responses to continue.');return}if(a==='demoMessages'){await api('/api/demo/inbox',{});await refresh();toast('Five real fixture documents received. Click Extract & normalize to process them.');return}if(a==='receiveMessage')return receiveForm(b.dataset.id);if(a==='packet')return packet(b.dataset.id);if(a==='vendorReview')return showVendorReview(b.dataset.id);if(a==='processAll'){activeJob=await api('/api/process',{});sessionStorage.setItem('aerchain-job',activeJob.id);renderResponses();stageAt=0;stageLoop(true);pollJob();return}if(a==='askSuggestion')$('#question').value=b.dataset.question;if(a==='askNew'||a==='askSuggestion'){const question=$('#question').value;if(!question.trim())throw Error('Enter a scenario question first.');$('#scenarioResult').classList.add('show');$('#scenarioResult').innerHTML=`<div class="user-message">${esc(question)}</div>`+agentThinking('Working through your scenario — checking eligibility and solving the award.')+``;const s=await api('/api/ask',{question});selected=s.id;await refresh();}})});
document.addEventListener('submit',async e=>{if(e.target.id!=='receiveForm')return;e.preventDefault();const form=e.target;await busy(form.querySelector('[type=submit]'),async()=>{const data=new FormData(form);if(!form.querySelector('[type=file]').files.length)data.delete('files');const r=await fetch('/api/responses/'+form.dataset.id+'/receive',{method:'POST',body:data});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Check the message and attachments.');closeDrawer();await refresh();toast('Response received. Start extraction when you are ready.');})});
const pendingJob=sessionStorage.getItem('aerchain-job');if(pendingJob){api('/api/jobs/'+pendingJob).then(j=>{activeJob=j;if(state)renderResponses();pollJob()}).catch(()=>sessionStorage.removeItem('aerchain-job'))}
