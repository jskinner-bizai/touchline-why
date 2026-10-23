(function(scope){
 'use strict';
 const safe=Number.isSafeInteger;
 const short=value=>typeof value==='string'&&value.length>0&&value.length<=160;
 const object=value=>value&&typeof value==='object'&&!Array.isArray(value);
 const validFacts=value=>object(value)&&object(value.score)&&Object.values(value.score).length===2&&Object.values(value.score).every(x=>safe(x)&&x>=0)&&safe(value.through_ms)&&value.through_ms>=0;
 const validTime=value=>object(value)&&['through_ms','start_ms','end_ms'].every(key=>safe(value[key])&&value[key]>=0)&&value.start_ms<=value.end_ms&&value.end_ms<=value.through_ms&&value.inclusive===true;
 function initial(){return {stream:null,lastSequence:0,signature:null,active:null,activeMonoDeadline:null,lastFacts:null,status:'waiting',quarantined:false};}
 function expired(state,now,monotonic=now){if(state.active&&(now>=state.active.expires_at_ms||monotonic>=state.activeMonoDeadline))return {...state,active:null,status:'expired'};return state;}
 function consume(state,pub,now,monotonic=now){
  const current=expired(state,now,monotonic);
  if(current.quarantined)return current;
  if(!pub||pub.schema_version!=='touchline.overlay.v1'||!short(pub.stream_id)||!short(pub.overlay_id)||!short(pub.fact_id)||!safe(pub.sequence)||pub.sequence<1||!safe(pub.issued_at_ms)||!safe(pub.expires_at_ms)||pub.expires_at_ms<=pub.issued_at_ms||pub.expires_at_ms-pub.issued_at_ms>30000||pub.issued_at_ms>now+1000||!object(pub.card)||typeof pub.card.text!=='string'||pub.card.text.length>4000||typeof pub.card.fallback!=='boolean'||!['casual','analyst'].includes(pub.card.audience)||!['en','es'].includes(pub.card.language)||!Array.isArray(pub.card.evidence_ids)||pub.card.evidence_ids.length>500||pub.card.evidence_ids.some(id=>!short(id))||(pub.card.translation_en!==undefined&&(typeof pub.card.translation_en!=='string'||pub.card.translation_en.length>4000))||!Array.isArray(pub.retracts)||pub.retracts.length>500||pub.retracts.some(id=>!short(id))||!validFacts(pub.facts)||!validTime(pub.event_time)||!object(pub.provenance))return {...current,status:current.active?current.status:'invalid'};
  if(current.stream&&current.stream!==pub.stream_id)return {...current,active:null,status:'session_changed',quarantined:true};
  const signature=JSON.stringify(pub);
  if(pub.sequence<current.lastSequence)return current;
  if(pub.sequence===current.lastSequence){if(signature!==current.signature)return current;return current;}
  const active=now>=pub.expires_at_ms?null:pub;
  return {stream:pub.stream_id,lastSequence:pub.sequence,signature,active,activeMonoDeadline:monotonic+Math.max(0,pub.expires_at_ms-now),lastFacts:pub.facts,status:active?(pub.card.fallback?'fallback':'insight'):'expired',quarantined:false};
 }
 const api={initial,consume,expired};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;else scope.TouchlineConsumer=api;
})(typeof window==='undefined'?{}:window);
