"""Durable synthetic desk. Recorded selections only; no provider is instantiated."""
from __future__ import annotations
import argparse
import copy
import json
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from uuid import uuid4
from app_m2 import Handler as BaseHandler
from durable_controller import DurableController, OPERATION_ID
from recap import build_recap, normalize_recorded_receipt
from touchline_core import load_events, validate_selection

ROOT = Path(__file__).resolve().parent

class Desk:
    def __init__(self, events, db_path):
        self.events, self.db_path = copy.deepcopy(events), db_path
        self.lock = threading.RLock()
        self.operations = {}
        self.replay = {'status': 'idle', 'label': 'No live inference; deterministic facts'}
        self.receipts = [{'receipt_id': name, 'receipt_bytes': (ROOT/'evidence'/name).read_bytes()}
                         for name in ('m2-third-ui-call.json','m2-fourth-ui-call.json')]
        # Fail startup if either exact preserved receipt was altered.
        self.recorded = [normalize_recorded_receipt(**row) for row in self.receipts]
        self.framework_traces = []
        for raw, normalized in zip(self.receipts, self.recorded):
            captured = json.loads(raw['receipt_bytes'].decode('utf-8'))
            result = captured['model_job']['result']
            self.framework_traces.append({
                'receipt_id': normalized['receipt_id'], 'receipt_sha256': normalized['receipt_sha256'],
                'historical_only': True, 'through_ms': normalized['snapshot']['upto_ms'],
                'captured_at_ms': captured['model_job']['finished_at_ms'],
                'model_id': result['model_id'], 'elapsed_ms': result['elapsed_ms'],
                'sdk_versions': copy.deepcopy(result['sdk_versions']),
                'trace': copy.deepcopy(result['trace']),
            })
        self.durable = DurableController(self.events, db_path)

    def state(self):
        with self.lock:
            state = self.durable.state()
            state['recorded_replay'] = copy.deepcopy(self.replay)
            state['live_model_calls_this_milestone'] = 0
            state['historical_model_calls'] = {'attempts':4,'accepted':2,'timeouts':2,'distinct_selected_moments':1}
            state['recovery_info'] = self.durable.recovery_info
            state['recap'] = build_recap(state['envelope']['snapshot'], state['envelope']['provenance'], self.receipts)
            pub = state['publication']
            visible_traces = [row for row in self.framework_traces if row['through_ms'] <= pub['event_time']['through_ms']]
            state['recorded_framework_trace'] = {
                'qualification': 'Historical accepted SDK traces, not live execution or a fresh latency benchmark.',
                'receipts': copy.deepcopy(visible_traces),
                'withheld_receipt_count': len(self.framework_traces)-len(visible_traces),
            }
            available = any(row['snapshot']['state_digest'] == pub['state_digest'] for row in self.recorded)
            state['recorded_replay']['available'] = available
            state['recorded_replay']['unavailable_reason'] = (
                '' if available else 'Recorded output requires the original 50s facts. Show the 50s pattern; approved corrections survive reset and rewind, so corrected facts cannot replay that receipt.'
            )
            # Explicit provenance reaches the independent consuming browser too.
            if not pub['card']['fallback']:
                pub['card']['replay_label'] = 'RECORDED MODEL OUTPUT REPLAY • no live inference'
                state['recorded_replay']['label'] = pub['card']['replay_label']
            else:
                pub['card']['replay_label'] = 'DETERMINISTIC VERIFIED FACTS • no model call'
                if state['recorded_replay']['status'] == 'recorded_replay':
                    state['recorded_replay']['label'] = 'RECORDED SELECTION EXPIRED • deterministic verified facts'
            return state

    def control(self, value):
        if not isinstance(value, dict) or not isinstance(value.get('operation_id'), str) or not OPERATION_ID.fullmatch(value['operation_id']):
            raise ValueError('Operation ID required')
        operation_id=value['operation_id']
        command={key: val for key,val in value.items() if key != 'operation_id'}
        action=command.get('action')
        with self.lock:
            if operation_id in self.operations:
                if self.operations[operation_id] != command: raise ValueError('Conflicting operation ID')
                # Finish has a durable parent receipt. Recheck it even when
                # cached, so a retry reports current state and duplicate=true.
                if action != 'finish': return self.state()
            durable_operation = None
            if action in {'replay3','replay4','timeout','recover'}:
                if set(command) != {'action'}:
                    raise ValueError('Unexpected fields')
                if self.durable.operation_command(operation_id) is not None:
                    raise ValueError('Conflicting operation ID')
                c=self.durable.controller
                if action in {'replay3','replay4'}:
                    receipt=self.receipts[0 if action=='replay3' else 1]
                    historical=self.recorded[0 if action=='replay3' else 1]
                    current=c.engine.view(c.audience,c.language)['snapshot']
                    if current['state_digest'] != historical['snapshot']['state_digest']:
                        raise ValueError('Recorded selection requires the exact original 50s facts; approved corrections survive reset and rewind')
                    request=c.engine.selection_request(c.audience,c.language)
                    validate_selection(historical['selection'],current)
                    selection=historical['selection']
                    c.engine.apply_selection(request,selection)
                    c.job={'status':'recorded_replay','injected':False,'receipt_id':receipt['receipt_id'],
                           'note':'Historical accepted SDK output replayed against identical facts. No provider call.'}
                    self.replay={'status':'recorded_replay','receipt_id':receipt['receipt_id'],
                                 'label':'RECORDED MODEL OUTPUT REPLAY • no live inference'}
                elif action=='timeout':
                    request=c.engine.selection_request(c.audience,c.language)
                    c.engine.fail_selection(request,reason='timeout')
                    c.job={'status':'timeout','injected':True,'note':'Declared local failure injection. No provider request or cancellation claim.'}
                    self.replay={'status':'injected_timeout','label':'INJECTED TIMEOUT • deterministic fallback; no model call'}
                elif action=='recover':
                    self.durable.close()
                    self.durable=DurableController(self.events,self.db_path)
                    self.replay={'status':'recovered_fallback','label':'DURABLE REOPEN • facts restored; recorded insight discarded'}
            else:
                result=self.durable.control(command,operation_id)
                durable_operation=copy.deepcopy(result['durability']['operation'])
                if action=='finish':
                    if result['position']==result['positions']-1:
                        self.replay={'status':'deterministic_recap','label':'FINAL SYNTHETIC RECAP • deterministic; recorded results remain history'}
                    else:
                        self.replay={'status':'duplicate_finish_current_state','label':'FINISH RETRY ACKNOWLEDGED - current replay retained; no advance'}
                else:
                    self.replay={'status':'deterministic','label':'DETERMINISTIC VERIFIED FACTS • no model call'}
            self.operations[operation_id]=copy.deepcopy(command)
            if len(self.operations)>500:self.operations.pop(next(iter(self.operations)))
            state=self.state()
            if durable_operation is not None:
                state['durability']['operation']=durable_operation
            return state

class Handler(BaseHandler):
    request_timeout_s = 4.0

    def setup(self):
        super().setup()
        # Bounds socket inactivity; absolute request deadlines/concurrency
        # are not implemented.
        self.connection.settimeout(self.request_timeout_s)

    def do_POST(self):
        try: return super().do_POST()
        except TimeoutError:
            self.close_connection = True
            try: return self._reply(408,{'error':'Local request timed out; outcome may be uncertain. Inspect state before retrying'})
            except (BrokenPipeError, ConnectionResetError, TimeoutError): return None
        except RuntimeError as error:
            return self._reply(503,{'error':'Durable state unavailable; reopen and inspect journal before retrying',
                                    'committed':getattr(error,'committed',None)})

    def _reply(self,status,data,content_type='application/json; charset=utf-8'):
        body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status)
        for key,val in {'Content-Type':content_type,'Content-Length':str(len(body)), 'Cache-Control':'no-store',
            'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"}.items():
            self.send_header(key,val)
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if not self._host(): return self._reply(403,{'error':'Loopback host required'})
        files={'/':('desk.html','text/html'),'/desk.js':('desk.js','text/javascript'),'/desk.css':('desk.css','text/css'),
               '/overlay.html':('overlay_m3.html','text/html'),'/overlay_m3.js':('overlay_m3.js','text/javascript'),
               '/m2.css':('m2.css','text/css'),'/overlay_client.js':('overlay_client.js','text/javascript')}
        if self.path in {'/api/state','/api/overlay','/api/recap'}:
            try: state=self.controller.state()
            except (ValueError,RuntimeError): return self._reply(503,{'error':'Durable state failed verification; stop and inspect journal'})
            return self._reply(200,state if self.path=='/api/state' else state['publication' if self.path=='/api/overlay' else 'recap'])
        if self.path not in files:return self._reply(404,{'error':'Unknown route'})
        name,kind=files[self.path];return self._reply(200,(ROOT/name).read_bytes(),kind+'; charset=utf-8')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8770)
    parser.add_argument('--db-path',type=Path,required=True,help='Writable runtime path outside judge source bundle')
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('Unprivileged port required')
    args.db_path.parent.mkdir(parents=True,exist_ok=True)
    Handler.controller=Desk(load_events(ROOT/'synthetic_match.jsonl'),args.db_path)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Touchline M3 http://127.0.0.1:{args.port}; recorded replay only; zero provider calls',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();Handler.controller.durable.close()

if __name__=='__main__':main()
