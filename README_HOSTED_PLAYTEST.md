# Touchline controlled playtest: isolated integration candidate

This combined candidate uses the frozen advisory source in `base/` and the separately prepared controlled-playtest wrapper. Both predecessor freezes are preserved. This is a local integration build, not a published service or production-readiness claim. No new model requests, downloads, cloud provisioning, access grants for real people, DNS changes, invitations or source merges were performed.

The reviewed predecessor source manifest is `b7c3d6d893e702c675f40a17f230b10d3af313b81a6e9c0cd5e9afa86a467b8e`. Supplied Windows evidence totals 334 checks: 272 base, 45 hosted and 17 hosted DOM. Claude actually reproduced 300/334 checks and 37 HTTP steps on Linux; 34 Windows-wheel-dependent checks were not reproduced there. Current review-fix results, final manifest pins and environment are recorded in the delivered verification/REVIEW_RESULT.json and RELEASE_EVIDENCE_INDEX.json. Files under `evidence/` retain their original scope and must not be relabeled as fresh results.

## What's implemented

- Public explanatory landing and controlled access-code entry. No open signup.
- One shared match workspace with producer actions and Fan/Analyst presentation depth. English/Spanish remain bounded templates.
- Recorded clause-level advice with current evidence/revision checks and explicit approval of a transient producer copy draft. Each tester has separate advice and approval state. Draft approval does not transmit text or change the broadcast card. The original four-call pilot remains NO_GO, three of four strict cases; its raw reason and the deterministic correction explanation stay separate.
- Per-browser-session durable match journals. Testers cannot select a session ID or database path. Corrections survive rewind, eviction and service restart.
- Explicit New match starts a separate personal generation and retains the archived journal; three generations per session. Duplicate requests, including after restart, cannot silently reset again.
- Optional consented private feedback: three ratings, coarse perspective/device category and bounded text. No names, email addresses, raw IPs, tracking pixels or external analytics fields. Other testers have no feedback list/export/read route.
- Private operator CLI for feedback list/triage/JSONL export and approved retention operations. No web admin route or shared administrator password.
- Exact Host/Origin checks, CSRF, hashed access/session tokens, secure HttpOnly SameSite cookies in HTTPS mode, explicit expiry/revocation, request/body/concurrency/session/storage bounds. These local controls require host integration tests before Internet exposure.
- Responsive CSS and a primary next action beside the score, human-readable correction diff, progressive evidence disclosure, last-confirmed/offline cues, and natural page flow instead of a fixed-height iframe.

The preview renders the authenticated publication directly. It does **not** claim to be an independent overlay consumer. This deliberately avoids the prior embedded-consumer race in a hosted wrapper; the original engine and separate local judge build remain unchanged.

## Local verification

```powershell
python -B -m unittest discover -s tests -v
python -B tests\http_smoke.py
node --check web\landing.js
node --check web\playtest.js
node --test web\test_advisory_hosted_ui.cjs
python -B base\verify_package.py
```

The boundary suite uses synthetic test access grants in temporary directories. The HTTP script binds an ephemeral **loopback** port, creates synthetic local grants, exercises real requests, and shuts down. It makes no external requests. These commands do not create a real friend/judge access code or invoke a model.

Actual rendered browser results are delivered separately and must match the current source manifest. Revision3 passed 476 rendered checks; that is predecessor evidence, not a revision4 pass. Physical-device, screen-reader and deployed-host checks remain separate from emulated viewports, keyboard/touch simulation and DOM tests. Consult the current release index for the latest evidence and environment.

## Local launch / no automatic credentials

```powershell
python -B hosted_app.py --data-dir ..\hosted-playtest-runtime --origin http://127.0.0.1:8896 --allow-local-http --bind 127.0.0.1 --port 8896
```

This starts a public landing on loopback but creates **no access grants**. Access-grant creation for real people is a separate owner action pending exact hosting/access approval. Synthetic automated tests are the current runnable protected-workflow demonstration. Keep all private runtime data outside this package, never in a public repository or image.

Production launch contract, after approval and host qualification:

```text
python -B hosted_app.py --data-dir /data --origin https://<approved-host> --bind 0.0.0.0 --port 8080
```

Only one approved process/revision may own these SQLite journals. Do not run multiple replicas or concurrent old/new writers against the mount. `/healthz` checks a metadata read, not durability, write safety or deployment readiness.

## Access/resource boundaries

| Boundary | Current default |
|---|---|
| Signup | None; owner-created friend/judge grant only |
| Session lifetime | Four hours, never extended by polling; code re-entry creates a new session/fresh match and retains the old journal without resuming it; grant expiry/revocation applies immediately |
| Active sessions | 100 total across unexpired sessions on unexpired, enabled grants; ended rows and journals remain in history and do not occupy active slots |
| Judge reservation | One fifth of total active capacity, rounded down: the default 20 slots cannot be filled by friends. Friends may occupy 80 slots; judges can use remaining shared slots up to 100 total. No active session is evicted. |
| Grant capacity | Owner-configured concurrent active sessions per code, at most the global active cap; default 10. Logout, session expiry, grant expiry or revocation releases active allowance without deleting history. No real grant exists yet. |
| Sign-in budgets | Unknown/expired/revoked codes: 60 invalid attempts/10min globally and 5 per hashed guess/10min. Recognized active grants: per code, friend 15/judge 30 per 10min and friend 30/judge 90 per hour; separate valid role ceilings friend 150/judge 300 per hour. Invalid attempts and full-grant retries cannot consume other codes' valid allowance; forwarded headers and the compatibility client key are not identities. |
| Match generations | Three per session, previous corrected journal retained |
| Active engine cache | Eight; evicted facts restore from journal, old selected insight not renewed |
| Read/control | 90 state reads/minute/session; 20 changes/minute for friends, 60 for judge-role grants |
| Grant daily changes | 600 friend / 10,000 judge; offline fallback required if any cap interferes with full judging |
| Feedback | Five submissions/day/session, 1,000 stored rows, text <=2,000 server characters (client <=1,000) |
| HTTP | 16 worker slots, queue16, request deadline8s, socket inactivity2s, body16KiB, header/target bounds |
| Storage | 100MiB application data budget checked before replay writes; failure preserves old journals |
| Model/provider | No model import/endpoint/calls; no optional inference route |

The rules allow a private judge site with supplied credentials, but Â§4.8 also requires free access without restriction through the judging period. Do not claim these caps automatically satisfy that requirement. Give judges a suitably provisioned dedicated grant, test the entire evaluation, and retain the unrestricted downloadable local build as a free fallback at a durable verified link. No public download/link was established by this work.

Judge availability must extend through **2026-11-11 07:59 UTC** (November10 23:59Pacific). The operator CLI rejects a judge grant expiry before08:00UTC that day. A browser session lasts four hours. Entering an active access code again creates a **new session and a fresh match**; it does not renew or resume the expired session's journal. The old journal is retained privately, but no resume feature is promised. Grant/session allowances and hosting capacity must support the required evaluation period, with no payment or open-signup requirement.

One active code can use at most 90 judge or 30 friend sign-ins per fixed hour, below its role's shared hourly ceiling. This prevents the reproduced single-code rate-budget lockout; it does not reserve a slot for every grant. Multiple valid codes can still reach their role's ceiling. Active-session capacity and retained storage are separate bounded resources. Exhausted grants, active capacity and the friend reservation are checked before valid rate charging. Those checks, rate updates and session insertion share one immediate SQLite transaction, so concurrent metadata admissions cannot exceed the active cap or spend valid budget on a rejected capacity request. Limits persist across service restarts and rate counters reset at fixed ten-minute/hour boundaries; they are not rolling-window limits.

Admission counts a session only while both its session expiry and grant expiry are strictly in the future and the grant is enabled. At the exact expiry boundary it no longer occupies global or per-code capacity. Re-entering the code creates a new session and fresh match; historical sessions, feedback and journals remain retained, and old credentials remain unavailable. Cleanup releases only inactive cached desk handles during admission, expired-token checks and grant revocation. Active judge handles are not selected for that cleanup. The original cache's separate size-based eviction still retains journals and does not revoke an active session.

Judge reservation is based on the number of active **friend** sessions, not on total occupancy. For example, 60 judges plus 20 friends leave 20 shared slots usable by either role; 80 friends leave 20 slots that only judges may fill. Reservation does not guarantee admission after the global active cap is reached, reserve a slot for every judge code, or bypass rate/storage limits. Configurations below five total slots round the reserved fifth down to zero and are unsuitable for this public-load separation promise. Size real grants and the qualified host for the judging window, rehearse the planned load and retain the unrestricted downloadable fallback.

Retaining history is not unbounded storage approval. The existing 100MiB budget is now also checked before a new session is allocated; no rows or journals are silently deleted to make room. A full retained store requires an approved operational capacity/retention decision. Local admission tests do not establish cloud filesystem behavior or a guarantee against resource saturation. The one-process journal-writer deployment contract still applies; a concurrent-metadata test does not authorize multiple live journal writers.

There is intentionally no application claim of per-person IP limits: a reverse proxy can place every judge behind one TCP peer, and `Forwarded`/`X-Forwarded-For` values supplied by a caller are untrusted. No raw address is stored in application rate buckets. Before deployment, qualify the exact ingress's trusted-proxy boundary and edge request/connection limits with same-NAT multi-judge and spoofed-header tests. These local per-code/role tests are not evidence of deployed ingress protection or protection against network saturation.

## Private feedback operation

After approved deployment, the owner/review agent uses the provider's authenticated control plane and private mounted data:

```text
python -B feedback_admin.py --data-dir /data list
python -B feedback_admin.py --data-dir /data triage <feedback-id> reviewing
python -B feedback_admin.py --data-dir /data export --output <private-path-outside-live-data>.jsonl
```

JSONL is deliberate: untrusted comments must not become executable spreadsheet formulas. Exports omit session token/CSRF/access/session IDs. Read access is an owner operation; no public admin API is added. There is no automatic notification or message to anyone. Review incoming feedback with `list` when desired.

The product says **planned retention until18November2026**. The service deletes feedback rows on startup/feedback collection after that cutoff and refuses new collection; testers can delete their own feedback while their session is active. Launch still requires an operational purge/volume-disposal plan covering stopped apps, backups and exports. A SQL delete is not a claim of cryptographic erasure. Azure/platform connection metadata logging and retention must be configured and disclosed separately; app code suppresses raw request logs.

## Hosting proposal and exact missing step

**Proposed**, not provisioned: personal Azure Container Apps, East US, Consumption0.25vCPU/0.5GiB, single replica, TLS ingress, public landing and controlled synthetic sessions; private owner feedback. Proposed budget **USD25 total through judging**, subject to live regional quote and explicit approval. Current authorized spend is **USD0**. Budget alerts do not enforce a dollar hard cap.

Read-only metadata inspection found no Azure CLI and no local Azure profile. No personal account/subscription/resource group/Container Apps environment or billing ownership was verified. No login, token-store read or secret inspection was performed. Docker CLI was present but engine/image listing failed; no image was built or pulled.

**Smallest missing user step:** identify the personal Azure subscription and billing owner for read-only resource/price inspection. Then approve the exact destination, region, quoted ceiling/duration, access policy, private-data/retention boundary and named resources before any provisioning, security grant, registry push, DNS, credential creation or publishing. No employer subscription/funds may be used.

Persistent SQLite on Azure Files is a **conditional design**, not qualified production storage. The official SQLite guidance warns about network filesystem locking/sync semantics. Require real mount/restart/lock/fsync/rollout writer-exclusion tests; otherwise change the persistence design before public judge hosting. Deployment templates do not remove that gate. See [hosting plan](deploy/HOSTING_PLAN.md) and [approval boundary](deploy/APPROVAL_BOUNDARY.md).

## Integration procedure

1. Preserve primary source and both predecessor packages. Verify `INTEGRATION_MANIFEST.json`, its SHA file and `base/PACKAGE_MANIFEST.json` before running this combined source.
2. Use the complete combined subtree. The earlier additions-only patch and workstation packaging helper remain in the preserved predecessor ZIP, outside this runnable distribution. They are not the current installation procedure. The current base already includes the approved offline advisory integration.
3. Re-run local tests against this combined source. The wrapper creates one recorded-only `app_advisory.AdvisoryDesk` per tester match and promises zero live calls. Its public response excludes private review bindings, tokens, raw wire bodies and runtime paths. Closing/evicting a desk clears draft approval; committed match corrections remain in its journal.
4. Render320/390px phone,768px tablet,1280px desktop and perform keyboard/screen-reader checks against the actual integrated UI. Use [journey acceptance](design/JOURNEY_AND_DESIGN_ACCEPTANCE.md), not a generic dashboard checklist.
5. Only after exact hosting approval and host validation, build a digest-pinned image, configure a private persistent store and real grants, verify HTTPS/signed-out/judge workflows and free fallback delivery. Preserve source/video/test-build correspondence.

The sibling untested `playtest-prep` draft was inspected. Its explicit engine-snapshot and outside-source-path boundaries informed the same controls here. Its routes, ephemeral cleanup and incomplete deployment authentication were not merged blindly. This isolated tested slice is the proposed hosting candidate until the primary owner integrates it.

## Release evidence inventory

The final release evidence index must record the actual deployed/demo URL and access proof through the judge window, public GitHub URL and exact Git commit, fresh video and its matching source, corrected manifest pins and run evidence. These items are independent of passing tests. Consult the delivered release index for their current status. A private Library video or local test URL does not establish public judge access. No URL, commit or result is inferred from a proposed hosting plan.

## Revision3 and revision4 review fixes

This isolated revision preserves revision2 and the complete base/core package. It separates invalid and recognized-grant sign-in budgets, prevents rapid repeated activation from skipping the synchronous evidence step, makes the guided surface opaque and optional copy approval secondary, and shows an explicit simulated-timeout result with empty advice/draft plus the retained checked score. The P04 warning uses the actual recorded `contradicted_fact` versus deterministic `stale_revision` evidence; it does not change the raw receipt or the original3/4 NO_GO pilot. Reopening explains why the current sample must be reviewed again.

Revision4 preserves revision3, including its fresh private 96-second Chris video. The primary guide now derives approval and completed recap state from the current server facts rather than sticky local milestones. Reopening a final replay reveals its recap. Timeout, recovery, clearing or presentation changes that discard advice return the producer to the matching review and approval steps; preview expiry alone does not erase an active draft. Inspecting original evidence does not count as inspecting a later corrected revision. Every primary activation has a 500ms guard, and unconfirmed actions pause further replay mutations until fresh state arrives. A nonfinal replay outside the recorded 50-second snapshot offers a return to that moment while retaining corrections.

Current tests, source pin, rendered acceptance and matching video status belong in the revision4 release evidence index. The DOM transition matrix covers all eight guide stages through recovery, timeout, clear, rewind, new match, presentation, evidence open/close, preview expiry, reload and rapid activation; real-browser acceptance is a separate result. Shared personal confirmations and Microsoft terms assent are already recorded privately; only unresolved exact Touchline public-release/license scope and unknown protected-organizer fields require separate reconciliation with the parent, alongside actual public-access proof.

For a direct local judge demonstration, use recorded-only `base/app_advisory.py` and the platform-specific fresh-journal command in `base/README.md`; no SDK installation is needed. `hosted_app.py` is the separate controlled-session wrapper and does not create real access grants automatically.

Core source is frozen for journal compatibility. See [versioned recovery](design/CORE_VERSION_RECOVERY.md). The separately retained rehearsal proves exact-source restoration on local storage; it does not establish cloud backup or core-version migration.

## Revision5 capacity correction and bounded text fixes

Revision5 preserves revision4 manifest `d2d86000a797a52aca94f4d16fb7dc109376263132f6daa8812615dd7e3807e8` and its technically reviewed video. Admission now uses concurrent active sessions and the judge reservation described above, while all historical rows and journals remain. The Spanish Fan summary adds a fixed correction explanation from the same current goal/shot evidence as English. A dropped network response uses the existing uncertain-outcome guidance; dependent actions remain paused until fresh facts reconcile, without an automatic write retry.

Current source, capacity rehearsal and targeted browser results belong in the revision5 release index. The revision4 payload had147 files, one more than revision3 because it added `tests/test_login_budget_revision4.py`; the two manifest files are counted separately from payload files. Earlier media remains scoped to its recorded revision, with no new revision5 video or live inference implied. Physical-device, human listening, public-access, organizer and deployment gates remain independent of these local fixes.
