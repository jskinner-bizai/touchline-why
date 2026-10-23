'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const ROOT=__dirname;
function makeState(overrides={}){
  return {publication:{facts:{score:{Harbor:0,Meadow:0}},event_time:{through_ms:50000},sequence:2,retracts:[],fact_id:'fact_1234567890123',stream_id:'same'},recorded_replay:{label:'facts',available:true,unavailable_reason:''},audience:'casual',language:'en',position:10,positions:21,recap:{views:{casual:{en:'English recap',es:'Recap en español'},analyst:{en:'English analyst',es:'Análisis'}},recorded_receipt_count:2,recorded_moment_count:1,withdrawn_claims:[],recap_id:'recap'},envelope:{provenance:{evidence_records:[]}},recovery_info:{},...overrides};
}
function fixture(fetcher){
  const elements=new Map();const timers=[];const buttons=[];const windowListeners={};const origin='http://127.0.0.1:8770';const clock={now:1700000000000};
  class WallClock extends Date{constructor(value=clock.now){super(value);}static now(){return clock.now;}}
  function el(id){if(!elements.has(id)){
    const element={id,textContent:'',hidden:true,value:'',disabled:false,attributes:{},children:[],listeners:{},style:{},contentWindow:{frame:id},srcWrites:[],replaceChildren(...nodes){this.children=[...nodes];},append(...nodes){this.children.push(...nodes);},replaceWith(replacement){elements.set(this.id,replacement);},scrollIntoView(){},setAttribute(k,v){this.attributes[k]=v;},addEventListener(event,listener){this.listeners[event]=listener;}};
    let normalized='';Object.defineProperty(element,'src',{get(){return normalized;},set(value){normalized=new URL(value,origin).href;this.srcWrites.push(normalized);}});elements.set(id,element);
  }return elements.get(id);}
  el('overlay').src='/overlay.html';
  buttons.push(el('replay-button'),el('audience'),el('language'));
  const context=vm.createContext({Date:WallClock,document:{getElementById:el,querySelectorAll:selector=>selector==='button,select'?buttons:[],createElement:()=>el(Math.random()),createTextNode:t=>t},window:{location:{origin},addEventListener(name,listener){windowListeners[name]=listener;}},crypto:{randomUUID:()=> 'op'},AbortSignal:{timeout:ms=>({timeoutMs:ms})},setTimeout(fn){timers.push(fn);},fetch:fetcher});
  vm.runInContext(fs.readFileSync(path.join(ROOT,'desk.js'),'utf8'),context);
  return {el,context,timers,setNow(now){clock.now=now;},status(data,{source=el('overlay').contentWindow,fromOrigin=origin}={}){windowListeners.message({data,source,origin:fromOrigin});}};
}
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function recordedState(overrides={}){
  const names=['m2-third-ui-call.json','m2-fourth-ui-call.json'];
  const captures=names.map(name=>JSON.parse(fs.readFileSync(path.join(ROOT,'evidence',name),'utf8')));
  const state=makeState();
  state.recorded_framework_trace={qualification:'Historical accepted SDK traces, not live execution.',withheld_receipt_count:0,receipts:captures.map((capture,index)=>{
    const result=capture.model_job.result;
    return {receipt_id:names[index],receipt_sha256:'approved-receipt-digest-'+index,historical_only:true,through_ms:capture.envelope.snapshot.upto_ms,model_id:result.model_id,elapsed_ms:result.elapsed_ms,sdk_versions:result.sdk_versions,trace:result.trace};
  })};
  state.recap.recorded_selections=[{recorded_moment_id:'recorded-one-moment',historical_only:true,original_through_ms:50000,receipt_ids:names,selection:captures[0].model_job.result.selection}];
  return {...state,...overrides};
}
function visibleText(element){return [element.textContent || '',...(element.children || []).map(child=>typeof child==='string'?child:visibleText(child))].join(' ');}
function overlayAck(state,overrides={}){return {type:'touchline.overlay.status.v1',stream_id:state.publication.stream_id,sequence:state.publication.sequence,status:'fallback',active:true,quarantined:false,...overrides};}
test('preview height fits bounded current-frame content and rejects forged or invalid height',async()=>{
  const state=makeState();const f=fixture(()=>Promise.resolve({ok:true,json:async()=>state}));await flush();const frame=f.el('overlay');
  f.status(overlayAck(state,{content_height:700}));assert.equal(frame.style.height,'700px');assert.equal(frame.scrolling,'no');
  f.status(overlayAck(state,{content_height:140}));assert.equal(frame.style.height,'260px');
  for(const height of [0,-1,Infinity,4097,500.5,'900']){f.status(overlayAck(state,{content_height:height}));assert.equal(frame.style.height,'260px');}
  f.status(overlayAck(state,{content_height:1400}),{fromOrigin:'https://foreign.example'});assert.equal(frame.style.height,'260px');
  f.status(overlayAck(state,{content_height:1400}),{source:{}});assert.equal(frame.style.height,'260px');
  f.status(overlayAck(state,{content_height:1400,sequence:state.publication.sequence+1}));assert.equal(frame.style.height,'260px');
  f.status(overlayAck(state,{content_height:2000}));assert.equal(frame.style.height,'1600px');assert.equal(frame.scrolling,'auto');assert.match(f.el('overlay-connection').textContent,/size limit/);
});
test('cached score keeps its last confirmed time and nearby stale label through producer loss',async()=>{
  let healthy=true;const state=correctedState([approvedCorrection()]);
  const f=fixture(()=>healthy?Promise.resolve({ok:true,json:async()=>state}):Promise.reject(Error('offline')));await flush();
  const score=f.el('score').textContent,confirmed=f.el('score-last-confirmed').textContent;
  assert.match(f.el('score-freshness').textContent,/Producer connected/);assert.equal(confirmed,'Last confirmed response: 2023-11-14 22:13:20 UTC.');
  f.setNow(1700000010000);healthy=false;await vm.runInContext('poll()',f.context);
  assert.equal(f.el('score').textContent,score);assert.equal(f.el('score-last-confirmed').textContent,confirmed);assert.match(f.el('score-freshness').textContent,/Cached facts.*no new producer update/);
  f.setNow(1700000020000);healthy=true;await vm.runInContext('poll()',f.context);
  assert.match(f.el('score-freshness').textContent,/Producer connected/);assert.equal(f.el('score-last-confirmed').textContent,'Last confirmed response: 2023-11-14 22:13:40 UTC.');
  const cold=fixture(()=>Promise.reject(Error('offline')));await flush();assert.match(cold.el('score-freshness').textContent,/No facts have been confirmed yet/);
});
test('new producer stream replaces iframe context even when its normalized URL is unchanged',async()=>{
  const first=makeState();const f=fixture(()=>Promise.resolve({ok:true,json:async()=>first}));await flush();
  const old=f.el('overlay'),oldWrites=old.srcWrites.length;f.status(overlayAck(first));assert.equal(old.hidden,false);
  const restarted=makeState();restarted.publication.stream_id='restarted';restarted.publication.sequence=1;
  vm.runInContext('render('+JSON.stringify(restarted)+')',f.context);
  const replacement=f.el('overlay');assert.notEqual(replacement,old);assert.notEqual(replacement.contentWindow,old.contentWindow);
  assert.equal(replacement.src,old.src);assert.equal(replacement.src,'http://127.0.0.1:8770/overlay.html');assert.equal(old.srcWrites.length,oldWrites);
  assert.equal(replacement.hidden,true);f.status(overlayAck(restarted));assert.equal(replacement.hidden,false);
});
test('late old producer poll and retired stream cannot rewind a recovered desk or iframe',async()=>{
  let release;const f=fixture(()=>new Promise(resolve=>{release=resolve;}));
  const old=makeState();old.publication.facts.score.Harbor=1;vm.runInContext('render('+JSON.stringify(old)+')',f.context);
  const restarted=makeState();restarted.publication.stream_id='restarted';restarted.publication.sequence=1;vm.runInContext('render('+JSON.stringify(restarted)+')',f.context);
  const replacement=f.el('overlay');old.publication.sequence=999;release({ok:true,json:async()=>old});await flush();
  assert.match(f.el('score').textContent,/Harbor 0/);assert.equal(f.el('overlay'),replacement);
  assert.equal(vm.runInContext('render('+JSON.stringify(old)+')',f.context),false);assert.equal(f.el('overlay'),replacement);
});
test('offline then new-stream poll replaces the consumer after the desk recovers corrected facts',async()=>{
  const first=correctedState([approvedCorrection()]);let state=first,healthy=true;
  const f=fixture(()=>healthy?Promise.resolve({ok:true,json:async()=>state}):Promise.reject(Error('offline')));await flush();f.status(overlayAck(first));
  const previous=f.el('overlay');healthy=false;await vm.runInContext('poll()',f.context);assert.equal(previous.hidden,true);assert.match(f.el('notice').textContent,/Producer unavailable/);
  state=correctedState([approvedCorrection()]);state.publication.stream_id='restarted';state.publication.sequence=1;healthy=true;await vm.runInContext('poll()',f.context);
  assert.notEqual(f.el('overlay'),previous);assert.equal(f.el('notice').textContent,'');assert.match(visibleText(f.el('correction-list')),/goal: true → false/);
  f.status(overlayAck(state));assert.equal(f.el('overlay').hidden,false);assert.match(f.el('overlay-connection').textContent,/confirmed the current producer stream/);
});
test('overlay acknowledgements reject old frames, foreign origins, malformed data and future sequences',async()=>{
  const state=makeState();const f=fixture(()=>Promise.resolve({ok:true,json:async()=>state}));await flush();
  for(const options of [{source:{}},{fromOrigin:'https://foreign.example'}]){f.status(overlayAck(state),options);assert.equal(f.el('overlay').hidden,true);}
  for(const malformed of [{status:'anything'},{sequence:Infinity},{stream_id:'x'.repeat(161)},{active:'true'},{status:'waiting',active:true},{sequence:state.publication.sequence+1}]){f.status(overlayAck(state,malformed));assert.equal(f.el('overlay').hidden,true);}
  f.status(overlayAck(state));assert.equal(f.el('overlay').hidden,false);
  const previous=f.el('overlay');f.el('overlay-reconnect').listeners.click();assert.notEqual(f.el('overlay'),previous);assert.equal(f.el('overlay').hidden,true);
  f.status(overlayAck(state),{source:previous.contentWindow});assert.equal(f.el('overlay').hidden,true);f.status(overlayAck(state));assert.equal(f.el('overlay').hidden,false);
});
test('unconfirmed or quarantined overlay exposes explicit manual recovery without bypassing quarantine',async()=>{
  const state=makeState();const f=fixture(()=>Promise.resolve({ok:true,json:async()=>state}));await flush();
  f.status(overlayAck(state,{status:'session_changed',active:false,quarantined:true}));assert.equal(f.el('overlay').hidden,true);assert.match(f.el('overlay-connection').textContent,/Use Reconnect overlay/);
  f.el('overlay-reconnect').listeners.click();const timeout=f.timers.at(-1);timeout();assert.match(f.el('overlay-connection').textContent,/connection is not confirmed/);
  f.status(overlayAck(state));const confirmed=f.el('overlay-connection').textContent;timeout();assert.equal(f.el('overlay-connection').textContent,confirmed);
});
test('embedded renderer reports bounded state to its same-origin parent and keeps session-change card cleared',async()=>{
  const elements=new Map(),messages=[];function el(id){if(!elements.has(id))elements.set(id,{textContent:'',hidden:true});return elements.get(id);}
  const window={location:{origin:'http://127.0.0.1:8770'},parent:{postMessage(data,origin){messages.push({data,origin});}}};
  const context=vm.createContext({window,document:{getElementById:el,querySelector:()=>({scrollHeight:9000})},TouchlineConsumer:{initial:()=>({stream:'prior',lastSequence:4,active:null,status:'session_changed',quarantined:true}),expired:s=>s,consume:s=>s},Date,performance:{now:()=>0},setInterval(){},setTimeout(){},AbortSignal:{timeout:()=>({})},fetch:()=>Promise.reject(Error('offline'))});
  vm.runInContext(fs.readFileSync(path.join(ROOT,'overlay_m3.js'),'utf8'),context);await flush();
  assert.equal(el('live-card').hidden,true);assert.equal(el('card-text').textContent,'');assert.match(el('consumer-status').textContent,/Reload consumer/);
  assert.equal(messages[0].origin,window.location.origin);assert.equal(messages[0].data.type,'touchline.overlay.status.v1');assert.equal(messages[0].data.quarantined,true);assert.equal(messages[0].data.active,false);assert.equal(messages[0].data.stream_id,'prior');
  assert.equal(messages[0].data.content_height,4096);assert.deepEqual(Object.keys(messages[0].data).sort(),['active','content_height','quarantined','sequence','status','stream_id','type']);
});
function approvedCorrection({id='e010',from=1,to=2,beforeGoal=true,afterGoal=false,at=50000}={}){
  const before={id,type:'shot',at_ms:at,team_id:'harbor',player_id:'harbor_7',on_target:true,goal:beforeGoal};
  return {correction_id:`review-${id}-${to}`,target_event_id:id,from_revision:from,to_revision:to,before,after:{...before,goal:afterGoal},source_id:'synthetic_match'};
}
function correctedState(corrections,overrides={}){
  const state=makeState();state.envelope.provenance.corrections=corrections;return {...state,...overrides};
}
test('missing correction history displays an explicit current-time empty state',async()=>{
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>makeState()}));await flush();
  assert.equal(f.el('correction-summary').textContent,'No approved corrections visible at 50s.');
  assert.equal(f.el('correction-list').children.length,0);assert.equal(f.el('correction-raw').textContent,'[]');
});
test('zero-time replay withholds future correction details in summary and raw provenance',async()=>{
  const state=correctedState([approvedCorrection()]);state.publication.event_time.through_ms=0;
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>state}));await flush();
  assert.equal(f.el('correction-summary').textContent,'No approved corrections visible at 0s.');
  assert.equal(f.el('correction-list').children.length,0);assert.equal(f.el('correction-raw').textContent,'[]');
  assert.doesNotMatch(f.el('audit').textContent,/review-e010-2|from_revision|to_revision/);
});
test('moving a future event into the current watermark does not expose its future prior facts',async()=>{
  const correction=approvedCorrection();correction.before.at_ms=80000;correction.after.at_ms=50000;
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>correctedState([correction])}));await flush();
  assert.equal(f.el('correction-list').children.length,0);assert.equal(f.el('correction-raw').textContent,'[]');
  assert.doesNotMatch(f.el('audit').textContent,/review-e010-2|80000|from_revision|to_revision/);
  assert.equal(f.el('correction-summary').textContent,'No approved corrections visible at 50s.');
});
test('correction summary shows exact revision and changed values without unchanged fields',async()=>{
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>correctedState([approvedCorrection()])}));await flush();
  assert.equal(f.el('correction-summary').textContent,'1 approved correction visible at 50s. Rewind keeps these changes.');
  const text=visibleText(f.el('correction-list'));
  assert.match(text,/e010: revision 1 to 2/);assert.match(text,/goal: true → false/);
  assert.doesNotMatch(text,/on_target|player_id|at_ms|team_id/);
  const raw=JSON.parse(f.el('correction-raw').textContent);assert.equal(raw[0].before.on_target,true);assert.equal(raw[0].after.on_target,true);
});
test('recovery response preserves visible approved changes while publication stream changes',async()=>{
  const row=approvedCorrection();const initial=correctedState([row]);
  const recovered=correctedState([row]);recovered.publication.stream_id='reopened';recovered.publication.sequence=1;recovered.recovery_info={recovered:true};
  const f=fixture((url,options)=>Promise.resolve({ok:true,json:async()=>options?.method==='POST'?recovered:initial}));await flush();
  const before=visibleText(f.el('correction-list'));
  await vm.runInContext("control({action:'recover'})",f.context);
  assert.equal(visibleText(f.el('correction-list')),before);assert.match(f.el('correction-summary').textContent,/1 approved correction visible/);
  assert.equal(f.el('overlay').src,'http://127.0.0.1:8770/overlay.html');assert.match(f.el('version').textContent,/Publisher sequence 1/);
});
test('all visible correction revisions remain inspectable after a deliberate goal restoration',async()=>{
  const rows=[approvedCorrection(),approvedCorrection({from:2,to:3,beforeGoal:false,afterGoal:true})];
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>correctedState(rows)}));await flush();
  const text=visibleText(f.el('correction-list'));
  assert.equal(f.el('correction-list').children.length,2);assert.match(f.el('correction-summary').textContent,/2 approved corrections visible/);
  assert.match(text,/e010: revision 1 to 2/);assert.match(text,/goal: true → false/);assert.match(text,/e010: revision 2 to 3/);assert.match(text,/goal: false → true/);
});
test('replacement references are labelled per publication independently of correction history',async()=>{
  const state=correctedState([approvedCorrection(),approvedCorrection({id:'e008'})]);state.publication.sequence=17;state.publication.retracts=['prior-overlay'];
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>state}));await flush();
  assert.equal(f.el('version').textContent,'Publisher sequence 17. Prior publications replaced by this one: 1.');
  assert.match(f.el('correction-summary').textContent,/2 approved corrections visible/);assert.doesNotMatch(f.el('version').textContent,/retractions|corrections/);
  const audit=JSON.parse(f.el('audit').textContent);assert.deepEqual(audit.delivery.replaces,['prior-overlay']);
});
test('disabled optional inference exposes its exact preflight reason without spending an attempt',async()=>{
  const reason='Current snapshot supplies fewer than two eligible candidates.';
  const live={enabled:true,available:false,attempts:0,wall_spent_ms:0,job:{status:'idle'},eligibility_reason:reason};
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>makeState({live_inference:live})}));await flush();
  assert.equal(f.el('live-button').disabled,true);assert.ok(f.el('live-help').textContent.endsWith(reason));assert.match(f.el('live-help').textContent,/0\/4 attempts/);
});
test('SDK receipt and candidate content stays withheld before its event-time watermark',async()=>{
  const state=recordedState();state.publication.event_time.through_ms=49000;
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>state}));await flush();
  assert.match(f.el('sdk-trace-summary').textContent,/No recorded SDK trace is visible/);
  assert.equal(f.el('sdk-records').children.length,0);
  assert.doesNotMatch(f.el('sdk-trace').textContent,/gemma4|candidate_1c324d|m2-third-ui-call/);
});
test('readable SDK panel associates two actual receipt traces with one historical choice',async()=>{
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>recordedState()}));await flush();
  assert.match(f.el('sdk-trace-summary').textContent,/2 accepted historical receipts; 1 distinct selection moment/);
  assert.match(f.el('sdk-trace-summary').textContent,/Current local attempts: 0/);
  const text=visibleText(f.el('sdk-records'));
  for(const term of ['gemma4:12b','agent-framework-core 1.22.0','agent-framework-ollama 1.0.0b261015','candidate_1c324d2700f64f848df0','shot_volume; e008, e010','Agent Framework agent middleware: enter','OllamaChatClient','http_status: 200'])assert.ok(text.includes(term),term);
  assert.equal(f.el('sdk-records').children.length,2);
});
test('corrected-state trace stays historical and does not re-enable recorded replay',async()=>{
  const state=recordedState({recorded_replay:{label:'corrected',available:false,unavailable_reason:'Current facts differ'}});
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>state}));await flush();
  assert.match(f.el('sdk-replay-state').textContent,/Recorded replay is blocked/);
  assert.match(f.el('sdk-replay-state').textContent,/supported historical claim remains history/);
  assert.equal(f.el('replay-button').disabled,true);
  assert.match(visibleText(f.el('sdk-records')),/candidate_1c324d2700f64f848df0/);
});
test('opening and closing SDK evidence changes disclosure state without a network request',async()=>{
  let requests=0;const f=fixture(()=>{requests++;return Promise.resolve({ok:true,json:async()=>recordedState()});});await flush();
  assert.equal(requests,1);
  f.el('trace-toggle').listeners.click();assert.equal(f.el('sdk-details').open,true);assert.equal(f.el('trace-toggle').attributes['aria-expanded'],'true');
  f.el('trace-toggle').listeners.click();assert.equal(f.el('sdk-details').open,false);assert.equal(f.el('trace-toggle').attributes['aria-expanded'],'false');
  assert.equal(requests,1);
});
test('a reset no longer presents its partial recap as final',async()=>{
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>makeState()}));await flush();
  f.el('recap').hidden=false;vm.runInContext('render('+JSON.stringify(makeState({position:0}))+')',f.context);
  assert.equal(f.el('recap').hidden,true);
});
test('Spanish recap exposes exact English companion and language tag',async()=>{
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>makeState()}));await flush();
  vm.runInContext('render('+JSON.stringify(makeState({language:'es'}))+')',f.context);
  assert.equal(f.el('recap-text').lang,'es');assert.equal(f.el('recap-english').hidden,false);assert.equal(f.el('recap-english-text').textContent,'English recap');
});
test('replay remains disabled after a successful corrected-state control',async()=>{
  const state=makeState({recorded_replay:{label:'corrected',available:false,unavailable_reason:'Reset first'}});
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>state}));await flush();
  await vm.runInContext("control({action:'correct'})",f.context);
  assert.equal(f.el('replay-button').disabled,true);assert.equal(f.el('audience').disabled,false);assert.equal(f.el('replay-help').textContent,'Reset first');
});
test('HTTP503 polling is visible and clears on a fresh successful state',async()=>{
  let healthy=false;const f=fixture(()=>Promise.resolve(healthy?{ok:true,json:async()=>makeState()}:{ok:false}));await flush();
  assert.match(f.el('notice').textContent,/Producer unavailable/);healthy=true;await vm.runInContext('poll()',f.context);
  assert.equal(f.el('notice').textContent,'');
});
test('timed-out mutation reports uncertain outcome, releases controls and never retries',async()=>{
  let posts=0,timeout;
  const f=fixture((url,options)=>{if(options?.method==='POST'){posts++;timeout=options.signal.timeoutMs;return Promise.reject(Object.assign(new Error('timeout'),{name:'TimeoutError'}));}return Promise.resolve({ok:true,json:async()=>makeState()});});await flush();
  await vm.runInContext("control({action:'correct'})",f.context);
  assert.equal(posts,1);assert.equal(timeout,5000);assert.equal(f.el('audience').disabled,false);assert.match(f.el('notice').textContent,/outcome is uncertain/);
});
test('local inference controls stay hidden by default and expose explicit opt-in separately',async()=>{
  const f=fixture(()=>Promise.resolve({ok:true,json:async()=>makeState()}));await flush();
  assert.equal(f.el('live-button').hidden,true);assert.equal(f.el('live-details').hidden,true);
  const live={enabled:true,available:true,attempts:1,wall_spent_ms:400,job:{status:'accepted',result:{trace:['mock']}}};
  vm.runInContext('render('+JSON.stringify(makeState({live_inference:live}))+')',f.context);
  assert.equal(f.el('live-button').hidden,false);assert.equal(f.el('live-button').disabled,false);
  assert.equal(f.el('live-details').hidden,false);assert.match(f.el('live-trace').textContent,/mock/);
  assert.match(f.el('live-help').textContent,/1\/4 attempts/);assert.match(f.el('recap-proof').textContent,/New local attempts: 1/);
});
test('overlay shows Spanish with English translation and clears both on expiry',async()=>{
  const elements=new Map();function el(id){if(!elements.has(id))elements.set(id,{textContent:'',hidden:true});return elements.get(id);}
  const publication={card:{text:'Tiros verificados',audience:'casual',language:'es',translation_en:'Verified shots',evidence_ids:['e010'],replay_label:'RECORDED',fallback:false,explanation_type:'shot_volume',metrics:{shots:2,on_target:2}},sequence:3,retracts:[],fact_id:'fact_1234567890123'};
  let expired=false;
  const context=vm.createContext({document:{getElementById:el},TouchlineConsumer:{initial:()=>({active:publication}),expired:s=>expired?{active:null,status:'expired'}:s,consume:s=>s},Date,performance:{now:()=>0},setInterval(){},setTimeout(){},AbortSignal:{timeout:()=>({})},fetch:()=>Promise.reject(Error('offline'))});
  vm.runInContext(fs.readFileSync(path.join(ROOT,'overlay_m3.js'),'utf8'),context);await flush();
  assert.equal(el('card-text').lang,'es');assert.equal(el('card-translation').hidden,false);assert.equal(el('card-translation').textContent,'English: Verified shots');
  assert.equal(el('replay-cue').textContent,'');assert.equal(el('replay-cue').hidden,true);
  assert.equal(el('card-evidence').hidden,true);assert.equal(el('card-meta').hidden,true);
  publication.card.audience='analyst';vm.runInContext('render()',context);
  assert.equal(el('card-evidence').hidden,false);assert.match(el('card-evidence').textContent,/e010/);assert.equal(el('card-meta').hidden,false);assert.match(el('card-meta').textContent,/123456789012/);
  expired=true;vm.runInContext('render()',context);assert.equal(el('live-card').hidden,true);assert.equal(el('card-translation').textContent,'');assert.equal(el('replay-cue').textContent,'');
});
