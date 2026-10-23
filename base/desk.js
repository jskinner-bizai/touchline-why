"use strict";
let current, busy=false, stream, requestGeneration=0, connectionNotice=false, frameworkFingerprint, correctionFingerprint;
let overlayReconnectGeneration=0, overlayConfirmedGeneration=-1, overlayConfirmedStream=null, overlayConfirmedSequence=0;
let lastConfirmedResponseAt=null;
let copyCasesFingerprint,copyAdviceFingerprint,copyReviewUncertain=false;
const retiredProducerStreams=new Set();
const el=id=>document.getElementById(id);
function reconnectOverlay(){
  if(!current || connectionNotice){
    el('overlay-connection').textContent='Wait for the producer and desk to recover, then reconnect the overlay.';return;
  }
  const previous=el('overlay'),replacement=document.createElement('iframe');
  replacement.id='overlay';replacement.title='Broadcast preview, independent overlay consumer';
  replacement.hidden=true;replacement.src='/overlay.html';
  previous.replaceWith(replacement);
  const generation=++overlayReconnectGeneration;
  el('overlay-connection').textContent='Reconnecting the embedded consumer. Waiting for its current-stream confirmation.';
  setTimeout(()=>{
    if(generation===overlayReconnectGeneration && overlayConfirmedGeneration!==generation){
      el('overlay-connection').textContent='Overlay connection is not confirmed. When the desk is available, use Reconnect overlay. Reload the desk if it still cannot connect.';
    }
  },3000);
}
function overlayStatus(event){
  if(!current || typeof window==='undefined' || event.origin!==window.location.origin || event.source!==el('overlay').contentWindow)return;
  const data=event.data;
  const statuses=['waiting','invalid','session_changed','expired','fallback','insight'];
  if(!data || typeof data!=='object' || Array.isArray(data) || data.type!=='touchline.overlay.status.v1'
    || !statuses.includes(data.status) || typeof data.active!=='boolean' || typeof data.quarantined!=='boolean'
    || !(data.stream_id===null || (typeof data.stream_id==='string' && data.stream_id.length>0 && data.stream_id.length<=160))
    || !Number.isSafeInteger(data.sequence) || data.sequence<0
    || (data.content_height!==undefined && (!Number.isSafeInteger(data.content_height) || data.content_height<1 || data.content_height>4096)))return;
  if((data.active && !['fallback','insight'].includes(data.status)) || (data.quarantined && (data.status!=='session_changed' || data.active)))return;
  const frame=el('overlay');
  if(connectionNotice){frame.hidden=true;return;}
  if(data.quarantined || data.stream_id!==current.publication.stream_id){
    frame.hidden=true;el('overlay-connection').textContent='Overlay paused after a producer change. Use Reconnect overlay after the desk has recovered.';return;
  }
  if(data.sequence!==current.publication.sequence){
    frame.hidden=true;el('overlay-connection').textContent='Overlay is catching up to the desk. If it stays blank, use Reconnect overlay.';return;
  }
  overlayConfirmedGeneration=overlayReconnectGeneration;overlayConfirmedStream=data.stream_id;overlayConfirmedSequence=data.sequence;frame.hidden=false;
  if(data.content_height!==undefined){
    frame.style.height=`${Math.max(260,Math.min(1600,data.content_height))}px`;
    frame.scrolling=data.content_height<=1600?'no':'auto';
  }
  el('overlay-connection').textContent=data.active?'Embedded consumer confirmed the current producer stream.':'Current producer stream confirmed; expired or unavailable insight is cleared.';
  if(data.content_height>1600)el('overlay-connection').textContent+=' Preview reached its size limit; use a shorter presentation or open the overlay separately.';
}
if(typeof window!=='undefined')window.addEventListener('message',overlayStatus);
function updateControls(){
  document.querySelectorAll('button,select').forEach(element=>{element.disabled=busy;});
  el('live-button').hidden=!current?.live_inference?.enabled;
  el('live-button').disabled=busy || !current?.live_inference?.available;
  el('live-help').hidden=!current?.live_inference?.enabled;
  if(current?.live_inference?.enabled)el('live-help').textContent=`Explicit local opt-in: ${current.live_inference.attempts}/4 attempts; ${(current.live_inference.wall_spent_ms/1000).toFixed(1)}/50s client wall budget. No automatic request or retry. Status: ${current.live_inference.job.status}.${current.live_inference.eligibility_reason?' '+current.live_inference.eligibility_reason:''}`;
  el('replay-button').disabled=busy || !current?.recorded_replay.available;
  el('replay-help').textContent=current?.recorded_replay.available
    ? 'Replays an exact accepted historical SDK output. No live inference.'
    : current?.recorded_replay.unavailable_reason || 'Show the original 50s pattern to replay its recorded model selection.';
  updateCopyControls();
}
function setBusy(value){busy=value;updateControls();}
function selectedCopyCase(){return current?.copy_review?.cases?.find(row=>row.case_id===el('copy-case')?.value);}
function canReviewCopy(){return !busy&&!connectionNotice&&!copyReviewUncertain&&current?.copy_review?.mode==='recorded'&&selectedCopyCase()?.available===true;}
function canApproveCopy(){
  const review=current?.copy_review,advice=review?.advice;
  return canReviewCopy()&&review.status==='reviewed'&&advice?.case_id===selectedCopyCase()?.case_id
    &&advice?.can_approve===true&&['allow','revise'].includes(advice.decision)
    &&typeof advice.advice_id==='string'&&advice.advice_id.length>0;
}
function updateCopyControls(){
  if(!el('copy-review'))return;
  const review=current?.copy_review,available=review?.mode==='recorded';
  el('copy-review').hidden=!available;
  el('copy-case').disabled=!available||busy||connectionNotice||copyReviewUncertain||!(review?.cases||[]).some(row=>row.available===true);
  el('copy-review-button').disabled=!canReviewCopy();
  el('copy-approve').disabled=!canApproveCopy();
  el('copy-clear').disabled=!available||busy||connectionNotice||copyReviewUncertain||!['reviewed','approved_copy_draft'].includes(review?.status);
  if(!available)return;
  const selected=selectedCopyCase();
  el('copy-availability').textContent=selected?.available===true
    ? 'This recorded draft matches the current facts. Reviewing it makes no model request.'
    : selected?.unavailable_reason||'Recorded drafts are available only at their matching 50s snapshot. Show the pattern first; the corrected snapshot has its own recording.';
  el('copy-status').textContent=copyReviewUncertain?'Control response not confirmed. Approval is paused until a fresh producer response confirms the current facts.'
    : connectionNotice?'Cached review. Producer unavailable; wording cannot be approved.'
    : busy?'Waiting for the producer response. No new model call.'
    : review.status==='stale'?'Facts changed. The previous advice and producer draft are no longer current. Review a matching recording again.'
    : review.status==='approved_copy_draft'?'Producer draft saved. The broadcast preview is unchanged.'
    : review.status==='reviewed'&&review.advice?.case_id!==selected?.case_id?'A different draft is selected. Review it before approving wording.'
    : review.status==='reviewed'&&review.advice?.decision==='withhold'?'Withhold this draft. No wording can be approved from this review.'
    : review.status==='reviewed'?'Inspect the original clauses and evidence, then approve only the retained wording.'
    : review.status==='cleared'?'Copy review cleared. The broadcast preview is unchanged.'
    : 'Choose an available recording to review wording before it reaches a producer draft.';
}
function renderCopyReview(s){
  if(!el('copy-review'))return;
  const review=s.copy_review;
  if(review?.mode!=='recorded'){
    el('copy-review').hidden=true;el('copy-advice').hidden=true;el('copy-approved').hidden=true;
    el('copy-clauses').replaceChildren();el('copy-facts').replaceChildren();el('copy-raw').textContent='';el('copy-approved-text').textContent='';
    copyCasesFingerprint=undefined;copyAdviceFingerprint=undefined;return;
  }
  el('copy-mode').textContent='One Microsoft Agent Framework reviewer. Actual recorded pilot outputs; no new model call. Live review is unavailable.';
  const evaluation=review.evaluation||{};
  el('copy-evaluation').textContent=`Pilot evaluation: ${evaluation.strict_passes??'?'}/${evaluation.total??'?'} strict passes. ${evaluation.status||'UNQUALIFIED'}; ${evaluation.qualification||'qualification unavailable'}. This is the recorded pilot result, not a production qualification.`;
  const cases=Array.isArray(review.cases)?review.cases:[],caseFingerprint=JSON.stringify(cases);
  if(caseFingerprint!==copyCasesFingerprint){
    copyCasesFingerprint=caseFingerprint;const previous=el('copy-case').value;
    el('copy-case').replaceChildren();
    const draftNames={P01:'Supported shot summary',P02:'Unsupported pressing explanation',P03:'Mixed shot and passing claim',P04:'Copy after the goal correction'};
    for(const row of cases){
      const option=document.createElement('option');option.value=row.case_id;option.disabled=row.available!==true;
      const name=draftNames[row.case_id]||row.label||'Recorded sample';
      option.textContent=row.available===true?name:`${name} (unavailable)`;
      el('copy-case').append(option);
    }
    el('copy-case').value=cases.find(row=>row.case_id===previous&&row.available===true)?.case_id||cases.find(row=>row.case_id===review.advice?.case_id&&row.available===true)?.case_id||cases.find(row=>row.case_id==='P03'&&row.available===true)?.case_id||cases.find(row=>row.available===true)?.case_id||'';
  }
  const visible=['reviewed','approved_copy_draft'].includes(review.status);
  const advice=visible&&cases.some(row=>row.case_id===review.advice?.case_id&&row.available===true)?review.advice:null;
  const draft=review.status==='approved_copy_draft'&&advice&&review.producer_copy_draft?.advice_id===advice.advice_id?review.producer_copy_draft:null;
  const fingerprint=JSON.stringify({advice,draft});
  if(fingerprint!==copyAdviceFingerprint){
    copyAdviceFingerprint=fingerprint;
    el('copy-advice').hidden=!advice;el('copy-approved').hidden=!draft;
    el('copy-clauses').replaceChildren();el('copy-facts').replaceChildren();el('copy-raw').textContent='';el('copy-approved-text').textContent='';
    el('copy-raw-details').open=false;
    if(advice){
      const labels={allow:'Keep this wording',revise:'Keep only the supported clauses',withhold:'Withhold this draft'};
      el('copy-decision').textContent=`${advice.case_id}: ${labels[advice.decision]||'Review unavailable'}`;
      el('copy-recorded-reason').textContent=`Recorded reviewer reason: ${String(advice.raw_reason||'Not supplied').replace(/_/g,' ')}.`;
      const checked=advice.deterministic_classification||{};
      el('copy-checked-reason').textContent=`Fact check: ${checked.explanation||String(checked.reason||'Not supplied').replace(/_/g,' ')}${checked.evidence_ids?.length?` Evidence: ${checked.evidence_ids.join(', ')}.`:''}`;
      for(const clause of advice.clauses||[]){
        const row=document.createElement('li'),tag=document.createElement('strong'),text=document.createElement('p'),proof=document.createElement('small');
        tag.textContent=`${clause.disposition==='keep'?'Keep':clause.disposition==='drop'?'Drop':'Unqualified'} ${clause.id}`;
        row.className=clause.disposition==='keep'?'copy-keep':'copy-drop';text.textContent=clause.text;
        proof.textContent=clause.evidence_ids?.length?`Evidence: ${clause.evidence_ids.join(', ')}`:'No supporting evidence linked for this clause.';
        row.append(tag,text,proof);el('copy-clauses').append(row);
      }
      for(const fact of advice.facts||[]){
        const row=document.createElement('li'),text=document.createElement('p'),proof=document.createElement('small');
        text.textContent=fact.text;proof.textContent=`${fact.fact_id}: ${(fact.evidence_ids||[]).map(id=>`${id}${fact.event_revisions?.[id]!==undefined?` revision ${fact.event_revisions[id]}`:''}`).join(', ')}`;
        row.append(text,proof);el('copy-facts').append(row);
      }
      el('copy-raw').textContent=JSON.stringify({mode:'recorded',new_model_calls:0,case_id:advice.case_id,advice_id:advice.advice_id,binding:advice.binding,raw_reason:advice.raw_reason,deterministic_classification:checked,receipt_sha256:advice.receipt_sha256,recorded_trace:advice.recorded_trace},null,2);
    }
    if(draft)el('copy-approved-text').textContent=draft.text;
  }
}
function renderCorrections(s){
  const through=s.publication.event_time.through_ms;
  const supplied=s.envelope.provenance.corrections;
  const visible=(Array.isArray(supplied)?supplied:[]).filter(row=>[row?.before?.at_ms,row?.after?.at_ms].every(at=>Number.isInteger(at) && at<=through));
  const fingerprint=JSON.stringify({through,visible});
  if(fingerprint===correctionFingerprint)return visible;correctionFingerprint=fingerprint;
  el('correction-summary').textContent=visible.length
    ? `${visible.length} approved correction${visible.length===1?'':'s'} visible at ${through/1000}s. Rewind keeps these changes.`
    : `No approved corrections visible at ${through/1000}s.`;
  const list=el('correction-list');list.replaceChildren();
  for(const correction of visible){
    const item=document.createElement('li'),title=document.createElement('strong'),changes=document.createElement('ul');
    title.textContent=`${correction.target_event_id}: revision ${correction.from_revision} to ${correction.to_revision}`;
    const before=correction.before || {},after=correction.after || {};
    for(const key of [...new Set([...Object.keys(before),...Object.keys(after)])].sort()){
      const had=Object.prototype.hasOwnProperty.call(before,key),has=Object.prototype.hasOwnProperty.call(after,key);
      if(had===has && JSON.stringify(before[key])===JSON.stringify(after[key]))continue;
      const change=document.createElement('li');
      change.textContent=`${key}: ${had?JSON.stringify(before[key]):'(absent)'} → ${has?JSON.stringify(after[key]):'(absent)'}`;changes.append(change);
    }
    item.append(title,changes);list.append(item);
  }
  el('correction-raw').textContent=JSON.stringify(visible,null,2);
  return visible;
}
function renderFrameworkEvidence(s){
  const framework=s.recorded_framework_trace || {};
  const through=s.publication.event_time.through_ms;
  const receipts=(framework.receipts || []).filter(row=>row.historical_only===true && row.through_ms<=through);
  const moments=(s.recap.recorded_selections || []).filter(row=>row.historical_only===true && row.original_through_ms<=through);
  const attempts=s.live_inference?.attempts || 0;
  const fingerprint=JSON.stringify({receipts,moments,attempts,available:s.recorded_replay.available,qualification:framework.qualification,withheld:framework.withheld_receipt_count});
  if(fingerprint===frameworkFingerprint)return;frameworkFingerprint=fingerprint;
  const visibleMoments=new Set();
  const records=el('sdk-records');records.replaceChildren();
  function field(list,label,value){
    const term=document.createElement('dt'),description=document.createElement('dd');
    term.textContent=label;description.textContent=value;list.append(term,description);
  }
  for(const receipt of receipts){
    const moment=moments.find(row=>(row.receipt_ids || []).includes(receipt.receipt_id));
    if(moment)visibleMoments.add(moment.recorded_moment_id);
    const article=document.createElement('article');article.className='sdk-record';
    const heading=document.createElement('h3');heading.textContent=`Accepted historical receipt: ${receipt.receipt_id}`;
    const list=document.createElement('dl');
    field(list,'Model',receipt.model_id || 'Not supplied');
    field(list,'SDK versions',Object.entries(receipt.sdk_versions || {}).map(([name,version])=>`${name} ${version}`).join('; ') || 'Not supplied');
    field(list,'Recorded event time',`${receipt.through_ms/1000}s`);
    field(list,'Recorded call duration',Number.isFinite(receipt.elapsed_ms)?`${(receipt.elapsed_ms/1000).toFixed(3)}s, including this historical call only`:'Not supplied');
    field(list,'Chosen candidate',moment?.selection?.candidate_id || 'Candidate mapping unavailable');
    field(list,'Pattern and evidence',moment?.selection?`${moment.selection.explanation_type}; ${(moment.selection.evidence_ids || []).join(', ')}`:'No selection metadata is visible at this watermark');
    field(list,'Receipt SHA-256',receipt.receipt_sha256 || 'Not supplied');
    const timeline=document.createElement('ol');timeline.className='sdk-timeline';
    for(const entry of receipt.trace || []){
      const step=document.createElement('li');
      const details=['agent_id','agent_class','client_class','path','http_status','response_class'].filter(key=>entry[key]!==undefined).map(key=>`${key}: ${entry[key]}`).join('; ');
      step.textContent=`${entry.source}: ${entry.event}${details?` (${details})`:''}`;timeline.append(step);
    }
    article.append(heading,list,timeline);records.append(article);
  }
  el('sdk-trace-summary').textContent=receipts.length
    ? `${receipts.length} accepted historical receipts; ${visibleMoments.size} distinct selection moment${visibleMoments.size===1?'':'s'}. Current local attempts: ${attempts}. Recorded evidence, not live inference.`
    : 'No recorded SDK trace is visible at this event time. Advance the replay to inspect history. Opening this panel makes no model request.';
  el('sdk-replay-state').textContent=!receipts.length?'Historical selections are withheld before their event-time watermark.'
    : s.recorded_replay.available?'Recorded replay is available because the current facts match the original snapshot.'
    : 'Recorded replay is blocked because the current snapshot differs. A supported historical claim remains history, not a new model result.';
  el('sdk-trace').textContent=JSON.stringify({qualification:framework.qualification || 'Historical accepted SDK traces only.',receipts,withheld_receipt_count:framework.withheld_receipt_count || 0},null,2);
}
function render(s){
  if(retiredProducerStreams.has(s.publication.stream_id))return false;
  if(connectionNotice){el('notice').textContent='';connectionNotice=false;}
  current=s;const p=s.publication;
  lastConfirmedResponseAt=Date.now();
  const freshness='Producer connected. Facts confirmed for this publication.';
  if(el('score-freshness').textContent!==freshness)el('score-freshness').textContent=freshness;
  el('score-last-confirmed').textContent=`Last confirmed response: ${new Date(lastConfirmedResponseAt).toISOString().replace('T',' ').replace(/\.\d{3}Z$/,' UTC')}.`;
  el('clock').textContent=`Event time ${(p.event_time.through_ms/1000).toFixed(0)}s`;
  el('score').textContent=Object.entries(p.facts.score).map(([name,goals])=>`${name} ${goals}`).join('  ·  ');
  if(el('mode').textContent!==s.recorded_replay.label)el('mode').textContent=s.recorded_replay.label;
  el('version').textContent=`Publisher sequence ${p.sequence}. Prior publications replaced by this one: ${p.retracts.length}.`;
  el('audience').value=s.audience;el('language').value=s.language;
  el('recap-text').textContent=s.recap.views[s.audience][s.language];el('recap-text').lang=s.language;
  el('recap-english').hidden=s.language!=='es';
  el('recap-english-text').textContent=s.language==='es'?s.recap.views[s.audience].en:'';
  el('recap-proof').textContent=`${s.recap.recorded_receipt_count} historical accepted receipts / ${s.recap.recorded_moment_count} distinct moment. ${s.recap.withdrawn_claims.length} withdrawn goal claim. New local attempts: ${s.live_inference?.attempts||0}.`;
  if(s.position!==s.positions-1)el('recap').hidden=true;
  const visibleCorrections=renderCorrections(s);
  el('audit').textContent=JSON.stringify({recovery:s.recovery_info,provenance:{...s.envelope.provenance,corrections:visibleCorrections},delivery:{stream_id:p.stream_id,sequence:p.sequence,overlay_id:p.overlay_id,fact_id:p.fact_id,replaces:p.retracts},recorded_replay:s.recorded_replay,recap_id:s.recap.recap_id},null,2);
  const live=s.live_inference;
  el('live-details').hidden=!live?.enabled;el('live-trace').textContent=live?.enabled?JSON.stringify(live,null,2):'';
  el('build-mode').textContent=live?.enabled?'Synthetic match - recorded replay and explicitly enabled local model selection':'Synthetic match - recorded model replay - no live inference';
  el('build-footer').textContent=live?.enabled?'Fictional teams; deterministic facts, wording and recap. Historical receipts and new local inference are labelled separately. The timeout button injects a failure. Real server cancellation remains unverified.':'This demo uses fictional teams and recorded model outputs. Facts, wording and recap are deterministic. The timeout is an explicit injection; real server cancellation remains unverified. No live inference runs in this build.';
  renderFrameworkEvidence(s);
  copyReviewUncertain=false;renderCopyReview(s);
  const evidence=el('evidence-body');evidence.replaceChildren();
  const priority=event=>event.id==='e010'?-2:event.id==='e008'?-1:0;
  for(const event of [...s.envelope.provenance.evidence_records].sort((a,b)=>priority(a)-priority(b))){
    const row=document.createElement('div');row.className='event';const id=document.createElement('strong');
    id.textContent=`${event.id} · revision ${s.envelope.provenance.event_revisions[event.id]}`;
    row.append(id,document.createTextNode(' '+JSON.stringify(event)));evidence.append(row);
  }
  if(stream&&stream!==p.stream_id){
    retiredProducerStreams.add(stream);requestGeneration++;reconnectOverlay();
  }else if(overlayConfirmedStream!==p.stream_id || overlayConfirmedSequence!==p.sequence){
    el('overlay').hidden=true;el('overlay-connection').textContent='Waiting for the embedded consumer to confirm this publication. If it stays blank, use Reconnect overlay.';
  }
  stream=p.stream_id;updateControls();return true;
}
async function control(value){
  if(busy)return;setBusy(true);requestGeneration++;connectionNotice=false;el('notice').textContent='';
  try{
    const response=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...value,operation_id:crypto.randomUUID()}),signal:AbortSignal.timeout(5000)});
    const state=await response.json();if(!response.ok)throw Error(state.error || 'Control request failed');render(state);
    if(value.action==='finish'){el('recap').hidden=false;el('recap').scrollIntoView({block:'center',behavior:'instant'});}
  }catch(error){
    if(current?.copy_review||['review_copy','approve_copy','clear_copy'].includes(value.action))copyReviewUncertain=true;
    el('notice').textContent=['TimeoutError','AbortError'].includes(error.name)
      ? 'Control response timed out; its outcome is uncertain. Inspect the refreshed score and evidence before repeating the action.'
      : error.message;
  }finally{setBusy(false);}
}
document.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',()=>control({action:button.dataset.action})));
el('overlay-reconnect').addEventListener('click',reconnectOverlay);
el('evidence-toggle').addEventListener('click',()=>{
  const panel=el('evidence');panel.hidden=!panel.hidden;el('evidence-toggle').setAttribute('aria-expanded',String(!panel.hidden));
  if(!panel.hidden)panel.scrollIntoView({block:'start',behavior:'instant'});
});
el('trace-toggle').addEventListener('click',()=>{
  const panel=el('sdk-details');panel.open=!panel.open;el('trace-toggle').setAttribute('aria-expanded',String(panel.open));
  if(panel.open)panel.scrollIntoView({block:'start',behavior:'instant'});
});
el('sdk-details').addEventListener('toggle',()=>el('trace-toggle').setAttribute('aria-expanded',String(el('sdk-details').open)));
el('copy-case')?.addEventListener('change',updateCopyControls);
el('copy-review-button')?.addEventListener('click',()=>{if(canReviewCopy())return control({action:'review_copy',case_id:selectedCopyCase().case_id});});
el('copy-approve')?.addEventListener('click',()=>{if(canApproveCopy())return control({action:'approve_copy',advice_id:current.copy_review.advice.advice_id});});
el('copy-clear')?.addEventListener('click',()=>{if(!el('copy-clear').disabled)return control({action:'clear_copy'});});
for(const id of ['audience','language'])el(id).addEventListener('change',()=>control({action:'view',audience:el('audience').value,language:el('language').value}));
async function poll(){
  const generation=requestGeneration;
  try{
    const response=await fetch('/api/state',{cache:'no-store',signal:AbortSignal.timeout(1500)});
    if(!response.ok)throw Error('Producer unavailable');const state=await response.json();
    if(!busy&&generation===requestGeneration&&(!current||state.publication.stream_id!==current.publication.stream_id||state.publication.sequence>=current.publication.sequence)){
      render(state);if(connectionNotice){el('notice').textContent='';connectionNotice=false;}
    }
  }catch(_){if(generation===requestGeneration&&!busy){
    el('notice').textContent='Producer unavailable. The overlay clears expired insight independently; retry a control only after the producer recovers.';connectionNotice=true;
    el('score-freshness').textContent=current?'Cached facts. Producer unavailable; no new producer update is available.':'Producer unavailable. No facts have been confirmed yet.';
    el('overlay').hidden=true;el('overlay-connection').textContent='Producer unavailable. Wait for the desk to recover, then reconnect the overlay if the card stays blank.';
    updateCopyControls();
  }}
  setTimeout(poll,700);
}
poll();
