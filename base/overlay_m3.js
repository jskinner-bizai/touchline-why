"use strict";
let consumer=TouchlineConsumer.initial();const el=id=>document.getElementById(id);
function reportEmbeddedStatus(){
  if(typeof window!=='undefined' && window.parent!==window){
    const message={type:'touchline.overlay.status.v1',stream_id:consumer.stream,sequence:consumer.lastSequence || 0,status:consumer.status,quarantined:consumer.quarantined===true,active:!!consumer.active};
    const main=document.querySelector?.('main'),height=main?.scrollHeight;
    if(Number.isFinite(height) && height>0)message.content_height=Math.min(4096,Math.ceil(height));
    window.parent.postMessage(message,window.location.origin);
  }
}
function render(){
  consumer=TouchlineConsumer.expired(consumer,Date.now(),performance.now());const publication=consumer.active;
  el('live-card').hidden=!publication;
  const status=publication?publication.card.replay_label:consumer.status==='session_changed'?'Producer restarted. Reload consumer.':'Expired or unavailable insight cleared';
  if(el('consumer-status').textContent!==status)el('consumer-status').textContent=status;
  if(publication){
    const card=publication.card;el('card-text').textContent=card.text;el('card-text').lang=card.language;
    el('card-translation').hidden=card.language!=='es'||!card.translation_en;
    el('card-translation').textContent=card.language==='es'&&card.translation_en?'English: '+card.translation_en:'';
    el('replay-cue').textContent='';el('replay-cue').hidden=true;
    el('card-evidence').hidden=card.audience!=='analyst';el('card-meta').hidden=card.audience!=='analyst';
    el('card-evidence').textContent='Evidence: '+card.evidence_ids.join(', ');
    el('card-meta').textContent=`Version ${publication.sequence}; retracts ${publication.retracts.length}; ${publication.fact_id.slice(5,17)}`;
  }else{
    el('replay-cue').textContent='';el('replay-cue').hidden=true;el('card-text').textContent='';el('card-translation').textContent='';el('card-translation').hidden=true;el('card-evidence').textContent='';el('card-meta').textContent='';
  }
  reportEmbeddedStatus();
}
async function poll(){
  try{const response=await fetch('/api/overlay',{cache:'no-store',signal:AbortSignal.timeout(1500)});if(response.ok)consumer=TouchlineConsumer.consume(consumer,await response.json(),Date.now(),performance.now());}catch(_){}
  render();setTimeout(poll,250);
}
setInterval(render,100);poll();
