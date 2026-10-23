'use strict';
// DOM stubs exercise state and request contracts. They do not qualify browser layout.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const ROOT=__dirname;
function copyReview(overrides={}){
  return {mode:'recorded',live_available:false,evaluation:{strict_passes:3,total:4,status:'NO_GO',qualification:'Recorded pilot; reason mismatch preserved'},cases:['P01','P02','P03','P04'].map(case_id=>({case_id,available:case_id!=='P04',...(case_id==='P04'?{unavailable_reason:'The corrected facts do not match this snapshot.'}:{label:`Recorded producer draft ${case_id}`})})),advice:null,producer_copy_draft:null,status:'idle',...overrides};
}
function advice(overrides={}){
  return {advice_id:'recorded-advice-P03',case_id:'P03',binding:{snapshot_digest:'current-digest',watermark_ms:50000},decision:'revise',clauses:[{id:'C1',text:'Harbor have two shots on target.',disposition:'keep',evidence_ids:['e008','e010']},{id:'C2',text:'Meadow have not completed a pass.',disposition:'drop',evidence_ids:['e003']}],keep:['C1'],drop:['C2'],facts:[{fact_id:'F_SHOTS',text:'Harbor have had 2 shots, both on target.',evidence_ids:['e008','e010'],event_revisions:{e008:1,e010:1}},{fact_id:'F_PASS',text:'Meadow have completed 1 of 1 attempted passes.',evidence_ids:['e003'],event_revisions:{e003:1}}],raw_reason:'numeric_mismatch',deterministic_classification:{reason:'numeric_mismatch',explanation:'Meadow completed one pass, so drop the contrary clause.',evidence_ids:['e003']},recorded_trace:[{source:'agent_framework',event:'recorded_result'}],receipt_sha256:'a'.repeat(64),can_approve:true,...overrides};
}
function state(review=copyReview()){
  return {publication:{facts:{score:{Harbor:1,Meadow:0}},event_time:{through_ms:50000},sequence:2,retracts:[],fact_id:'fact_current',stream_id:'same'},recorded_replay:{label:'facts',available:true,unavailable_reason:''},audience:'casual',language:'en',position:10,positions:21,recap:{views:{casual:{en:'English recap',es:'Spanish recap'},analyst:{en:'English analyst',es:'Spanish analyst'}},recorded_receipt_count:2,recorded_moment_count:1,withdrawn_claims:[],recap_id:'recap'},envelope:{provenance:{evidence_records:[],event_revisions:{}}},recovery_info:{},...(review===undefined?{}:{copy_review:review})};
}
function fixture(fetcher){
  const elements=new Map(),timers=[],requests=[],windowListeners={},origin='http://127.0.0.1:8770';let operation=0;
  function el(id){
    if(!elements.has(id)){
      const node={id,textContent:'',hidden:true,open:false,value:'',disabled:false,attributes:{},children:[],listeners:{},style:{},contentWindow:{frame:id},srcWrites:[],replaceChildren(...nodes){this.children=[...nodes];},append(...nodes){this.children.push(...nodes);},replaceWith(replacement){elements.set(this.id,replacement);},scrollIntoView(){},setAttribute(key,value){this.attributes[key]=value;},addEventListener(event,listener){this.listeners[event]=listener;}};
      let normalized='';Object.defineProperty(node,'src',{get(){return normalized;},set(value){normalized=new URL(value,origin).href;this.srcWrites.push(normalized);}});
      Object.defineProperty(node,'innerHTML',{set(){throw Error('Untrusted review content must never use innerHTML');}});
      elements.set(id,node);
    }
    return elements.get(id);
  }
  el('overlay').src='/overlay.html';
  const context=vm.createContext({Date,document:{getElementById:el,querySelectorAll:selector=>selector==='button,select'?[...elements.values()].filter(node=>['replay-button','audience','language','copy-case','copy-review-button','copy-approve','copy-clear'].includes(node.id)):[],createElement:()=>el(`created-${elements.size}`),createTextNode:text=>text},window:{location:{origin},addEventListener(name,listener){windowListeners[name]=listener;}},crypto:{randomUUID:()=>`operation-${++operation}`},AbortSignal:{timeout:ms=>({timeoutMs:ms})},setTimeout(fn){timers.push(fn);},fetch:(url,options)=>{requests.push({url,options});return fetcher(url,options);}});
  vm.runInContext(fs.readFileSync(path.join(ROOT,'desk.js'),'utf8'),context);
  return {el,context,timers,requests,render(value){return vm.runInContext(`render(${JSON.stringify(value)})`,context);},poll(){return vm.runInContext('poll()',context);},control(value){return vm.runInContext(`control(${JSON.stringify(value)})`,context);},ack(value){windowListeners.message({origin,source:el('overlay').contentWindow,data:{type:'touchline.overlay.status.v1',stream_id:value.publication.stream_id,sequence:value.publication.sequence,status:'insight',active:true,quarantined:false}});}};
}
const flush=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
const response=value=>({ok:true,json:async()=>value});
function text(node){return [node.textContent||'',...(node.children||[]).map(child=>typeof child==='string'?child:text(child))].join(' ');}
function selected(f,value){f.el('copy-case').value=value;f.el('copy-case').listeners.change();}
const mutations=f=>f.requests.filter(row=>row.options?.method==='POST').map(row=>JSON.parse(row.options.body));

test('older producer without copy_review keeps advisory hidden and existing controls usable',async()=>{
  const value=state();delete value.copy_review;const f=fixture(()=>Promise.resolve(response(value)));await flush();
  assert.equal(f.el('copy-review').hidden,true);assert.equal(f.el('copy-review-button').disabled,true);assert.equal(f.el('copy-approve').disabled,true);
  assert.equal(f.el('replay-button').disabled,false);assert.equal(f.requests.length,1);assert.equal(mutations(f).length,0);
});
test('before matching watermark, cases are disabled and no draft or receipt leaks',async()=>{
  const review=copyReview({cases:['P01','P02','P03','P04'].map(case_id=>({case_id,available:false,unavailable_reason:'Not at the matching 50s snapshot.'}))});
  const value=state(review);value.publication.event_time.through_ms=0;const f=fixture(()=>Promise.resolve(response(value)));await flush();
  assert.equal(f.el('copy-case').disabled,true);assert.ok(f.el('copy-case').children.every(option=>option.disabled));assert.equal(f.el('copy-review-button').disabled,true);assert.equal(f.el('copy-advice').hidden,true);assert.equal(f.el('copy-raw').textContent,'');assert.equal(f.el('copy-approved-text').textContent,'');
  assert.match(f.el('copy-evaluation').textContent,/3\/4 strict passes.*NO_GO/);assert.match(f.el('copy-mode').textContent,/Live review is unavailable/);
  await f.el('copy-review-button').listeners.click();assert.equal(mutations(f).length,0);
});
test('available cases preserve selection across polls and switch safely when context changes',async()=>{
  const f=fixture(()=>Promise.resolve(response(state())));await flush();selected(f,'P03');const options=f.el('copy-case').children;
  f.render(state());assert.equal(f.el('copy-case').value,'P03');assert.equal(f.el('copy-case').children,options);
  const corrected=copyReview({cases:['P01','P02','P03','P04'].map(case_id=>({case_id,available:case_id==='P04'})),status:'stale'});f.render(state(corrected));
  assert.equal(f.el('copy-case').value,'P04');assert.ok(f.el('copy-case').children.filter(row=>row.value!=='P04').every(row=>row.disabled));assert.match(f.el('copy-status').textContent,/Facts changed/);assert.equal(f.el('copy-approve').disabled,true);
});
test('review button uses existing control with exact case and fresh operation ID, no provider route',async()=>{
  const next=state(copyReview({status:'reviewed',advice:advice({case_id:'P02',decision:'withhold',can_approve:false})}));
  const f=fixture((url,options)=>Promise.resolve(response(options?.method==='POST'?next:state())));await flush();selected(f,'P02');await f.el('copy-review-button').listeners.click();
  assert.deepEqual(mutations(f),[{action:'review_copy',case_id:'P02',operation_id:'operation-1'}]);assert.ok(f.requests.every(row=>['/api/state','/api/control'].includes(row.url)));assert.equal(f.el('copy-approve').disabled,true);
});
test('original clauses, keep/drop, facts and distinct reviewer/check reasons are readable literal text',async()=>{
  const result=advice({raw_reason:'numeric_mismatch',deterministic_classification:{reason:'stale_correction',explanation:'The goal was corrected; the shots remain valid.',evidence_ids:['e010']}});result.clauses[0].text='<img src=x onerror=run()> & original wording';
  const f=fixture(()=>Promise.resolve(response(state(copyReview({status:'reviewed',advice:result})))));await flush();selected(f,'P03');
  assert.equal(f.el('copy-advice').hidden,false);assert.match(text(f.el('copy-clauses')),/Keep C1.*<img src=x onerror=run\(\)> & original wording.*Drop C2/);
  assert.match(text(f.el('copy-facts')),/2 shots, both on target.*e010 revision 1.*completed 1 of 1/);assert.match(f.el('copy-recorded-reason').textContent,/numeric mismatch/);assert.match(f.el('copy-checked-reason').textContent,/goal was corrected/);
  assert.equal(f.el('copy-raw-details').open,false);assert.match(f.el('copy-raw').textContent,/"new_model_calls": 0/);assert.match(f.el('copy-raw').textContent,/agent_framework/);assert.equal(f.el('copy-approve').disabled,false);assert.match(f.el('copy-evaluation').textContent,/NO_GO/);
});
test('approval gates reject withhold, stale, unavailable, unqualified and mismatched selected cases',async()=>{
  const f=fixture(()=>Promise.resolve(response(state())));await flush();
  for(const overrides of [{status:'reviewed',advice:advice({decision:'withhold',can_approve:true})},{status:'stale',advice:advice()},{status:'reviewed',advice:advice({can_approve:false})},{status:'reviewed',advice:advice({decision:'anything'})},{status:'reviewed',advice:advice({advice_id:''})},{status:'reviewed',advice:advice({case_id:'P04'})}]){
    f.render(state(copyReview(overrides)));selected(f,'P03');assert.equal(f.el('copy-approve').disabled,true);await f.el('copy-approve').listeners.click();
  }
  f.render(state(copyReview({status:'reviewed',advice:advice()})));selected(f,'P01');assert.equal(f.el('copy-approve').disabled,true);assert.match(f.el('copy-status').textContent,/different draft/);assert.equal(mutations(f).length,0);
});
test('approval saves canonical kept wording without replacing preview or publication facts',async()=>{
  const result=advice(),review=copyReview({status:'reviewed',advice:result});const before=state(review);
  const after=state(copyReview({status:'approved_copy_draft',advice:{...result,can_approve:false},producer_copy_draft:{advice_id:result.advice_id,case_id:'P03',text:'Harbor have two shots on target.'}}));
  const f=fixture((url,options)=>Promise.resolve(response(options?.method==='POST'?after:before)));await flush();selected(f,'P03');f.ack(before);const overlay=f.el('overlay'),score=f.el('score').textContent;
  await f.el('copy-approve').listeners.click();assert.deepEqual(mutations(f),[{action:'approve_copy',advice_id:'recorded-advice-P03',operation_id:'operation-1'}]);assert.equal(f.el('copy-approved').hidden,false);assert.equal(f.el('copy-approved-text').textContent,'Harbor have two shots on target.');
  assert.equal(f.el('overlay'),overlay);assert.equal(overlay.hidden,false);assert.equal(overlay.srcWrites.length,1);assert.equal(f.el('score').textContent,score);assert.equal(f.el('copy-approve').disabled,true);assert.match(f.el('copy-status').textContent,/broadcast preview is unchanged/);
});
test('clear action removes draft and receipt while a stale state defensively suppresses supplied old advice',async()=>{
  const initial=state(copyReview({status:'reviewed',advice:advice()}));const cleared=state(copyReview({status:'cleared'}));
  const f=fixture((url,options)=>Promise.resolve(response(options?.method==='POST'?cleared:initial)));await flush();await f.el('copy-clear').listeners.click();
  assert.deepEqual(mutations(f),[{action:'clear_copy',operation_id:'operation-1'}]);assert.equal(f.el('copy-advice').hidden,true);assert.equal(f.el('copy-raw').textContent,'');assert.equal(f.el('copy-clear').disabled,true);
  f.render(state(copyReview({status:'stale',advice:advice(),producer_copy_draft:{advice_id:'recorded-advice-P03',text:'OLD DRAFT'}})));assert.equal(f.el('copy-advice').hidden,true);assert.equal(f.el('copy-approved').hidden,true);assert.equal(f.el('copy-approved-text').textContent,'');assert.equal(f.el('copy-raw').textContent,'');
});
test('busy review disables duplicate requests and fresh confirmation restores appropriate controls',async()=>{
  let release;const next=state(copyReview({status:'reviewed',advice:advice()}));const f=fixture((url,options)=>options?.method==='POST'?new Promise(resolve=>{release=resolve;}):Promise.resolve(response(state())));await flush();selected(f,'P03');
  const pending=f.el('copy-review-button').listeners.click();assert.equal(f.el('copy-review-button').disabled,true);assert.equal(f.el('copy-case').disabled,true);assert.equal(f.el('copy-approve').disabled,true);await f.el('copy-review-button').listeners.click();assert.equal(mutations(f).length,1);
  release(response(next));await pending;assert.equal(f.el('copy-approve').disabled,false);assert.equal(f.el('copy-case').disabled,false);
});
test('producer loss blocks cached approval until a fresh valid state is received',async()=>{
  let healthy=true;const value=state(copyReview({status:'reviewed',advice:advice()}));const f=fixture(()=>healthy?Promise.resolve(response(value)):Promise.reject(Error('offline')));await flush();selected(f,'P03');assert.equal(f.el('copy-approve').disabled,false);
  healthy=false;await f.poll();assert.equal(f.el('copy-approve').disabled,true);assert.equal(f.el('copy-review-button').disabled,true);assert.match(f.el('copy-status').textContent,/Cached review.*unavailable/);await f.el('copy-approve').listeners.click();assert.equal(mutations(f).length,0);
  healthy=true;await f.poll();assert.equal(f.el('copy-approve').disabled,false);
});
test('uncertain advisory or match-changing command blocks approval, never retries, and awaits a fresh poll',async()=>{
  for(const command of [{action:'approve_copy',advice_id:'recorded-advice-P03'},{action:'correct'}]){
    const value=state(copyReview({status:'reviewed',advice:advice()}));const timeout=Object.assign(Error('deadline'),{name:'TimeoutError'});const f=fixture((url,options)=>options?.method==='POST'?Promise.reject(timeout):Promise.resolve(response(value)));await flush();selected(f,'P03');
    await f.control(command);assert.equal(mutations(f).length,1);assert.equal(f.el('copy-approve').disabled,true);assert.match(f.el('copy-status').textContent,/paused until a fresh producer response/);await f.el('copy-approve').listeners.click();assert.equal(mutations(f).length,1);
    await f.poll();assert.equal(f.el('copy-approve').disabled,false);assert.equal(mutations(f).length,1);
  }
});
test('recorded disclosure stays closed on unchanged polls and controls use labelled responsive structure',async()=>{
  const value=state(copyReview({status:'reviewed',advice:advice()}));const f=fixture(()=>Promise.resolve(response(value)));await flush();f.el('copy-raw-details').open=true;const clauses=f.el('copy-clauses').children;f.render(value);assert.equal(f.el('copy-raw-details').open,true);assert.equal(f.el('copy-clauses').children,clauses);
  const html=fs.readFileSync(path.join(ROOT,'desk.html'),'utf8'),css=fs.readFileSync(path.join(ROOT,'desk.css'),'utf8');
  assert.match(html,/for="copy-case"/);assert.match(html,/id="copy-status" role="status" aria-live="polite"/);assert.match(html,/Producer-approved draft; not transmitted/);assert.match(html,/<details id="copy-raw-details">/);
  assert.doesNotMatch(html,/id="copy-(?:review-button|approve|clear)"[^>]*data-action/);assert.match(css,/\.copy-review button,\.copy-review select,\.copy-review summary\{min-height:44px/);assert.match(css,/@media\(max-width:640px\).*\.copy-start\{grid-template-columns:minmax\(0,1fr\)\}/);assert.match(css,/\.copy-review pre\{[^}]*overflow-wrap:anywhere;white-space:pre-wrap/);
});
