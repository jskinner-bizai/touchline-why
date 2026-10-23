# Hosted playtest security and test review

Independent reviewer: hosted-security-tests subagent. Scope: isolated `hosted-playtest` preparation. No cloud/network calls, deployment, credential reads, real access grants, downloads, or canonical source changes.

## Evidence status

**26 independent tests pass** against the isolated hosted adapter, in 13.320 seconds on the existing Windows/Python 3.12.2 runtime. Command: `python -B -m unittest discover -s tests -p test_hosted.py -v`. Log: `security-test-expanded.log` next to this report. These are direct-service, concurrent Python and in-memory real-handler tests plus local private-owner CLI subprocess checks. No socket was bound by this reviewer; TLS, browser and cloud behavior are not proved by them.

Tested file identities:

- `hosted_app.py`: SHA-256 `7be88eefef41b8e34bd1f060b9a238745232845233001d3df180b70affba4bd1`.
- `feedback_admin.py`: SHA-256 `2789b9e064533d0864fa68885a84f0465bbd74b79189e1ca1ad5c86d5ed10fa0`.
- `tests/test_hosted.py`: SHA-256 `4c033a34768c7cd5bdf44f0a39e88f4ad2951be42312f98a1d74b7c4a5be193a`.

Tests fix the auth/retention clock to 22 October 2026 for repeatability and use unmistakably synthetic local grants. No deployable credential or invite was created. Every test uses disposable private temporary data; it never addresses frozen/canonical state. The table below remains the acceptance checklist; the result section distinguishes what was exercised from code-inspected or pending host checks.

## Boundary and release criteria

The public landing can describe the synthetic prototype. Only explicitly granted friend/judge access may allocate a private synthetic replay. There is no open registration. Every browser session owns its own replay/journal and approved corrections; it cannot address another replay by request-supplied path or identifier. The common metadata store must scope every read/write to the authenticated session. Existing correction-preserving rewind is distinct from an explicitly labelled new synthetic match.

Feedback is optional, consented and private. It should collect bounded ratings and a bounded comment with a pseudonymous session, excluding email, name, raw IP and secret/token values. Owner triage/export should use authenticated operator filesystem/CLI access, with no public administration or listing route. JSON/JSONL export is preferred; if CSV is added, untrusted text must be protected against spreadsheet formula execution.

## High-priority risks to test

| Area | Required behavior | Test evidence needed |
|---|---|---|
| Auth | Unknown/malformed code rejected uniformly; access code not reflected, logged or saved in browser storage; cookie is opaque, HttpOnly, Secure in hosted mode, SameSite and scoped to `/` | Direct invalid/valid grant tests; actual HTTP header checks |
| Grant lifetime | Expired/revoked grant invalidates existing sessions as well as future sign-ins | Clock-controlled tests before/after expiry and revocation |
| Session isolation | Two users may view/correct/rewind/new-match concurrently without affecting one another | Two session stores with distinct watermarks, revisions and scores; reject user-chosen IDs/paths |
| CSRF/origin | Every mutation requires current session CSRF plus configured trusted origin; no wildcard CORS or forwarded-header trust | Missing/wrong token, cross-origin, forged Host and same-origin tests |
| State allocation | Failed auth/CSRF/oversize/rate-limit requests do not create Desk databases or consume grant session slots | Count files/session rows before and after rejection |
| Resource bounds | Request body/header/socket/concurrency/command/session/feedback limits are enforced before expensive allocation; the limiter itself has bounded memory or rows | Low configured caps, oversize bodies, exhaustion, concurrent requests, cleanup tests |
| Persistence | Valid corrected facts survive service close/reopen; selected insight is not renewed; incompatible/corrupt journal fails closed with a safe message | Restart service from same temporary directory; no path/traceback leak |
| Reset/new match | Rewind keeps committed correction; explicit new match affects only caller and does not silently erase another tester's history | Correct → rewind → pattern remains corrected; new_match restores only caller fixture |
| Feedback privacy | Consent required; ratings/type/length schema strict; no public enumeration, other session's rows, stack traces or secret fields | Invalid payloads, private store checks, absent public endpoints |
| Feedback retention | Retention dates are explicit and enforced by an operator/lifecycle plan, not merely a promise hidden in copy | Clock-controlled cleanup plus documented stopped-app/backup purge procedure |
| Host boundary | Only allowlisted routes and Host/public origin accepted; debug/raw database/source/model routes absent | Traversal/encoded traversal/unknown method/secret route tests |
| Logs/export | No bodies, access/session/CSRF tokens or raw client addresses logged; untrusted feedback remains text | Captured logs/error/export checks |

## Important limits

Passing direct Python tests cannot establish TLS termination, cloud network exposure, reverse-proxy trust, WAF behavior, production reliability, Azure Files/SQLite correctness, backup deletion, actual multi-device rendering or full accessibility. Hosted readiness requires a separately approved deployment and real integration smoke checks. Python's standard-library HTTP handler is a small controlled playtest adapter, not evidence of a hardened general public SaaS service.

No deployment is authorized by this review. The approved defaults remain a public descriptive landing and controlled free friend/judge access after exact hosting approval; open signup and paid/model resources remain out of scope.

## Results actually exercised

| Evidence | Result |
|---|---|
| Two authenticated sessions; separate watermarks/corrections/streams | Pass. Alice can finish corrected 0–1 while Bob finishes uncorrected 1–1, including a two-thread concurrent run |
| Rewind versus explicit fresh match | Pass. Rewind retains e010 revision2; new_match restores only the caller's fictional fixture; Bob's correction remains |
| Persistent new_match idempotence | Pass. Retrying the same action after subsequent correction, including after service restart, cannot start another fresh generation |
| Missing/wrong auth and CSRF | Pass. Unauthenticated state/control/feedback and missing/wrong mutation CSRF fail; rejected attempts do not allocate replay files |
| Session/grant lifetime and revocation | Pass. Nonrolling session expiry, grant expiry and explicit revocation invalidate existing session reads and writes |
| Persistence and eviction | Pass. Approved correction survives service close/reopen and an in-memory Desk eviction; a selected card is not renewed on restart |
| Read/control/session/match/feedback bounds | Pass. Read/control rate limits persist across restart, grant/global session and match caps are enforced, and feedback quota rejects extra submissions |
| Feedback schema/consent/privacy | Pass. Exact consent, integer 1–5 ratings, allowed coarse role/device classes, <=2000-char text and exact keys required; no public state exposes feedback or credentials; deleting Alice's feedback leaves Bob's row |
| Feedback retention boundary | Pass for invoked cleanup. At the configured collection cutoff, cleanup removes stored rows and new collection returns 410. This does not prove stopped-app, snapshots, exports or physical-volume deletion |
| Host/origin/body/parser guards | Pass using the real Handler methods with in-memory requests. Wrong/duplicate Host/Origin, oversize body, duplicate Content-Length, duplicate JSON keys, NaN and invalid top-level JSON fail |
| Cookie/security response headers | Pass in-memory. Hosted cookie and its deletion include Secure/HttpOnly/SameSite; response is no-store, no-referrer and restrictive CSP; no raw access code reflected |
| Private/admin/source route exposure | Pass for absent feedback-list/admin/export/database/source/traversal routes; unauthenticated `/api/state` rejected; query-string access codes refused |
| Owner feedback access | Pass using the real private CLI against synthetic local data. List/triage/JSONL export works; output excludes access/session/CSRF identifiers; overwrite is refused |

## Findings raised during preparation and addressed by implementation owner

1. SQLite connection context management originally committed but did not guarantee close. The owner added a closing context manager; temporary-file cleanup and repeated service restarts now pass without Windows file-lock failures.
2. A `None` CSRF argument originally shared the read-only session lookup default. The owner added an explicit read sentinel; missing mutation CSRF now fails.
3. New-match retries initially needed persistent wrapper idempotence. The owner added operation receipts; duplicate-after-restart test now passes.
4. Hosted logout initially omitted Secure on deletion of the `__Host-` cookie. The owner corrected the flag; response test passes.
5. Host/Origin lookup initially accepted only the first header. The owner added exact single-header checks; duplicate-header tests pass.

No backend changes were made by this reviewer. Implementation changes belong to the primary owner; this agent owns the independent test suite and this review.

## Remaining launch gates and review limits

- **Actual host integration pending:** TLS termination, public-origin/Host forwarding, secure-cookie acceptance in an actual browser, Container Apps health-probe Host, network isolation and deployment exposure need a separately approved hosted smoke test. In-memory request tests are not Internet tests.
- **Persistence pending:** qualify the selected mounted filesystem and SQLite locking/durability with one running instance, container replacement and two real clients. Do not assume a network Azure Files mount has local-disk SQLite semantics. Multi-replica shared SQLite is not established.
- **Retention pending:** the application supports row cleanup; full retention requires owner-approved disposal of the live volume, snapshots and private exports. If the application is stopped, request-triggered cleanup cannot execute. Do not promise guaranteed deletion by a date until the lifecycle/operator procedure is assigned and tested.
- **Capacity pending:** bounds reduce application work; they do not make public ingress/egress free or impose a provider billing hard cap. The controlled grant/session caps must leave enough judge access through the deadline; retained expired sessions consume bounded capacity until the owner reviews it.
- **Owner access pending:** production operator permissions and actual private export retrieval are not granted or tested. No public admin interface should be added simply to make feedback convenient.
- **Operational coverage:** `DeadlineReader`'s absolute request deadline and `BoundedServer`'s semaphore/queue are code-inspected; this independent suite did not simulate slow network sockets or load the actual cloud ingress. The parent owns HTTP/socket smoke work.
- **UX/accessibility:** this suite is not a device, screen-reader, keyboard or rendered-layout assessment. It does not establish the mobile journey is complete.

Recommendation: **suitable for isolated integration and owner review, not evidence of production readiness or authorization to deploy.** Keep the unresolved host/persistence/retention checks visible in the final approval packet.
