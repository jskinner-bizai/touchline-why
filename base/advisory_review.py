"""Recorded, context-bound producer copy review. No SDK or provider imports.

Approval creates an in-memory producer draft. It never changes match facts,
broadcast overlays, durable data, provider configuration or external services.
The Desk owner serializes every call with its existing lock and supplies a fresh
state after every deterministic command.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from recap import build_recap


CASE_IDS = ("P01", "P02", "P03", "P04")
OPERATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
REASONS = {"supported", "unsupported_causality", "contradicted_fact", "stale_revision"}
SOURCE_DIGEST = "4d7c1eceb7c20621bedb80eecf9fc3a09b349e02c5075b5c8eef84951bf8b5b3"
SOURCE_ID = "synthetic_match"
# Exact preserved input/receipt bytes; adapter publishable flags confer no authority.
EVIDENCE_SHA256 = {
    "cases.json":"b947970c1d203a7a14e72c1521c89a4f98bf9af9134f090687224ba6236b0b8a",
    "RECEIPT_P01.json":"d21d780136572be4726f49a5afc8be576e7afca861dee13acfed20403ab2c765",
    "RECEIPT_P02.json":"a1b39be33e2ae9002374916b88fe29aa78b0c9a649ff64a256445ab0727cfdb4",
    "RECEIPT_P03.json":"ad629429a3b15b485e611e9b89e2960d07c7495421488bcc11fd99be00d6152a",
    "RECEIPT_P04.json":"51156ab6cea396f5719a02619274c2aee610ae3d4a09ee5a9836540b82fcd58c",
}


def _canonical(value, *, ascii=True):
    try:
        return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=ascii,allow_nan=False)
    except (TypeError,ValueError,OverflowError,RecursionError) as error:
        raise ValueError("Finite bounded JSON required") from error


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError("Duplicate evidence JSON key")
            result[key]=value
        return result
    try:
        return json.loads(raw,object_pairs_hook=pairs,
                          parse_constant=lambda _:(_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    except (TypeError,ValueError,UnicodeError,RecursionError) as error:
        raise ValueError("Invalid evidence JSON") from error


def _identifier(value):
    return isinstance(value,str) and OPERATION_ID.fullmatch(value) is not None


def _ids(value,allowed,maximum):
    if (not isinstance(value,list) or len(value)>maximum
            or any(not isinstance(item,str) or item not in allowed for item in value)
            or len(set(value))!=len(value)):
        raise ValueError("Invalid or duplicate declared IDs")
    return list(value)


def _output(value,case):
    if not isinstance(value,dict) or set(value)!={"decision","keep","drop","facts","reason"}:
        raise ValueError("Recorded output requires exactly five fields")
    if (not isinstance(value["decision"],str) or value["decision"] not in {"allow","revise","withhold"}
            or not isinstance(value["reason"],str) or value["reason"] not in REASONS):
        raise ValueError("Unknown recorded decision or reason")
    clauses={row["id"] for row in case["draft_clauses"]}
    keep=_ids(value["keep"],clauses,2);drop=_ids(value["drop"],clauses,2)
    facts=_ids(value["facts"],case["facts"],8)
    if set(keep)&set(drop) or set(keep)|set(drop)!=clauses:
        raise ValueError("Recorded clause partition is invalid")
    if (value["decision"]=="allow" and (drop or set(keep)!=clauses)
            or value["decision"]=="revise" and (not keep or not drop)
            or value["decision"]=="withhold" and (keep or facts)
            or keep and not facts):
        raise ValueError("Recorded decision and partition differ")
    return copy.deepcopy(value)


def _case(value):
    required={"synthetic","watermark_ms","snapshot_digest","audience","draft_clauses","facts",
              "evidence_ids","event_revisions","evidence_times_ms","corrections"}
    if (not isinstance(value,dict) or set(value)!=required or value["synthetic"] is not True
            or type(value["watermark_ms"]) is not int or value["watermark_ms"]!=50000
            or not isinstance(value["snapshot_digest"],str) or not DIGEST.fullmatch(value["snapshot_digest"])
            or value["audience"]!="casual"):
        raise ValueError("Invalid frozen synthetic review case")
    clauses=value["draft_clauses"]
    if (not isinstance(clauses,list) or not 1<=len(clauses)<=2
            or any(not isinstance(row,dict) or set(row)!={"id","text"}
                   or not isinstance(row["id"],str) or row["id"] not in {"C1","C2"}
                   or not isinstance(row["text"],str) or not 1<=len(row["text"])<=1200 for row in clauses)
            or len({row["id"] for row in clauses})!=len(clauses)):
        raise ValueError("Invalid frozen draft clauses")
    evidence=value["evidence_ids"];revisions=value["event_revisions"];times=value["evidence_times_ms"]
    if (not isinstance(evidence,list) or not 1<=len(evidence)<=64
            or any(not _identifier(item) for item in evidence) or len(set(evidence))!=len(evidence)
            or not isinstance(revisions,dict) or set(revisions)!=set(evidence)
            or any(type(item) is not int or item<1 for item in revisions.values())
            or not isinstance(times,dict) or set(times)!=set(evidence)
            or any(type(item) is not int or not 0<=item<=50000 for item in times.values())):
        raise ValueError("Invalid frozen evidence revision/time catalog")
    facts=value["facts"]
    if not isinstance(facts,dict) or not 1<=len(facts)<=8:raise ValueError("Invalid frozen facts")
    for fact_id,row in facts.items():
        if (not isinstance(fact_id,str) or not re.fullmatch(r"F_[A-Z0-9_]{1,24}",fact_id)
                or not isinstance(row,dict) or set(row)!={"text","evidence_ids","event_revisions"}
                or not isinstance(row["text"],str) or not 1<=len(row["text"])<=1200):
            raise ValueError("Invalid frozen fact")
        ids=_ids(row["evidence_ids"],evidence,24)
        if not ids or row["event_revisions"]!={item:revisions[item] for item in ids}:
            raise ValueError("Frozen fact revision mismatch")
    if not isinstance(value["corrections"],list) or len(value["corrections"])>8:
        raise ValueError("Invalid frozen correction catalog")
    return copy.deepcopy(value)


def _context(state):
    try:
        envelope=state["envelope"];snapshot=envelope["snapshot"];provenance=envelope["provenance"]
        publication=state["publication"]
        # Reuse the existing deterministic snapshot/correction validator. This
        # verifies stats against events and contiguous history to current payloads.
        build_recap(snapshot,provenance)
        snapshot_body={key:val for key,val in snapshot.items() if key!="state_digest"}
        digest=snapshot["state_digest"];watermark=snapshot["upto_ms"]
        events=snapshot["events"];visible=snapshot["event_ids"];revisions=provenance["event_revisions"]
        if (provenance["synthetic"] is not True or not isinstance(digest,str) or not DIGEST.fullmatch(digest)
                or _sha(_canonical(snapshot_body).encode())!=digest
                or envelope["state_digest"]!=digest or publication["state_digest"]!=digest
                or type(watermark) is not int or envelope["through_ms"]!=watermark
                or publication["event_time"]["through_ms"]!=watermark
                or not isinstance(events,list) or not isinstance(visible,list)
                or [row["id"] for row in events]!=visible
                or len(set(visible))!=len(visible)
                or any(type(row["at_ms"]) is not int or row["at_ms"]>watermark for row in events)
                or not isinstance(revisions,dict) or set(revisions)!=set(visible)
                or any(type(item) is not int or item<1 for item in revisions.values())
                or not _identifier(envelope["engine_epoch"]) or not _identifier(publication["stream_id"])
                or state["audience"] not in ("casual","analyst") or state["language"] not in ("en","es")
                or not DIGEST.fullmatch(state["durability"]["fixture_sha256"])
                or not DIGEST.fullmatch(state["durability"]["journal_head_sha256"])):
            raise ValueError("Invalid fresh desk context")
        return {"state_digest":digest,"upto_ms":watermark,"event_revisions":copy.deepcopy(revisions),
                "engine_epoch":envelope["engine_epoch"],"stream_id":publication["stream_id"],
                "audience":state["audience"],"language":state["language"],
                "source_digest":state["durability"]["fixture_sha256"],"source_id":provenance["source_id"],
                "journal_head_sha256":state["durability"]["journal_head_sha256"]}
    except (KeyError,TypeError,ValueError,AttributeError) as error:
        raise ValueError("Unverifiable fresh desk context") from error


def _stale_goal(case,output,state,context):
    """A narrow score grammar plus verified visible goal withdrawal, not gold labels."""
    snapshot=state["envelope"]["snapshot"]
    try:
        verified=build_recap(snapshot,state["envelope"]["provenance"])
    except (KeyError,TypeError,ValueError):
        return None
    events={row["id"]:row for row in snapshot["events"]}
    teams=snapshot["match"]["teams"]
    dropped=[row["text"] for row in case["draft_clauses"] if row["id"] in output["drop"]]
    claimed_teams=set()
    for text in dropped:
        match=re.fullmatch(r"([A-Za-z][A-Za-z ]{0,60}) lead(?:s)? (?:one[- ]nil|1[-:]0)[.!]?",text.strip(),re.I)
        if not match:continue
        name=match.group(1).strip().casefold()
        matches=[team["id"] for team in teams if name==team["name"].casefold()
                 or name==team["name"].split()[0].casefold()]
        if len(matches)==1:claimed_teams.add(matches[0])
    if not claimed_teams:return None
    audit=state["envelope"]["provenance"].get("corrections",[])
    if not isinstance(audit,list):return None
    for row in audit:
        try:
            event_id=row["target_event_id"];before=row["before"];after=row["after"]
            verified_withdrawal=any(claim["type"]=="goal" and claim["event_id"]==event_id
                and claim["team_id"]==after.get("team_id") and claim["current_revision"]==context["event_revisions"].get(event_id)
                for claim in verified["withdrawn_claims"])
            if (row["source_id"]!=context["source_id"] or event_id not in events
                    or not verified_withdrawal
                    or type(row["from_revision"]) is not int or type(row["to_revision"]) is not int
                    or row["to_revision"]!=row["from_revision"]+1
                    or context["event_revisions"].get(event_id)!=row["to_revision"]
                    or before["id"]!=event_id or after["id"]!=event_id or after!=events[event_id]
                    or before["type"]!="shot" or after["type"]!="shot"
                    or before["team_id"]!=after["team_id"] or after["team_id"] not in claimed_teams
                    or before["goal"] is not True or after["goal"] is not False
                    or before["at_ms"]>context["upto_ms"] or after["at_ms"]>context["upto_ms"]):continue
            other_fields=set(before)|set(after)
            if any(before.get(key)!=after.get(key) for key in other_fields-{"goal"}):continue
            team=after["team_id"]
            totals=snapshot["stats"]["total"]["teams"]
            current_score=[totals[item["id"]]["goals"] for item in teams]
            current_team=totals[team]["goals"]
            other=[totals[item["id"]]["goals"] for item in teams if item["id"]!=team]
            # Prove this removed goal supplied the specific prior 1-0 claim.
            if current_team!=0 or other!=[0] or current_score!=[0,0]:continue
            return {"reason":"stale_revision","source":"deterministic current correction audit",
                    "explanation":"The removed 1-0 lead clause depends on a visible goal withdrawn by the current event revision. The recorded model reason is preserved separately.",
                    "evidence_ids":[event_id],"from_revision":row["from_revision"],"to_revision":row["to_revision"]}
        except (KeyError,TypeError,ValueError):continue
    return None


class AdvisoryReview:
    """Per-Desk transient review service; never persist approval or call providers."""
    def __init__(self,evidence_root:Path):
        self.evidence_root=Path(evidence_root)
        self._session=uuid4().hex
        self._advice=None;self._draft=None;self._status="idle";self._operations={}
        self._cases={};self._receipts={};self._hashes={};self._evidence_error=None
        self._load()

    def _read(self,name):
        path=self.evidence_root/name
        if path.is_symlink():raise ValueError("Evidence symlinks are forbidden")
        with path.open("rb") as handle:raw=handle.read(131073)
        if len(raw)>131072:raise ValueError("Evidence exceeds byte bound")
        digest=_sha(raw)
        if EVIDENCE_SHA256.get(name)!=digest:raise ValueError("Pinned recorded evidence hash mismatch")
        return raw,digest

    def _load(self):
        expected={"cases.json",*(f"RECEIPT_{case_id}.json" for case_id in CASE_IDS)}
        if set(EVIDENCE_SHA256)!=expected:raise ValueError("Recorded evidence pins are incomplete")
        raw,digest=self._read("cases.json");catalog=_json(raw)
        if (not isinstance(catalog,dict) or set(catalog)!={"schema_version","cases"}
                or catalog["schema_version"]!=1 or not isinstance(catalog["cases"],list)
                or len(catalog["cases"])!=4):raise ValueError("Invalid frozen case catalog")
        self._hashes["cases.json"]=digest
        for entry in catalog["cases"]:
            if (not isinstance(entry,dict) or set(entry)!={"id","input"} or entry["id"] not in CASE_IDS
                    or entry["id"] in self._cases):raise ValueError("Invalid frozen case ID")
            case_id=entry["id"];case=_case(entry["input"])
            name=f"RECEIPT_{case_id}.json";raw,receipt_hash=self._read(name);receipt=_json(raw)
            binding={"input_sha256":_sha(_canonical(case,ascii=False).encode()),
                     "snapshot_digest":case["snapshot_digest"],"watermark_ms":case["watermark_ms"],
                     "event_revisions":case["event_revisions"]}
            if (not isinstance(receipt,dict) or receipt.get("status")!="reviewed" or receipt.get("binding")!=binding
                    or not isinstance(receipt.get("trace"),list) or len(receipt["trace"])>32
                    or not isinstance(receipt.get("evidence_mode"),str)
                    or receipt["evidence_mode"] not in ("real local model","injected transport")):
                raise ValueError("Recorded receipt does not bind the frozen case")
            output=_output(receipt.get("validated_output"),case)
            observed=receipt.get("observed",{})
            if not isinstance(observed,dict):raise ValueError("Invalid recorded observation")
            raw_output=observed.get("raw_output")
            if not isinstance(raw_output,str) or _json(raw_output)!=output:raise ValueError("Raw recorded reason/output was altered")
            self._cases[case_id]=case;self._receipts[case_id]=receipt;self._hashes[name]=receipt_hash

    def _check_files(self):
        if self._evidence_error is not None:return False
        try:
            for name,digest in self._hashes.items():
                if self._read(name)[1]!=digest:raise ValueError("Recorded evidence changed")
            return True
        except (OSError,ValueError):
            self._advice=self._draft=None;self._status="evidence_error"
            self._evidence_error="Recorded evidence is unavailable or its pinned hash changed."
            return False

    def _available(self,case,context):
        return (context["source_digest"]==SOURCE_DIGEST and context["source_id"]==SOURCE_ID
                and context["state_digest"]==case["snapshot_digest"] and context["upto_ms"]==case["watermark_ms"]
                and context["event_revisions"]==case["event_revisions"]
                and context["audience"]==case["audience"] and context["language"]=="en")

    def invalidate(self):
        """Discard transient advice/approval under the owning desk's control lock.

        Timeout/recovery policy is explicit even when the factual context has
        not changed. Keep operation receipts so retries cannot restore a draft.
        This never changes durable facts, evidence or on-air publication.
        """
        self._advice=self._draft=None
        if self._status!="evidence_error":self._status="cleared"

    def state(self,desk_state):
        valid=self._check_files();context=None
        try:context=_context(desk_state)
        except ValueError:valid=False
        if self._advice and (not valid or context!=self._advice["binding"]["context"]):
            self._advice=self._draft=None
            if self._status!="evidence_error":self._status="stale"
        cases=[]
        for case_id in CASE_IDS:
            available=bool(valid and context and self._available(self._cases[case_id],context))
            row={"case_id":case_id,"available":available,
                 "unavailable_reason":"" if available else "Recorded review requires its exact visible 50s facts, revisions, source and English casual view."}
            if available:row["label"]="Recorded producer draft "+case_id
            cases.append(row)
        return {"mode":"recorded","live_available":False,"label":"RECORDED CLAIM REVIEW - no live model call",
                "qualification":"PRODUCER COPY DRAFT ONLY - no on-air publication",
                "evaluation":{"strict_passes":3,"total":4,"status":"NO_GO",
                              "qualification":"Original frozen pilot: 3/4 strict passes. Recorded model reasons remain unchanged; this is not a general accuracy estimate."},
                "status":self._status,"cases":cases,"advice":copy.deepcopy(self._advice),
                "producer_copy_draft":copy.deepcopy(self._draft),"evidence_error":self._evidence_error,
                "new_provider_requests":0,"approval_persisted":False}

    def control(self,command,desk_state):
        if not isinstance(command,dict) or not _identifier(command.get("operation_id")):
            raise ValueError("Bounded operation ID required")
        action=command.get("action");operation_id=command["operation_id"]
        fields={"review_copy":{"action","case_id","operation_id"},
                "approve_copy":{"action","advice_id","operation_id"},"clear_copy":{"action","operation_id"}}
        if not isinstance(action,str) or action not in fields or set(command)!=fields[action]:raise ValueError("Unexpected advisory fields")
        body={key:value for key,value in command.items() if key!="operation_id"}
        key=_canonical(body)
        current=self.state(desk_state)
        if operation_id in self._operations:
            if self._operations[operation_id]!=key:raise ValueError("Conflicting operation ID")
            return current
        if len(self._operations)>=256:raise ValueError("Advisory operation capacity reached")
        if current["evidence_error"]:raise ValueError(current["evidence_error"])
        if action=="clear_copy":
            self.invalidate()
        elif action=="review_copy":
            case_id=body["case_id"]
            if not isinstance(case_id,str) or case_id not in CASE_IDS:raise ValueError("Unknown recorded case")
            context=_context(desk_state);case=self._cases[case_id]
            if not self._available(case,context):raise ValueError("Recorded review context unavailable")
            receipt=self._receipts[case_id];output=receipt["validated_output"]
            facts=[{"fact_id":fact_id,**copy.deepcopy(case["facts"][fact_id])} for fact_id in output["facts"]]
            kept_evidence=sorted({item for fact in facts for item in fact["evidence_ids"]})
            classification=_stale_goal(case,output,desk_state,context)
            if classification is None:
                classification={"reason":"unclassified",
                                "source":"deterministic conservative fallback",
                                "explanation":"No withdrawn-goal classification is proven by the current correction audit and removed clause. The recorded model reason remains a separate advisory judgment.",
                                "evidence_ids":[]}
            self._advice={"advice_id":"advice_"+uuid4().hex,"case_id":case_id,
                "binding":{"context":context,"input_sha256":receipt["binding"]["input_sha256"],
                           "receipt_sha256":self._hashes[f"RECEIPT_{case_id}.json"],"session_id":self._session},
                "decision":output["decision"],"keep":copy.deepcopy(output["keep"]),"drop":copy.deepcopy(output["drop"]),
                "clauses":[{**copy.deepcopy(row),"disposition":"keep" if row["id"] in output["keep"] else "drop",
                            "evidence_ids":kept_evidence if row["id"] in output["keep"] else classification["evidence_ids"]} for row in case["draft_clauses"]],
                "facts":facts,"fact_reference_qualification":"Recorded model-proposed support for kept clauses; ID joins alone do not establish semantic support.",
                "raw_reason":output["reason"],"deterministic_classification":classification,
                "recorded_trace":copy.deepcopy(receipt["trace"]),"receipt_sha256":self._hashes[f"RECEIPT_{case_id}.json"],
                "sdk_versions":copy.deepcopy(receipt.get("sdk_versions",{})),"evidence_mode":receipt["evidence_mode"],
                "test_mode":receipt["evidence_mode"]=="injected transport","historical_only":True,
                "can_approve":bool(output["keep"] and output["decision"]!="withhold")}
            self._draft=None;self._status="reviewed"
        else:
            advice_id=body["advice_id"]
            if (not isinstance(advice_id,str) or self._advice is None or advice_id!=self._advice["advice_id"]
                    or not self._advice["can_approve"] or self._status!="reviewed"):
                raise ValueError("Current approvable advice required; stale or withheld advice cannot be approved")
            clauses=[copy.deepcopy(row) for row in self._advice["clauses"] if row["disposition"]=="keep"]
            self._draft={"advice_id":advice_id,"case_id":self._advice["case_id"],
                         "text":" ".join(row["text"] for row in clauses),"clauses":clauses,
                         "binding":copy.deepcopy(self._advice["binding"]),"label":"PRODUCER COPY DRAFT - not on air",
                         "on_air":False,"approved_operation_id":operation_id}
            self._advice["can_approve"]=False;self._status="approved_copy_draft"
        self._operations[operation_id]=key
        return self.state(desk_state)
