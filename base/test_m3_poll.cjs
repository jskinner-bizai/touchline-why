'use strict';
// Deterministic response ordering test. No browser, network, or provider.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
const target=process.argv[2]||path.resolve(__dirname,'desk.js');
let releaseOld;
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{id,textContent:'',hidden:true,value:'',src:'',replaceChildren(){},append(){},scrollIntoView(){},addEventListener(){}});return elements.get(id);}
function state(goal,sequence,stream='same'){
 return {publication:{facts:{score:{Harbor:goal,Meadow:0}},event_time:{through_ms:50000},sequence,retracts:[],fact_id:'fact_1234567890123',stream_id:stream},recorded_replay:{label:'facts'},audience:'casual',language:'en',recap:{views:{casual:{en:'recap'}},recorded_receipt_count:0,recorded_moment_count:0,withdrawn_claims:[],recap_id:'recap'},envelope:{provenance:{evidence_records:[]}},recovery_info:{}};
}
let calls=0;
const context=vm.createContext({document:{getElementById:element,querySelectorAll:()=>[],createElement:()=>element(Math.random()),createTextNode:t=>t},crypto:{randomUUID:()=> 'operation'},AbortSignal:{timeout:()=>({})},setTimeout(){},fetch(){calls++;if(calls===1)return new Promise(resolve=>{releaseOld=()=>resolve({ok:true,json:async()=>state(1,1)});});return Promise.resolve({ok:true,json:async()=>state(0,2)});}});
vm.runInContext(fs.readFileSync(target,'utf8'),context,{filename:target});
(async()=>{
 await vm.runInContext("control({action:'correct'})",context);
 assert.match(element('score').textContent,/Harbor 0/,'correction response was shown');
 releaseOld();for(let i=0;i<8;i++)await Promise.resolve();
 assert.match(element('score').textContent,/Harbor 0/,'older in-flight poll must not rewind correction');
 console.log('PASS: delayed producer poll cannot rewind a correction');
})().catch(error=>{console.error(error.message);process.exitCode=1;});
