"""One bounded native Ollama selection Agent; deterministic code owns facts.

Importing this module and the default adapter perform no model requests.
The owner must explicitly enable a configured adapter after reserving resources.
"""
from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
import json
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from agent_framework import Agent, agent_middleware, chat_middleware
from agent_framework.ollama import OllamaChatClient
import httpx
from ollama import AsyncClient

SELECTION_KEYS = {"candidate_id", "explanation_type", "evidence_ids"}
IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")
RAW_LIMIT = 4096
BODY_LIMIT = 65536


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _exception_chain(error):
    chain, seen = [], set()
    while error is not None and id(error) not in seen and len(chain) < 8:
        seen.add(id(error))
        chain.append(error)
        error = error.__cause__ or error.__context__
    return chain


def _strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))


def _endpoint(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.port != 11434 or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("only literal loopback HTTP Ollama port11434 is permitted")
    return value.rstrip("/")


@dataclass(frozen=True)
class SelectionConfig:
    endpoint: str = "http://127.0.0.1:11434"
    model_id: str = "gemma4:12b"
    enabled: bool = False
    enabled_until_ms: int | None = None
    timeout_s: float = 12.0
    max_output_tokens: int = 48
    selection_mode: str = "candidate_id"
    think: bool | None = False
    max_calls: int = 4
    wall_budget_s: float = 50.0
    cleanup_timeout_s: float = 0.25

    def __post_init__(self):
        _endpoint(self.endpoint)
        if self.model_id not in {"gemma4:12b", "qwen2.5:14b"}:
            raise ValueError("model must be an inspected installed local tag")
        if self.selection_mode not in {"candidate_id", "full_selection"}:
            raise ValueError("unsupported selection_mode")
        if self.think is not None and type(self.think) is not bool:
            raise ValueError("think must be a bool or None")
        token_limit = 48 if self.selection_mode == "candidate_id" else 128
        if not (0 < self.timeout_s <= 12 and 0 < self.max_output_tokens <= token_limit
                and 0 < self.max_calls <= 4 and 0 < self.wall_budget_s <= 50
                and 0 < self.cleanup_timeout_s <= 0.25):
            raise ValueError("configuration exceeds the milestone budget")


def _candidates(request):
    if not isinstance(request, dict):
        raise ValueError("request must be a dict")
    source = request.get("candidates")
    if source is None:
        source = request.get("snapshot", {}).get("candidates")
    if not isinstance(source, list) or len(source) > 8:
        raise ValueError("request requires at most8 supplied candidates")
    projected = []
    seen = set()
    for candidate in source:
        if not isinstance(candidate, dict) or not SELECTION_KEYS <= set(candidate):
            raise ValueError("candidate selection fields missing")
        for key in ("candidate_id", "explanation_type"):
            if not isinstance(candidate[key], str) or not IDENTIFIER.fullmatch(candidate[key]):
                raise ValueError("invalid candidate identifier")
        ids = candidate["evidence_ids"]
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 24
                or any(not isinstance(value, str) or not IDENTIFIER.fullmatch(value) for value in ids)
                or len(ids) != len(set(ids))):
            raise ValueError("invalid candidate evidence IDs")
        if candidate["candidate_id"] in seen:
            raise ValueError("duplicate candidate ID")
        seen.add(candidate["candidate_id"])
        row = {key: copy.deepcopy(candidate[key]) for key in sorted(SELECTION_KEYS)}
        # Verified core metrics may inform the choice, but may never be returned.
        if "metrics" in candidate:
            row["metrics"] = copy.deepcopy(candidate["metrics"])
        projected.append(row)
    if len(_json(projected).encode()) > 12000:
        raise ValueError("candidate context exceeds byte budget")
    return projected


def selection_schema(candidates, selection_mode="full_selection"):
    if selection_mode == "candidate_id":
        return {"type": "object", "additionalProperties": False, "required": ["candidate_id"],
                "properties": {"candidate_id": {"type": "string", "enum": [row["candidate_id"] for row in candidates]}}}
    return {
        "type": "object", "additionalProperties": False,
        "required": sorted(SELECTION_KEYS),
        "properties": {
            "candidate_id": {"type": "string", "enum": [row["candidate_id"] for row in candidates]},
            "explanation_type": {"type": "string", "enum": sorted({row["explanation_type"] for row in candidates})},
            "evidence_ids": {"type": "array", "minItems": 1, "maxItems": 24, "items": {
                "type": "string", "enum": sorted({value for row in candidates for value in row["evidence_ids"]})}},
        },
    }


def validate_choice(raw, candidates, selection_mode="full_selection"):
    if not isinstance(raw, str) or len(raw.encode()) > RAW_LIMIT:
        raise ValueError("model content exceeds byte limit")
    selection = _strict_json(raw)
    if selection_mode == "candidate_id":
        if not isinstance(selection, dict) or set(selection) != {"candidate_id"} or not isinstance(selection["candidate_id"], str):
            raise ValueError("selection must contain exactly candidate_id")
        matching = next((row for row in candidates if row["candidate_id"] == selection["candidate_id"]), None)
        if matching is None:
            raise ValueError("unknown candidate_id")
        # Only canonical engine-supplied values cross into the fact gate.
        return {key: copy.deepcopy(matching[key]) for key in sorted(SELECTION_KEYS)}
    if not isinstance(selection, dict) or set(selection) != SELECTION_KEYS:
        raise ValueError("selection must contain exactly three keys")
    if not isinstance(selection["candidate_id"], str) or not isinstance(selection["explanation_type"], str):
        raise ValueError("selection identifiers must be strings")
    if not isinstance(selection["evidence_ids"], list) or any(not isinstance(value, str) for value in selection["evidence_ids"]):
        raise ValueError("selection evidence must be strings")
    matching = next((row for row in candidates if row["candidate_id"] == selection["candidate_id"]), None)
    if matching is None or selection != {key: matching[key] for key in SELECTION_KEYS}:
        raise ValueError("selection does not exactly match one supplied candidate")
    return selection


class BoundedOllamaTransport(httpx.AsyncBaseTransport):
    """Allow one non-streaming native chat request and bounded response bytes."""
    def __init__(self, config, trace, observed, inner=None):
        self.config, self.trace, self.observed = config, trace, observed
        self.inner = inner if inner is not None else httpx.AsyncHTTPTransport(
            retries=0, limits=httpx.Limits(max_connections=1, max_keepalive_connections=0))
        self.sent = 0
        self.closed = False

    async def handle_async_request(self, request):
        url = request.url
        if (str(url.copy_with(path="/", query=None)).rstrip("/") != _endpoint(self.config.endpoint)
                or request.method != "POST" or url.path != "/api/chat" or url.query):
            raise ValueError("transport rejected non-allowlisted request")
        if self.sent:
            raise ValueError("transport rejected a retry or extra request")
        body = await request.aread()
        if len(body) > 24000:
            raise ValueError("request exceeds byte budget")
        data = _strict_json(body)
        self.observed["request_policy_fields"] = {"keys": sorted(data), "model": data.get("model"),
            "stream": data.get("stream"), "options": data.get("options"), "tools_present": bool(data.get("tools")), "keep_alive": data.get("keep_alive"), "think": data.get("think")}
        if (data.get("model") != self.config.model_id or data.get("stream") is not False
                or data.get("options", {}).get("num_predict") != self.config.max_output_tokens
                or "keep_alive" in data or bool(data.get("tools"))
                or (self.config.think is not None and data.get("think") is not self.config.think)
                or any(key in data.get("options", {}) for key in ("num_gpu", "num_ctx", "num_thread"))):
            raise ValueError("transport rejected model/resource/options mismatch")
        self.sent += 1
        self.observed["request_sha256"] = hashlib.sha256(body).hexdigest()
        self.observed["request_body"] = data
        self.trace.append({"source": "httpx transport", "event": "request_dispatched", "path": "/api/chat", "request_sha256": self.observed["request_sha256"]})
        response = None
        try:
            response = await self.inner.handle_async_request(request)
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > BODY_LIMIT:
                    raise ValueError("response exceeds byte budget")
            self.observed["response_body_sha256"] = hashlib.sha256(content).hexdigest()
            if response.status_code == 200:
                envelope = _strict_json(bytes(content))
                message = envelope.get("message", {})
                raw = message.get("content", "")
                self.observed["raw_response"] = raw.encode()[:RAW_LIMIT].decode(errors="ignore") if isinstance(raw, str) else ""
                self.observed["raw_response_truncated"] = isinstance(raw, str) and len(raw.encode()) > RAW_LIMIT
                self.observed["server"] = {key: envelope.get(key) for key in (
                    "model", "done", "done_reason", "prompt_eval_count", "eval_count", "total_duration", "load_duration")}
                if (envelope.get("model") != self.config.model_id or envelope.get("done") is not True
                        or type(envelope.get("eval_count")) is not int
                        or not 0 <= envelope["eval_count"] <= self.config.max_output_tokens
                        or message.get("tool_calls") or self.observed["raw_response_truncated"]):
                    raise ValueError("incomplete, oversized or unexpected model response")
            self.trace.append({"source": "httpx transport", "event": "response_received", "http_status": response.status_code, "bytes": len(content)})
            return httpx.Response(response.status_code, headers=response.headers, content=bytes(content), extensions=response.extensions)
        except asyncio.CancelledError:
            self.observed["transport_cancelled"] = True
            self.trace.append({"source": "httpx transport", "event": "client_task_cancelled"})
            raise
        finally:
            if response is not None:
                self.observed.setdefault("cleanup_started", time.perf_counter())
                try:
                    await asyncio.wait_for(response.aclose(), timeout=self.config.cleanup_timeout_s / 2)
                except Exception as error:
                    self.observed["response_close_error"] = type(error).__name__
                self.observed["response_closed"] = response.is_closed

    async def aclose(self):
        await self.inner.aclose()
        self.closed = True


class CandidateSelector:
    """Retain one instance for the whole milestone; counters never reset per call."""
    def __init__(self, config=None, *, test_transport=None, initial_calls=0, initial_wall_ms=0):
        self.config = config or SelectionConfig()
        if (type(initial_calls) is not int or not 0 <= initial_calls <= self.config.max_calls
                or not isinstance(initial_wall_ms, (int, float)) or not 0 <= initial_wall_ms <= self.config.wall_budget_s * 1000):
            raise ValueError("invalid retained milestone counters")
        self.test_transport = test_transport
        self.evidence_mode = "injected transport; no real inference" if test_transport is not None else "real local model"
        self._lock = threading.Lock()
        self._calls = initial_calls
        self._spent_s = initial_wall_ms / 1000
        self._inflight = False
        self._cleanup_failed = False

    def budget_status(self):
        return {"attempts_started": self._calls, "real_calls_started": self._calls if self.test_transport is None else 0,
                "inflight": self._inflight, "max_calls": self.config.max_calls,
                "wall_spent_ms": round(self._spent_s * 1000, 3), "wall_budget_ms": round(self.config.wall_budget_s * 1000),
                "max_output_tokens": self.config.max_output_tokens, "client_timeout_ms": round(self.config.timeout_s * 1000),
                "selection_mode": self.config.selection_mode, "think": self.config.think,
                "retries": 0, "evidence_mode": self.evidence_mode,
                "enabled_until_ms": self.config.enabled_until_ms, "cleanup_failed": self._cleanup_failed}

    def preflight(self, request: dict) -> dict:
        """Pure catalog validation shared by the producer and async adapter.

        This reads only the immutable selection mode and supplied request. It
        does not inspect resources, time, counters, locks or provider state.
        """
        minimum = 2 if self.config.selection_mode == "candidate_id" else 1
        try:
            candidates = _candidates(request)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as error:
            return {"eligible": False, "status": "invalid_request", "reason": str(error)[:200],
                    "candidates": [], "candidate_count": None, "minimum_candidates": minimum}
        count = len(candidates)
        if count == 0:
            status, reason = "no_candidates", "No current supplied pattern candidates."
        elif count < minimum:
            status = "insufficient_candidates"
            reason = f"{self.config.selection_mode} selection requires at least {minimum} valid supplied candidates; found {count}."
        else:
            status, reason = "eligible", f"{count} valid supplied candidates meet the {minimum}-candidate minimum."
        return {"eligible": status == "eligible", "status": status, "reason": reason,
                "candidates": candidates, "candidate_count": count, "minimum_candidates": minimum}

    async def select_candidate(self, request: dict) -> dict:
        start = time.perf_counter()
        trace, observed = [], {}
        result = {"selection": None, "status": "disabled", "elapsed_ms": 0,
                  "model_id": self.config.model_id, "endpoint": self.config.endpoint,
                  "trace": trace, "raw_response": "", "evidence_mode": self.evidence_mode, "requests_dispatched": 0,
                  "selection_mode": self.config.selection_mode, "think_requested": self.config.think,
                  "sdk_versions": {name: version(name) for name in ("agent-framework-core", "agent-framework-ollama", "ollama")},
                  "cleanup": {"client_closed": None, "transport_closed": None, "server_cancellation": "not measured; no cancellation claim"}}
        if not self.config.enabled:
            result["budget"] = self.budget_status()
            return result
        if self.test_transport is None and (type(self.config.enabled_until_ms) is not int or self.config.enabled_until_ms <= time.time() * 1000):
            result.update(status="authorization_expired", budget=self.budget_status())
            return result
        eligibility = self.preflight(request)
        result["eligibility"] = {key: copy.deepcopy(value) for key, value in eligibility.items() if key != "candidates"}
        if not eligibility["eligible"]:
            result.update(status=eligibility["status"], eligibility_reason=eligibility["reason"], budget=self.budget_status())
            if eligibility["status"] == "invalid_request":
                result["error"] = eligibility["reason"]
            return result
        candidates = eligibility["candidates"]
        if not self._lock.acquire(blocking=False):
            result.update(status="busy", budget=self.budget_status())
            return result
        client = transport = None
        try:
            remaining = self.config.wall_budget_s - self._spent_s
            if self._cleanup_failed:
                result["status"] = "cleanup_blocked"
                return result
            if self._calls >= self.config.max_calls or remaining <= self.config.cleanup_timeout_s:
                result["status"] = "budget_exhausted"
                return result
            self._calls += 1
            self._inflight = True
            timeout_s = min(self.config.timeout_s, remaining - self.config.cleanup_timeout_s)
            if self.test_transport is None:
                timeout_s = min(timeout_s, (self.config.enabled_until_ms - time.time() * 1000) / 1000 - self.config.cleanup_timeout_s)
                if timeout_s <= 0:
                    result["status"] = "authorization_expired"
                    return result
            transport = BoundedOllamaTransport(self.config, trace, observed, self.test_transport)
            client = AsyncClient(host=_endpoint(self.config.endpoint), transport=transport,
                                 trust_env=False, follow_redirects=False,
                                 timeout=httpx.Timeout(timeout_s, connect=min(1.0, timeout_s), pool=0.1))

            @agent_middleware
            async def agent_trace(context, call_next):
                trace.append({"source": "Agent Framework agent middleware", "event": "enter", "agent_id": context.agent.id, "agent_class": type(context.agent).__name__})
                try:
                    await call_next()
                    trace.append({"source": "Agent Framework agent middleware", "event": "completed", "response_class": type(context.result).__name__})
                except BaseException as error:
                    trace.append({"source": "Agent Framework agent middleware", "event": "failed", "error_type": type(error).__name__})
                    raise

            @chat_middleware
            async def chat_trace(context, call_next):
                trace.append({"source": "Agent Framework chat middleware", "event": "enter", "client_class": type(context.client).__name__, "stream": context.stream})
                try:
                    await call_next()
                    trace.append({"source": "Agent Framework chat middleware", "event": "completed", "response_class": type(context.result).__name__})
                except BaseException as error:
                    trace.append({"source": "Agent Framework chat middleware", "event": "failed", "error_type": type(error).__name__})
                    raise

            provider = OllamaChatClient(client=client, model=self.config.model_id)
            id_only = self.config.selection_mode == "candidate_id"
            instructions = (
                "Choose the clearest supported football pattern from the supplied candidates. Return only a JSON object containing candidate_id copied exactly from one candidate. No other keys or prose."
                if id_only else
                "Choose exactly one supplied candidate for a football event explanation. Return only one JSON object with candidate_id, explanation_type and evidence_ids copied exactly from that same candidate. No prose, metrics, new IDs, extra keys or external facts. Prefer the clearest current supported pattern. The deterministic engine owns every fact."
            )
            options = {"max_tokens": self.config.max_output_tokens,
                       "response_format": selection_schema(candidates, self.config.selection_mode), "tool_choice": "none"}
            if self.config.think is not None:
                options["think"] = self.config.think
            agent = Agent(client=provider, id="touchline_candidate_selector", name="CandidateSelector",
                          instructions=instructions, default_options=options,
                          middleware=[agent_trace, chat_trace])
            result["candidate_context_sha256"] = _hash(candidates)
            catalog = [{key: row[key] for key in ("candidate_id", "explanation_type", "metrics") if key in row}
                       for row in candidates] if id_only else candidates
            result["model_context_sha256"] = _hash(catalog)
            async with asyncio.timeout(timeout_s):
                response = await agent.run("Current supplied candidates: " + _json(catalog))
            raw = response.text
            result["selection"] = validate_choice(raw, candidates, self.config.selection_mode)
            result["status"] = "selected"
        except TimeoutError:
            result["status"] = "timeout"
        except asyncio.CancelledError:
            result["status"] = "cancelled"
            raise
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            result.update(status="invalid_response", error_type=type(error).__name__)
        except Exception as error:
            chain = _exception_chain(error)
            status = "timeout" if any(isinstance(item, (TimeoutError, httpx.TimeoutException)) for item in chain) else "transport_error"
            result.update(status=status, error_type=type(error).__name__, error_chain=[type(item).__name__ for item in chain])
        finally:
            if client is not None:
                try:
                    # Ollama0.5.3 owns a httpx client but has no public close API.
                    close_start = observed.get("cleanup_started", time.perf_counter())
                    close_budget = max(.001, self.config.cleanup_timeout_s - (time.perf_counter() - close_start))
                    await asyncio.wait_for(client._client.aclose(), timeout=close_budget)
                except BaseException as error:
                    result["cleanup"]["error_type"] = type(error).__name__
                result["cleanup"]["client_closed"] = client._client.is_closed
                result["cleanup"]["transport_closed"] = transport.closed
                result["cleanup"]["response_closed"] = observed.get("response_closed")
                result["cleanup"]["transport_task_cancelled"] = observed.get("transport_cancelled", False)
                if observed.get("response_close_error"):
                    result["cleanup"]["response_close_error"] = observed["response_close_error"]
                self._cleanup_failed = (not client._client.is_closed or not transport.closed
                                        or observed.get("response_closed") is False)
                if self._cleanup_failed:
                    result["selection"] = None
                    result["status"] = "cleanup_failed"
            elapsed = time.perf_counter() - start
            if self._inflight:
                self._spent_s += elapsed
            self._inflight = False
            self._lock.release()
            result["elapsed_ms"] = round(elapsed * 1000, 3)
            result["raw_response"] = observed.get("raw_response", "")
            result["raw_response_truncated"] = observed.get("raw_response_truncated", False)
            result["server"] = observed.get("server")
            result["request_sha256"] = observed.get("request_sha256")
            result["response_body_sha256"] = observed.get("response_body_sha256")
            result["requests_dispatched"] = transport.sent if transport else 0
            if not result["requests_dispatched"]:
                result["request_policy_fields"] = observed.get("request_policy_fields")
            result["budget"] = self.budget_status()
        return result


_DEFAULT_SELECTOR = CandidateSelector()


async def select_candidate(request: dict, *, selector: CandidateSelector | None = None) -> dict:
    """Default is disabled; pass an explicitly enabled, retained selector instance."""
    return await (selector or _DEFAULT_SELECTOR).select_candidate(request)
