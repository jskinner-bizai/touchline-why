'use strict';
// DOM-stub tests verify host request/state behavior, not rendered browser usability.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const ROOT=__dirname;
function review(overrides={}){
  return {mode:'recorded',live_available:false,evaluation:{strict_passes:3,total:4,status:'NO_GO',qualification:'Recorded pilot; reason mismatch preserved'},status:'idle',cases:['P01','P02','P03','P04'].map(case_id=>({case_id,available:case_id!=='P04'})),advice:null,producer_copy_draft:null,...overrides};
}
function advice(overrides={}){
  return {advice_id:'recorded-P03-current',case_id:'P03',decision:'revise',can_approve:true,clauses:[{id:'C1',text:'Harbor have two shots on target.',disposition:'keep',evidence_ids:['e008','e010']},{id:'C2',text:'Meadow have not completed a pass.',disposition:'drop',evidence_ids:['e003']}],keep:['C1'],drop:['C2'],facts:[{fact_id:'F_SHOTS',text:'Harbor have had 2 shots, both on target.',evidence_ids:['e008','e010'],event_revisions:{e008:1,e010:1}},{fact_id:'F_PASS',text:'Meadow completed 1 of 1 attempted passes.',evidence_ids:['e003'],event_revisions:{e003:1}}],raw_reason:'numeric_mismatch',deterministic_classification:{reason:'numeric_mismatch',explanation:'Meadow completed a pass. Drop the contrary clause.',evidence_ids:['e003']},recorded_trace:[{source:'agent_framework',event:'recorded_result'}],receipt_sha256:'a'.repeat(64),...overrides};
}
function state(copy=review(),overrides={}){
  const now=Date.now();
  return {publication:{stream_id:'session-stream',sequence:2,issued_at_ms:now,expires_at_ms:now+30000,event_time:{through_ms:50000},facts:{score:{Harbor:1,Meadow:0}},card:{text:'Harbor 1, Meadow 0.',language:'en',fallback:true}},audience:'casual',language:'en',position:10,positions:21,envelope:{provenance:{corrections:[],evidence_records:[],event_revisions:{}}},recorded_replay:{available:true,status:'fallback'},recap:{views:{casual:{en:'Final fan recap.',es:'Spanish fan recap.'},analyst:{en:'Final analyst recap.',es:'Spanish analyst recap.'}},withdrawn_claims:[],recorded_receipt_count:2,recorded_moment_count:1},copy_review:copy,...overrides};
}
const flush=async()=>{for(let i=0;i<25;i++)await Promise.resolve();};
const ok=value=>({ok:true,status:200,json:async()=>value});
const http=(status,value={})=>({ok:false,status,json:async()=>value});
function fixture(initial=state(),handler=null){
  const elements=new Map(),timers=[],requests=[],intervals=[];let latest=initial,operation=0;
  function el(id){
    if(!elements.has(id)){
      const classes=new Set();const node={id,textContent:'',value:'',hidden:true,open:false,disabled:false,checked:false,valid:true,attributes:{},children:[],listeners:{},dataset:{},className:'',classList:{add(...items){items.forEach(item=>classes.add(item));},remove(...items){items.forEach(item=>classes.delete(item));},toggle(item,value){const add=value===undefined?!classes.has(item):value;if(add)classes.add(item);else classes.delete(item);return add;},contains(item){return classes.has(item);}},replaceChildren(...nodes){this.children=[...nodes];},append(...nodes){this.children.push(...nodes);},addEventListener(event,listener){this.listeners[event]=listener;},setAttribute(key,value){this.attributes[key]=value;},removeAttribute(key){delete this.attributes[key];},focus(){this.focused=true;context.document.activeElement=this;},scrollIntoView(options){this.lastScroll=options;},click(){if(!this.disabled)return this.listeners.click?.();},reportValidity(){return this.valid;},reset(){this.didReset=true;}};
      Object.defineProperty(node,'innerHTML',{set(){throw Error('Review content must use literal text');}});elements.set(id,node);
    }
    return elements.get(id);
  }
  const actions=['pattern','replay3','correct','finish','reset','timeout','recover'].map(action=>{const node=el(`action-${action}`);node.dataset.action=action;return node;});
  const journeys=[...actions.filter(node=>['pattern','replay3','correct'].includes(node.dataset.action)),el('inspect-evidence')];
  // Real HTML uses the replay ID on its replay3 journey button.
  elements.set('replay',actions.find(node=>node.dataset.action==='replay3'));
  const query=selector=>selector==='[data-action]'?actions:selector==="[data-action='correct']"?actions.filter(node=>node.dataset.action==='correct'):selector===".journey-button,[data-action='finish']"?[...journeys,...actions.filter(node=>node.dataset.action==='finish')]:selector==='[data-action],#audience,#language,#new-match,#new-match-confirm'?[...actions,...['audience','language','new-match','new-match-confirm'].map(el)]:[];
  const context=vm.createContext({Date,performance:{now:()=>0},AbortController,Uint8Array,crypto:{randomUUID:()=>`operation-${++operation}`},window:{innerWidth:390,location:{assign(url){context.redirect=url;}}},document:{hidden:false,getElementById:el,querySelectorAll:query,createElement:()=>el(`created-${elements.size}`),createTextNode:value=>value,addEventListener(){}},setTimeout(callback,delay){const timer={callback,delay,cancelled:false,used:false};timers.push(timer);return timer;},clearTimeout(timer){timer.cancelled=true;},setInterval(callback,delay){intervals.push({callback,delay});},fetch:async(url,options)=>{
    requests.push({url,options});
    if(handler){const answer=await handler(url,options);if(answer!==undefined)return answer;}
    if(url==='/api/session')return ok({authenticated:true,csrf:'session-csrf',matches_used:1,max_matches:3});
    if(url==='/api/state'||url==='/api/control')return ok(latest);
    if(['/api/feedback','/api/logout'].includes(url))return ok({ok:true});
    throw Error('Unexpected network route '+url);
  }});
  vm.runInContext(fs.readFileSync(path.join(ROOT,'playtest.js'),'utf8'),context);
  return {el,requests,timers,intervals,context,setState(value){latest=value;},async settlePrimary(){for(const timer of timers.filter(row=>row.delay===500&&!row.cancelled&&!row.used)){timer.used=true;await timer.callback();}await flush();},async poll(){const timer=timers.find(row=>row.delay===4000&&!row.cancelled&&!row.used);assert.ok(timer,'scheduled host poll');timer.used=true;await timer.callback();await flush();},async click(id){const answer=el(id).listeners.click?.();await answer;await flush();},async select(id,value){el(id).value=value;await el(id).listeners.change?.();await flush();}};
}
const posts=f=>f.requests.filter(row=>row.options.method==='POST'&&row.url==='/api/control').map(row=>({body:JSON.parse(row.options.body),headers:JSON.parse(JSON.stringify(row.options.headers)),credentials:row.options.credentials}));
function visibleText(node){return [node.textContent||'',...(node.children||[]).map(child=>typeof child==='string'?child:visibleText(child))].join(' ');}

test('host init keeps primary replay action, session limits and recorded boundaries',async()=>{
  const f=fixture();await flush();assert.equal(f.el('next-action').disabled,false);assert.match(f.el('next-action').textContent,/Review the mixed draft/);assert.match(f.el('session-limits').textContent,/1 of 3/);
  assert.equal(f.el('copy-review').hidden,false);assert.equal(f.el('copy-case').value,'P03');assert.match(f.el('copy-case').children[2].textContent,/Mixed shot and passing claim/);assert.match(f.el('copy-evaluation').textContent,/3\/4 strict passes.*NO_GO/);assert.equal(f.el('copy-approve').disabled,true);
  assert.ok(f.requests.every(row=>row.options.credentials==='same-origin'));assert.ok(f.requests.every(row=>['/api/session','/api/state'].includes(row.url)));
});
test('absent advisory state keeps legacy host experience usable',async()=>{
  const value=state();delete value.copy_review;const f=fixture(value);await flush();assert.equal(f.el('copy-review').hidden,true);assert.equal(f.el('copy-review-button').disabled,true);assert.equal(f.el('next-action').disabled,false);
});
test('before 50 seconds no sample clauses or receipt are exposed and review is disabled',async()=>{
  const value=state(review({cases:['P01','P02','P03','P04'].map(case_id=>({case_id,available:false}))}));value.publication.event_time.through_ms=0;const f=fixture(value);await flush();
  assert.equal(f.el('copy-case').disabled,true);assert.ok(f.el('copy-case').children.every(row=>row.disabled));assert.equal(f.el('copy-advice').hidden,true);assert.equal(f.el('copy-raw').textContent,'');assert.equal(f.el('copy-clauses').children.length,0);assert.match(f.el('copy-availability').textContent,/Show the moment first/);
  await f.click('copy-review-button');assert.equal(posts(f).length,0);
});
test('review uses exact command with CSRF, same-origin session credentials and operation ID',async()=>{
  const f=fixture(state(),(url,options)=>url==='/api/control'?ok(state(review({status:'reviewed',advice:advice()}))):undefined);await flush();await f.click('copy-review-button');
  assert.deepEqual(posts(f),[{body:{action:'review_copy',case_id:'P03',operation_id:'operation-1'},headers:{'Content-Type':'application/json','X-CSRF-Token':'session-csrf'},credentials:'same-origin'}]);assert.equal(f.el('copy-approve').disabled,false);assert.match(f.el('action-status').textContent,/No model call/);
});
test('literal original wording, keep/drop and evidence are shown separately from mismatched recorded reason',async()=>{
  const result=advice({raw_reason:'numeric_mismatch',deterministic_classification:{reason:'stale_correction',explanation:'Goal withdrawn; the on-target shots remain.',evidence_ids:['e010']}});result.clauses[0].text='<img src=x onerror=run()> original wording';
  const f=fixture(state(review({status:'reviewed',advice:result})));await flush();assert.match(visibleText(f.el('copy-clauses')),/Keep C1.*<img src=x onerror=run\(\)> original wording.*Drop C2/);assert.match(visibleText(f.el('copy-facts')),/2 shots, both on target.*e010 revision 1.*1 of 1/);
  assert.match(f.el('copy-recorded-reason').textContent,/numeric mismatch/);assert.match(f.el('copy-checked-reason').textContent,/Goal withdrawn/);assert.equal(f.el('copy-raw-details').open,false);assert.match(f.el('copy-raw').textContent,/"new_model_calls": 0/);assert.match(f.el('copy-evaluation').textContent,/NO_GO/);
});
test('approval saves exact producer wording without changing current broadcast card or primary step',async()=>{
  const result=advice(),initial=state(review({status:'reviewed',advice:result}));const approved={...initial,copy_review:review({status:'approved_copy_draft',advice:{...result,can_approve:false},producer_copy_draft:{advice_id:result.advice_id,case_id:'P03',text:'Harbor have two shots on target.'}})};
  const f=fixture(initial,(url)=>url==='/api/control'?ok(approved):undefined);await flush();const card=f.el('card-text').textContent,step=f.el('next-action').textContent;await f.click('copy-approve');
  assert.equal(posts(f)[0].body.action,'approve_copy');assert.equal(posts(f)[0].body.advice_id,'recorded-P03-current');assert.equal(f.el('copy-approved').hidden,false);assert.equal(f.el('copy-approved-text').textContent,'Harbor have two shots on target.');assert.equal(f.el('card-text').textContent,card);assert.notEqual(f.el('next-action').textContent,step);assert.match(f.el('next-action').textContent,/Correct the goal/);assert.match(f.el('action-status').textContent,/not transmitted.*unchanged/);assert.equal(f.el('copy-approve').disabled,true);
});
test('withheld, stale, unqualified, mismatched or unavailable advice cannot be approved',async()=>{
  const f=fixture();await flush();
  for(const overrides of [{status:'reviewed',advice:advice({decision:'withhold',can_approve:true})},{status:'stale',advice:advice()},{status:'reviewed',advice:advice({can_approve:false})},{status:'reviewed',advice:advice({decision:'unknown'})},{status:'reviewed',advice:advice({advice_id:''})},{status:'reviewed',advice:advice({case_id:'P04'})}]){
    f.setState(state(review(overrides)));await f.poll();assert.equal(f.el('copy-approve').disabled,true);await f.click('copy-approve');
  }
  f.setState(state(review({status:'reviewed',advice:advice()})));await f.poll();await f.select('copy-case','P01');assert.equal(f.el('copy-approve').disabled,true);assert.match(f.el('copy-status').textContent,/different sample/);assert.equal(posts(f).length,0);
});
test('other language or audience explains English Fan restriction and hides old copy',async()=>{
  const f=fixture(state(review({status:'reviewed',advice:advice()})));await flush();
  for(const presentation of [{audience:'analyst',language:'en'},{audience:'casual',language:'es'}]){
    f.setState(state(review({status:'reviewed',advice:advice()}),presentation));await f.poll();assert.equal(f.el('copy-case').disabled,true);assert.equal(f.el('copy-review-button').disabled,true);assert.equal(f.el('copy-approve').disabled,true);assert.equal(f.el('copy-advice').hidden,true);assert.equal(f.el('copy-raw').textContent,'');assert.match(f.el('copy-availability').textContent,/Fan summary in English only.*not changed automatically/);
  }
  assert.equal(posts(f).length,0);assert.equal(f.el('language').value,'es');
});
test('context changes suppress old advice and approved draft, then offer only matching corrected sample',async()=>{
  const result=advice();const f=fixture(state(review({status:'approved_copy_draft',advice:result,producer_copy_draft:{advice_id:result.advice_id,text:'OLD DRAFT'}})));await flush();await f.select('copy-case','P03');
  f.setState(state(review({status:'stale',advice:result,producer_copy_draft:{advice_id:result.advice_id,text:'OLD DRAFT'},cases:['P01','P02','P03','P04'].map(case_id=>({case_id,available:case_id==='P04'}))})));await f.poll();
  assert.equal(f.el('copy-case').value,'P04');assert.equal(f.el('copy-advice').hidden,true);assert.equal(f.el('copy-approved').hidden,true);assert.equal(f.el('copy-approved-text').textContent,'');assert.equal(f.el('copy-raw').textContent,'');assert.match(f.el('copy-status').textContent,/Facts changed/);assert.equal(f.el('copy-review-button').disabled,false);
});
test('clear review uses protected host command without touching private feedback',async()=>{
  const f=fixture(state(review({status:'reviewed',advice:advice()})),url=>url==='/api/control'?ok(state(review({status:'cleared'}))):undefined);await flush();f.el('feedback-comment').value='Unsaved private feedback';await f.click('copy-clear');
  assert.equal(posts(f)[0].body.action,'clear_copy');assert.equal(posts(f)[0].headers['X-CSRF-Token'],'session-csrf');assert.equal(f.el('copy-advice').hidden,true);assert.equal(f.el('feedback-comment').value,'Unsaved private feedback');assert.ok(!f.requests.some(row=>row.url==='/api/feedback'));
});
test('offline review is visibly cached and cannot be approved until fresh authenticated state',async()=>{
  let offline=false;const f=fixture(state(review({status:'reviewed',advice:advice()})),url=>offline&&url==='/api/state'?Promise.reject(Error('offline')):undefined);await flush();await f.select('copy-case','P03');assert.equal(f.el('copy-approve').disabled,false);
  offline=true;await f.poll();assert.equal(f.el('copy-approve').disabled,true);assert.equal(f.el('copy-review-button').disabled,true);assert.match(f.el('copy-status').textContent,/Cached review.*unavailable/);await f.click('copy-approve');assert.equal(posts(f).length,0);
  offline=false;await f.poll();assert.equal(f.el('copy-approve').disabled,false);
});
test('uncertain review or match-changing command never retries and pauses approval until fresh state',async()=>{
  for(const button of ['copy-approve','action-correct']){
    let fail=true;const f=fixture(state(review({status:'reviewed',advice:advice()})),(url,options)=>url==='/api/control'&&fail?Promise.reject(Object.assign(Error('deadline'),{name:'AbortError'})):undefined);await flush();await f.select('copy-case','P03');await f.click(button);
    assert.equal(posts(f).length,1);assert.equal(f.el('copy-approve').disabled,true);if(button==='copy-approve')assert.match(f.el('copy-status').textContent,/paused until a fresh replay response/);else assert.equal(f.el('copy-status').attributes['aria-live'],'off');await f.click('copy-approve');assert.equal(posts(f).length,1);
    fail=false;await f.poll();assert.equal(f.el('copy-approve').disabled,false);assert.equal(posts(f).length,1);
  }
});
test('HTTP409 keeps cached approval blocked until a fresh state rather than assuming rejection was current',async()=>{
  const f=fixture(state(review({status:'reviewed',advice:advice()})),url=>url==='/api/control'?http(409):undefined);await flush();await f.click('copy-approve');assert.equal(f.el('copy-approve').disabled,true);assert.match(f.el('copy-status').textContent,/Action not confirmed/);assert.equal(f.el('next-action').disabled,false);await f.poll();assert.equal(f.el('copy-approve').disabled,false);
});
test('session expiry disables review and leaves a feedback draft unsent',async()=>{
  const f=fixture(state(review({status:'reviewed',advice:advice()})),url=>url==='/api/control'?http(403):undefined);await flush();f.el('feedback-comment').value='Private unsent draft';await f.click('copy-approve');assert.equal(f.el('copy-approve').disabled,true);assert.equal(f.el('copy-review-button').disabled,true);assert.match(f.el('global-notice').textContent,/session has expired/);assert.equal(f.el('feedback-comment').value,'Private unsent draft');assert.ok(!f.requests.some(row=>row.url==='/api/feedback'));
});
test('recorded disclosure and keyboard focus nodes remain stable on unchanged polls',async()=>{
  const f=fixture(state(review({status:'reviewed',advice:advice()})));await flush();const options=f.el('copy-case').children,clauses=f.el('copy-clauses').children;f.el('copy-raw-details').open=true;await f.poll();assert.equal(f.el('copy-case').children,options);assert.equal(f.el('copy-clauses').children,clauses);assert.equal(f.el('copy-raw-details').open,true);
});
test('missing review evidence fails closed with a bounded explanation and no raw internal error',async()=>{
  const f=fixture(state(review({status:'reviewed',advice:advice(),evidence_error:'internal artifact path must not be shown'})));await flush();
  assert.equal(f.el('copy-advice').hidden,true);assert.equal(f.el('copy-review-button').disabled,true);assert.equal(f.el('copy-approve').disabled,true);assert.match(f.el('copy-availability').textContent,/evidence is unavailable/);assert.doesNotMatch(f.el('copy-availability').textContent,/internal artifact/);assert.equal(f.el('copy-raw').textContent,'');
});
test('hosted structure retains first action, consent/privacy, responsive targets and no iframe-consumer claim',()=>{
  const html=fs.readFileSync(path.join(ROOT,'playtest.html'),'utf8'),css=fs.readFileSync(path.join(ROOT,'site.css'),'utf8');
  assert.ok(html.indexOf('id="next-action"')<html.indexOf('id="copy-review"'));assert.ok(html.indexOf('id="journey-title"')<html.indexOf('id="copy-review"'));assert.match(html,/for="copy-case"/);assert.match(html,/id="copy-status" class="small" role="status" aria-live="off"/);assert.match(html,/Producer-approved draft; not transmitted/);assert.doesNotMatch(html,/<iframe|independent overlay consumer/);
  assert.match(html,/id="feedback-consent"[^>]*required/);assert.doesNotMatch(html,/id="feedback-consent"[^>]*checked/);assert.match(html,/Other testers cannot read your feedback/);assert.match(html,/max-width:|No live provider calls/);assert.match(css,/\.copy-review button,\.copy-review select,\.copy-review summary\{min-height:44px/);assert.match(css,/@media\(max-width:650px\)\{\.copy-start\{grid-template-columns:minmax\(0,1fr\)/);assert.match(css,/summary:focus-visible\{outline:3px/);
});

function correctedState(copy=review({status:'stale',cases:['P01','P02','P03','P04'].map(case_id=>({case_id,available:case_id==='P04'}))})){
  const result=state(copy),before={id:'e010',type:'shot',at_ms:50000,team_id:'harbor',goal:true,on_target:true},after={...before,goal:false};
  result.publication.facts.score.Harbor=0;
  result.envelope.provenance={corrections:[{target_event_id:'e010',from_revision:1,to_revision:2,before,after}],event_revisions:{e010:2,e003:1,e008:1},evidence_records:[after,{id:'e008',type:'shot',at_ms:40000,team_id:'harbor',goal:false,on_target:true},{id:'e003',type:'pass',at_ms:3000,team_id:'meadow'}]};
  return result;
}
function afterAdvice(){return advice({case_id:'P04',advice_id:'recorded-P04-current',raw_reason:'contradicted_fact',deterministic_classification:{reason:'stale_revision',explanation:'The goal was withdrawn in revision 2; the shots remain on target.',evidence_ids:['e010']},clauses:[{id:'C1',text:'Harbor lead one-nil.',disposition:'drop',evidence_ids:['e010']},{id:'C2',text:'Both efforts were on target.',disposition:'keep',evidence_ids:['e008','e010']}],keep:['C2'],drop:['C1']});}
function feedbackDraft(f,comment='Useful correction check'){
  for(const name of ['clarity','usefulness','trust'])f.el('rating-'+name).value='4';
  f.el('feedback-role').value='both';f.el('feedback-comment').value=comment;f.el('feedback-consent').checked=true;
}
async function submitFeedback(f){await f.el('feedback-form').listeners.submit({preventDefault(){}});await flush();}
test('next action alone completes reviews, approval, correction, evidence and recap without optional replay',async()=>{
  let latest=state(review({cases:[]}));latest.publication.event_time.through_ms=0;
  const f=fixture(latest,(url,options)=>{
    if(url!=='/api/control')return;
    const command=JSON.parse(options.body);
    if(command.action==='pattern')latest=state();
    else if(command.action==='review_copy'&&command.case_id==='P03')latest=state(review({status:'reviewed',advice:advice()}));
    else if(command.action==='approve_copy')latest=state(review({status:'approved_copy_draft',advice:{...advice(),can_approve:false},producer_copy_draft:{advice_id:'recorded-P03-current',text:'Harbor have two shots on target.'}}));
    else if(command.action==='correct')latest=correctedState();
    else if(command.action==='review_copy'&&command.case_id==='P04')latest=correctedState(review({status:'reviewed',advice:afterAdvice(),cases:[{case_id:'P04',available:true}]}));
    else if(command.action==='finish'){latest=correctedState();latest.position=20;latest.publication.event_time.through_ms=130000;}
    else throw Error('Unexpected guided command '+command.action);
    return ok(latest);
  });await flush();
  const labels=[/Show the 50s/,/Review the mixed/,/Approve the retained/,/Correct the goal/,/Review copy after/,/Inspect the changed/,/Show the final/];
  f.el('next-action').focus();
  for(const label of labels){await f.settlePrimary();assert.match(f.el('next-action').textContent,label);assert.equal(f.el('next-action').attributes['aria-disabled'],'false');await f.click('next-action');assert.equal(f.context.document.activeElement,f.el('next-action'));}
  assert.match(f.el('next-action').textContent,/Recap ready/);assert.equal(f.el('next-action').attributes['aria-disabled'],'true');assert.equal(f.el('recap-panel').hidden,false);assert.ok(f.el('recap-title').lastScroll);
  assert.deepEqual(posts(f).map(row=>row.body.action),['pattern','review_copy','approve_copy','correct','review_copy','finish']);
  assert.equal(f.el('evidence-panel').hidden,false);assert.ok(f.el('copy-decision').lastScroll);assert.ok(f.el('copy-approved-title').lastScroll);assert.ok(f.el('correction-title').lastScroll);
});
test('primary focus survives busy request and repeated activation cannot duplicate it',async()=>{
  let release;const f=fixture(state(),url=>url==='/api/control'?new Promise(resolve=>{release=resolve;}):undefined);await flush();f.el('next-action').focus();const pending=f.click('next-action');await flush();
  assert.equal(f.el('next-action').disabled,false);assert.equal(f.el('next-action').attributes['aria-disabled'],'true');assert.equal(f.el('next-action').attributes['aria-busy'],'true');assert.equal(f.context.document.activeElement,f.el('next-action'));
  await f.click('next-action');assert.equal(posts(f).length,1);release(ok(state(review({status:'reviewed',advice:advice()}))));await pending;assert.equal(f.context.document.activeElement,f.el('next-action'));assert.match(f.el('next-action').textContent,/Approve the retained/);
});
test('expired card and fresh fallback polls cannot rewind guided progress',async()=>{
  const saved=state(review({status:'approved_copy_draft',advice:{...advice(),can_approve:false},producer_copy_draft:{advice_id:'recorded-P03-current',text:'Harbor have two shots on target.'}}));const f=fixture(saved);await flush();assert.match(f.el('next-action').textContent,/Correct the goal/);
  const expired=structuredClone(saved);expired.publication.issued_at_ms=Date.now()-26000;expired.publication.expires_at_ms=Date.now()-1000;expired.publication.card.fallback=true;f.setState(expired);await f.poll();assert.equal(f.el('preview-content').hidden,true);assert.match(f.el('next-action').textContent,/Correct the goal/);assert.equal(f.el('next-action').attributes['aria-disabled'],'false');
  expired.copy_review=review({status:'stale'});f.setState(expired);await f.poll();assert.match(f.el('next-action').textContent,/Review the mixed/);
});
test('new producer stream resets local guided progress rather than carrying approval across matches',async()=>{
  const saved=state(review({status:'approved_copy_draft',advice:{...advice(),can_approve:false},producer_copy_draft:{advice_id:'recorded-P03-current',text:'Kept wording'}}));const f=fixture(saved);await flush();assert.match(f.el('next-action').textContent,/Correct the goal/);
  const fresh=state();fresh.publication.stream_id='new-match';fresh.publication.event_time.through_ms=0;f.setState(fresh);await f.poll();assert.match(f.el('next-action').textContent,/Show the 50s/);fresh.publication.event_time.through_ms=50000;f.setState(fresh);await f.poll();assert.match(f.el('next-action').textContent,/Review the mixed/);
});
test('copy live status is quiet before use and activates only after panel interaction',async()=>{
  const f=fixture();await flush();assert.equal(f.el('copy-status').attributes['aria-live'],'off');assert.equal(f.el('copy-status').textContent,'');await f.select('copy-case','P03');assert.equal(f.el('copy-status').attributes['aria-live'],'polite');assert.match(f.el('copy-status').textContent,/Choose an available/);
});
test('changed evidence is grouped first and remaining events keep chronological times',async()=>{
  const f=fixture(correctedState());await flush();const groups=f.el('evidence-list').children;assert.equal(groups.length,2);assert.match(visibleText(groups[0]),/Changed by the approved correction.*e010: revision 2.*50s: Shot/);assert.match(visibleText(groups[1]),/Other visible events, in time order.*e003: revision 1.*3s: Pass.*e008: revision 1.*40s: Shot/);
  assert.equal(f.el('fan-correction-summary').hidden,false);assert.match(f.el('fan-correction-summary').textContent,/goal was removed.*shot on target/);
  const restored=correctedState();restored.envelope.provenance.evidence_records[0].goal=true;restored.envelope.provenance.event_revisions.e010=3;f.setState(restored);await f.poll();assert.equal(f.el('fan-correction-summary').hidden,true);
});
test('P04 mismatch warning is grounded in current revision without changing raw reason or original score',async()=>{
  const result=correctedState(review({status:'reviewed',advice:afterAdvice(),cases:[{case_id:'P04',available:true}]}));const f=fixture(result);await flush();assert.equal(f.el('copy-pilot-warning').hidden,false);assert.match(f.el('copy-pilot-warning').textContent,/right words.*wrong reason.*e010 revision 2.*3\/4 NO_GO/);assert.match(f.el('copy-recorded-reason').textContent,/contradicted fact/);assert.match(f.el('copy-raw').textContent,/"raw_reason": "contradicted_fact"/);assert.match(f.el('copy-evaluation').textContent,/3\/4.*NO_GO/);
});
test('feedback timeout retains payload and ID across retry and displays original duplicate receipt',async()=>{
  const payloads=[];let first=true;const f=fixture(state(),(url,options)=>{if(url!=='/api/feedback')return;payloads.push(JSON.parse(options.body));if(first){first=false;return Promise.reject(Object.assign(Error('deadline'),{name:'AbortError'}));}return ok({saved:true,receipt_id:'receipt_test_01',duplicate:true});});await flush();feedbackDraft(f);await submitFeedback(f);assert.equal(f.el('feedback-form').didReset,undefined);assert.match(f.el('feedback-status').textContent,/retained/);f.context.window.innerWidth=1280;await submitFeedback(f);
  assert.deepEqual(payloads[1],payloads[0]);assert.equal(payloads[0].viewport,'phone');assert.match(payloads[0].feedback_id,/operation-/);assert.match(f.el('feedback-receipt').textContent,/receipt_test_01.*no duplicate/);assert.equal(f.el('feedback-form').didReset,true);
});
test('feedback edits get a new ID, pending duplicate clicks are blocked, and no receipt is invented',async()=>{
  const payloads=[];let release;const f=fixture(state(),(url,options)=>{if(url!=='/api/feedback')return;payloads.push(JSON.parse(options.body));return new Promise(resolve=>{release=resolve;});});await flush();feedbackDraft(f);const pending=submitFeedback(f);await flush();assert.equal(f.el('feedback-submit').disabled,true);await submitFeedback(f);assert.equal(payloads.length,1);release(http(500));await pending;assert.equal(f.el('feedback-form').didReset,undefined);assert.equal(f.el('feedback-receipt').textContent,'');
  f.el('feedback-comment').value='A genuinely edited submission';const second=submitFeedback(f);await flush();assert.notEqual(payloads[0].feedback_id,payloads[1].feedback_id);release(ok({saved:true,receipt_id:'receipt_edited',duplicate:false}));await second;assert.match(f.el('feedback-receipt').textContent,/receipt_edited/);
});


test('timeout before approval returns primary to P03 review and can advance again',async()=>{
  let latest=state(review({cases:[]}));latest.publication.event_time.through_ms=0;
  const f=fixture(latest,(url,options)=>{
    if(url!=='/api/control')return;
    const command=JSON.parse(options.body);
    if(command.action==='pattern')latest=state();
    if(command.action==='review_copy')latest=state(review({status:'reviewed',advice:advice()}));
    if(command.action==='timeout'){latest=state(review({status:'cleared'}));latest.recorded_replay.status='injected_timeout';}
    return ok(latest);
  });await flush();await f.click('next-action');await f.settlePrimary();await f.click('next-action');assert.match(f.el('next-action').textContent,/Approve the retained/);
  await f.click('action-timeout');assert.equal(f.el('copy-advice').hidden,true);assert.match(f.el('next-action').textContent,/Review the mixed/);await f.settlePrimary();assert.equal(f.el('next-action').attributes['aria-disabled'],'false');
  await f.settlePrimary();await f.click('next-action');assert.equal(posts(f).at(-1).body.action,'review_copy');assert.equal(posts(f).at(-1).body.case_id,'P03');assert.match(f.el('next-action').textContent,/Approve the retained/);await f.settlePrimary();assert.equal(f.el('next-action').attributes['aria-disabled'],'false');
});
test('presentation round-trip before approval offers a fresh P03 review',async()=>{
  const f=fixture(state(review({status:'reviewed',advice:advice()})),(url,options)=>{
    if(url!=='/api/control')return;
    const command=JSON.parse(options.body);
    if(command.action==='review_copy')return ok(state(review({status:'reviewed',advice:advice()})));
    return ok(state(review({status:'stale',cases:command.language==='en'?review().cases:[]}),{audience:command.audience,language:command.language}));
  });await flush();await f.select('language','es');assert.match(f.el('next-action').textContent,/English Fan/);await f.select('language','en');assert.match(f.el('next-action').textContent,/Review the mixed/);assert.equal(f.el('next-action').attributes['aria-disabled'],'false');
  await f.click('next-action');assert.equal(posts(f).at(-1).body.case_id,'P03');assert.match(f.el('next-action').textContent,/Approve the retained/);
});
test('replacing pending P03 advice with another sample cannot strand primary approval',async()=>{
  const f=fixture(state(review({status:'reviewed',advice:advice()})),(url,options)=>{
    if(url!=='/api/control')return;
    const command=JSON.parse(options.body);
    return ok(state(review({status:'reviewed',advice:advice(command.case_id==='P01'?{case_id:'P01',advice_id:'P01-advice',decision:'allow'}:{})})));
  });await flush();await f.select('copy-case','P01');await f.click('copy-review-button');assert.match(f.el('next-action').textContent,/Review the mixed/);assert.equal(f.el('next-action').attributes['aria-disabled'],'false');
  await f.click('next-action');assert.equal(posts(f).at(-1).body.case_id,'P03');assert.match(f.el('next-action').textContent,/Approve the retained/);
});
test('reopened new stream clears pending approval and offers fresh current P03 review',async()=>{
  const f=fixture(state(review({status:'reviewed',advice:advice()})),(url,options)=>{
    if(url!=='/api/control')return;
    const command=JSON.parse(options.body),reopened=state(review(command.action==='review_copy'?{status:'reviewed',advice:advice()}:{status:'cleared'}));
    reopened.publication.stream_id='reopened-controller-stream';return ok(reopened);
  });await flush();await f.click('action-recover');assert.match(f.el('next-action').textContent,/Review the mixed/);assert.equal(f.el('next-action').attributes['aria-disabled'],'false');
  await f.click('next-action');assert.equal(posts(f).at(-1).body.case_id,'P03');assert.match(f.el('next-action').textContent,/Approve the retained/);
});


test('rapid repeated evidence activation cannot dispatch recap before the cooldown',async()=>{
  const initial=correctedState(review({status:'reviewed',advice:afterAdvice(),cases:[{case_id:'P04',available:true}]}));
  const f=fixture(initial,(url,options)=>url==='/api/control'?ok({...initial,position:20}):undefined);await flush();
  assert.match(f.el('next-action').textContent,/6\. Inspect/);f.el('next-action').focus();
  await f.click('next-action');await f.click('next-action');await f.click('next-action');
  assert.equal(f.el('evidence-panel').hidden,false);assert.ok(f.el('evidence-title').lastScroll);
  assert.match(f.el('next-action').textContent,/7\. Show/);assert.equal(posts(f).length,0);
  assert.equal(f.el('next-action').attributes['aria-disabled'],'true');assert.equal(f.context.document.activeElement,f.el('next-action'));
  await f.settlePrimary();assert.equal(f.el('next-action').attributes['aria-disabled'],'false');
  await f.click('next-action');assert.equal(posts(f).length,1);assert.equal(posts(f)[0].body.action,'finish');
});
test('P04 warning never substitutes a mismatch when the reason agrees or revision is not current',async()=>{
  const matches=afterAdvice();matches.raw_reason='stale_revision';
  const f=fixture(correctedState(review({status:'reviewed',advice:matches,cases:[{case_id:'P04',available:true}]})));await flush();
  assert.equal(f.el('copy-pilot-warning').hidden,true);
  const later=correctedState(review({status:'reviewed',advice:afterAdvice(),cases:[{case_id:'P04',available:true}]}));
  later.envelope.provenance.event_revisions.e010=3;f.setState(later);await f.poll();assert.equal(f.el('copy-pilot-warning').hidden,true);
});
test('P04 optional approval stays secondary and guide surface is opaque',async()=>{
  const f=fixture(correctedState(review({status:'reviewed',advice:afterAdvice(),cases:[{case_id:'P04',available:true}]})));await flush();
  assert.match(f.el('copy-approve').textContent,/Optional/);
  const html=fs.readFileSync(path.join(ROOT,'playtest.html'),'utf8'),css=fs.readFileSync(path.join(ROOT,'site.css'),'utf8');
  assert.doesNotMatch(html,/id="copy-approve"[^>]*class="primary"/);assert.match(css,/background:#102c2f;/);assert.doesNotMatch(css,/#102c2ff5/);
});
test('injected timeout reveals cleared-advice proof and retained score without claiming a live failure',async()=>{
  const initial=state(review({status:'reviewed',advice:advice()}));
  const cleared=state(review({status:'cleared',advice:null,producer_copy_draft:null}));cleared.recorded_replay.status='injected_timeout';
  const f=fixture(initial,url=>url==='/api/control'?ok(cleared):undefined);await flush();await f.click('action-timeout');
  assert.equal(f.el('copy-recovery-result').hidden,false);assert.equal(f.el('copy-advice').hidden,true);assert.equal(f.el('copy-approved').hidden,true);
  assert.match(f.el('copy-recovery-facts').textContent,/Checked score retained/);assert.ok(f.el('copy-recovery-title').lastScroll);
  assert.match(f.el('action-status').textContent,/Simulated timeout/);
  f.setState(initial);await f.poll();assert.equal(f.el('copy-recovery-result').hidden,true);
});
const LABELS=['1. Show the 50s moment','2. Review the mixed draft','3. Approve the retained wording','4. Correct the goal','5. Review copy after the correction','6. Inspect the changed evidence','7. Show the final recap','Recap ready'];
// An independent tiny fixture models factual actions, not UI next-step logic.
// Each matrix row drives the same shipped DOM handler used by real browsers.
function journeyModel(){
  let through=0,corrected=false,seq=1,stream=1,audience='casual',language='en',mode='fallback',expired=false,copy=review({cases:[]});
  function snapshot(){
    const atReview=through===50000&&audience==='casual'&&language==='en';
    const cases=['P01','P02','P03','P04'].map(case_id=>({case_id,available:atReview&&(corrected?case_id==='P04':case_id!=='P04')}));
    const value=corrected?correctedState({...copy,cases}):state({...copy,cases});
    value.publication.sequence=seq;value.publication.stream_id='model-stream-'+stream;
    if(expired){value.publication.issued_at_ms=Date.now()-31000;value.publication.expires_at_ms=Date.now()-1;}
    value.publication.event_time.through_ms=through;value.position=through===0?0:through===130000?20:10;
    value.publication.facts.score={Harbor:corrected?0:through>=50000?1:0,Meadow:through===130000?1:0};
    value.audience=audience;value.language=language;value.publication.card.language=language;
    value.publication.card.text=language==='es'?'Datos ficticios comprobados.':'Checked fictional facts.';
    value.recorded_replay={available:through===50000&&!corrected,status:mode};
    if(through===0)value.envelope.provenance.evidence_records=[];
    return value;
  }
  function invalidate(status='cleared'){copy=review({status,advice:null,producer_copy_draft:null});}
  return{snapshot,expirePreview(){expired=true;},async handle(url,options){
    if(url==='/api/state')return ok(snapshot());
    if(url!=='/api/control')return;
    const c=JSON.parse(options.body);seq++;
    if(c.action==='pattern'){if(through!==50000)invalidate('stale');through=50000;mode='fallback';}
    else if(c.action==='correct'){assert.equal(through,50000);assert.equal(corrected,false);corrected=true;invalidate('stale');}
    else if(c.action==='finish'){through=130000;invalidate('stale');}
    else if(c.action==='reset'){through=0;invalidate('stale');}
    else if(c.action==='new_match'){through=0;corrected=false;stream++;invalidate('idle');}
    else if(c.action==='recover'){stream++;mode='recovered_fallback';invalidate();}
    else if(c.action==='timeout'){mode='injected_timeout';invalidate();}
    else if(c.action==='clear_copy')invalidate();
    else if(c.action==='view'){if(audience!==c.audience||language!==c.language)invalidate('stale');audience=c.audience;language=c.language;}
    else if(c.action==='review_copy'){
      assert.equal(snapshot().copy_review.cases.find(row=>row.case_id===c.case_id)?.available,true);
      copy=review({status:'reviewed',advice:c.case_id==='P04'?afterAdvice():advice()});
    }else if(c.action==='approve_copy'){
      assert.equal(copy.status,'reviewed');assert.equal(copy.advice.advice_id,c.advice_id);assert.equal(copy.advice.can_approve,true);
      const kept={...copy.advice,can_approve:false};copy=review({status:'approved_copy_draft',advice:kept,producer_copy_draft:{advice_id:kept.advice_id,text:'Retained supported wording.'}});
    }else throw Error('Unexpected model command '+c.action);
    return ok(snapshot());
  }};
}
async function reachStage(stage){
  const model=journeyModel(),f=fixture(model.snapshot(),model.handle);await flush();
  for(let i=0;i<stage;i++){await f.settlePrimary();assert.equal(f.el('next-action').textContent,LABELS[i]);await f.click('next-action');}
  await f.settlePrimary();assert.equal(f.el('next-action').textContent,LABELS[stage]);
  return{f,model};
}
const perturbations=['timeout','recover','clear','reset','newmatch','presentation','evidence-open-close','preview-expiry','client-reload','rapid-primary'];
for(let stage=0;stage<LABELS.length;stage++)for(const perturbation of perturbations){
  test(`journey state ${stage}: ${perturbation} preserves a truthful usable route`,async()=>{
    let{f,model}=await reachStage(stage);const before=model.snapshot(),beforeCount=posts(f).length;
    let expected=stage;
    if(['timeout','recover','clear'].includes(perturbation)){
      await f.click(perturbation==='clear'?'copy-clear':'action-'+perturbation);
      // The clear control is intentionally disabled when no active advice exists.
      expected=stage===0?0:stage===7?7:stage<4?1:4;
      if(perturbation==='clear'&&![2,3,5,6].includes(stage))expected=stage;
      assert.equal(f.el('copy-approved').hidden,true);
      if(perturbation!=='clear'||[2,3,5,6].includes(stage))assert.equal(f.el('copy-advice').hidden,true);
      if(perturbation==='recover'&&stage===7){assert.ok(f.el('recap-title').lastScroll);assert.match(f.el('action-status').textContent,/final moment.*recap.*Rewind/);}
    }else if(perturbation==='reset'||perturbation==='newmatch'){
      await f.click(perturbation==='reset'?'action-reset':'new-match-confirm');expected=0;
      await f.settlePrimary();await f.click('next-action');expected=perturbation==='reset'&&stage>=4?4:1;
      assert.equal(model.snapshot().envelope.provenance.event_revisions.e010===2,perturbation==='reset'&&stage>=4);
    }else if(perturbation==='presentation'){
      await f.select('language','es');
      if(stage>0&&stage<7){assert.match(f.el('next-action').textContent,/English Fan/);assert.equal(f.el('next-action').attributes['aria-disabled'],'true');}
      assert.equal(f.el('copy-approved').hidden,true);await f.select('language','en');expected=stage===0?0:stage===7?7:stage<4?1:4;
    }else if(perturbation==='evidence-open-close'){
      await f.click('inspect-evidence');await f.click('inspect-evidence');
      expected=stage===5?6:stage;
      // Having opened original evidence must not count as inspecting its revision.
      if(stage===3){await f.settlePrimary();await f.click('next-action');await f.settlePrimary();await f.click('next-action');expected=5;}
    }else if(perturbation==='preview-expiry'){
      model.expirePreview();await f.poll();f.intervals[0].callback();
      assert.equal(f.el('preview-content').hidden,true);assert.equal(f.el('next-action').textContent,LABELS[stage]);
    }else if(perturbation==='client-reload'){
      f=fixture(model.snapshot(),model.handle);await flush();expected=stage===6?5:stage;
    }else if(perturbation==='rapid-primary'){
      f.el('next-action').focus();await Promise.all([f.click('next-action'),f.click('next-action'),f.click('next-action')]);
      expected=stage===7?7:stage+1;
      const commands=posts(f).slice(beforeCount);assert.equal(commands.length,stage===5||stage===7?0:1);
      assert.equal(f.context.document.activeElement,f.el('next-action'));
    }
    await f.settlePrimary();assert.equal(f.el('next-action').textContent,LABELS[expected]);
    assert.equal(f.el('next-action').attributes['aria-disabled'],String(expected===7));
    assert.equal(f.el('next-action').disabled,false);
    const after=model.snapshot();
    if(!['newmatch'].includes(perturbation)&&before.envelope.provenance.event_revisions.e010===2)assert.equal(after.envelope.provenance.event_revisions.e010,2);
    if(expected===7){assert.equal(f.el('recap-panel').hidden,false);await f.click('action-reset');await f.settlePrimary();await f.click('next-action');assert.equal(f.el('next-action').textContent,LABELS[4]);}
  });
}

test('distant nonfinal copied-review moment offers actionable return to50s rather than a disabled step',async()=>{
  const distant=correctedState();distant.publication.event_time.through_ms=90000;distant.position=15;distant.copy_review.cases=[];
  const f=fixture(distant,url=>url==='/api/control'?ok(correctedState()):undefined);await flush();
  assert.match(f.el('next-action').textContent,/Return to the 50s/);assert.equal(f.el('next-action').attributes['aria-disabled'],'false');
  await f.click('next-action');assert.equal(posts(f)[0].body.action,'pattern');assert.equal(f.el('next-action').textContent,LABELS[4]);
});

test('malformed approved status cannot bypass a real identified producer draft',async()=>{
  for(const mutation of ['missing-advice-id','empty-advice-id','missing-draft','different-draft-id']){
    const value=state(review({status:'approved_copy_draft',advice:{...advice(),can_approve:false},producer_copy_draft:{advice_id:'recorded-P03-current',text:'Kept wording'}}));
    if(mutation==='missing-advice-id'){delete value.copy_review.advice.advice_id;value.copy_review.producer_copy_draft=null;}
    if(mutation==='empty-advice-id'){value.copy_review.advice.advice_id='';value.copy_review.producer_copy_draft.advice_id='';}
    if(mutation==='missing-draft')value.copy_review.producer_copy_draft=null;
    if(mutation==='different-draft-id')value.copy_review.producer_copy_draft.advice_id='different';
    const f=fixture(value);await flush();assert.equal(f.el('next-action').textContent,LABELS[1],mutation);
  }
});
test('unconfirmed correction blocks every replay mutation until a fresh state is confirmed',async()=>{
  let fail=true;const saved=state(review({status:'approved_copy_draft',advice:{...advice(),can_approve:false},producer_copy_draft:{advice_id:'recorded-P03-current',text:'Kept wording'}}));
  const f=fixture(saved,url=>url==='/api/control'&&fail?http(409):undefined);await flush();
  await f.click('next-action');await f.settlePrimary();assert.equal(posts(f).length,1);
  assert.equal(f.el('next-action').attributes['aria-disabled'],'true');assert.match(f.el('next-action-help').textContent,/Waiting for a fresh/);
  for(const action of ['next-action','action-correct','action-reset','action-timeout','action-recover'])await f.click(action);
  assert.equal(posts(f).length,1);fail=false;await f.poll();assert.equal(f.el('next-action').attributes['aria-disabled'],'false');
  await f.click('next-action');assert.equal(posts(f).length,2);
});

test('new-match dialog cancel preserves corrected match and returns keyboard focus without a request',async()=>{
  const {f,model}=await reachStage(6),before=posts(f).length,facts=model.snapshot().publication.facts;
  await f.click('new-match');assert.equal(f.el('new-match-confirmation').hidden,false);assert.equal(f.context.document.activeElement,f.el('new-match-cancel'));
  await f.click('new-match-cancel');assert.equal(f.el('new-match-confirmation').hidden,true);assert.equal(f.context.document.activeElement,f.el('new-match'));
  assert.equal(posts(f).length,before);assert.deepEqual(model.snapshot().publication.facts,facts);assert.equal(f.el('next-action').textContent,LABELS[6]);
});

test('Spanish and English fan explanations use the same current corrected goal and retained shot facts',async()=>{
  for(const onTarget of [true,false])for(const language of ['en','es']){
    const value=correctedState();value.language=language;value.envelope.provenance.evidence_records[0].on_target=onTarget;
    const f=fixture(value);await flush();assert.equal(f.el('fan-correction-summary').hidden,false);assert.equal(f.el('fan-correction-summary').lang,language);
    const text=f.el('fan-correction-summary').textContent;
    if(language==='en')assert.equal(text,`The goal was removed from the score. The attempt still counts as ${onTarget?'a shot on target':'a shot'}.`);
    else assert.equal(text,`El gol se anuló en el marcador. El intento sigue contando como ${onTarget?'un tiro a puerta':'un tiro'}.`);
    assert.deepEqual(value.publication.facts.score,{Harbor:0,Meadow:0});assert.equal(posts(f).length,0);
  }
});
test('Spanish correction explanation fails closed for wrong audience, future evidence or mismatched revision',async()=>{
  for(const mutation of ['analyst','future','revision','restored-goal']){
    const value=correctedState();value.language='es';
    if(mutation==='analyst')value.audience='analyst';
    if(mutation==='future')value.publication.event_time.through_ms=0;
    if(mutation==='revision')value.envelope.provenance.event_revisions.e010=3;
    if(mutation==='restored-goal')value.envelope.provenance.evidence_records[0].goal=true;
    const f=fixture(value);await flush();assert.equal(f.el('fan-correction-summary').hidden,true,mutation);assert.equal(f.el('fan-correction-summary').textContent,'');
  }
});
test('network TypeError uses uncertainty wording and paused writes until committed facts reconcile',async()=>{
  let lost=true;const saved=state(review({status:'approved_copy_draft',advice:{...advice(),can_approve:false},producer_copy_draft:{advice_id:'recorded-P03-current',text:'Kept wording'}}));
  const f=fixture(saved,(url)=>url==='/api/control'&&lost?Promise.reject(new TypeError('Failed to fetch')):undefined);await flush();
  await f.click('next-action');await f.settlePrimary();assert.match(f.el('global-notice').textContent,/outcome is uncertain.*refreshed facts/);assert.doesNotMatch(f.el('global-notice').textContent,/Failed to fetch/);
  for(const id of ['next-action','action-correct','action-timeout'])await f.click(id);assert.equal(posts(f).length,1);
  lost=false;f.setState(correctedState());await f.poll();assert.equal(f.el('next-action').textContent,LABELS[4]);assert.equal(f.el('next-action').attributes['aria-disabled'],'false');assert.equal(posts(f).length,1);assert.equal(f.el('copy-approved').hidden,true);
});
