# Hosted-playtest preparation

Prepared 2026-10-22. These files are isolated integration inputs, not a deployed service. No provisioning, grants, credentials, image downloads, publishing, DNS/tunnel changes or paid resources were performed. Root owns application implementation and its local tests.

## Decision

Prefer **Azure Container Apps Consumption in East US** only after a personal authorized subscription and resources are established. Run one small container for the public landing and controlled app, using the provider HTTPS hostname. A second static site adds a domain/CORS/cookie boundary and another deployment without improving this small trial. Keep one origin and one deployable application. No open signup is part of the default.

Container sizing is a proposal: **0.25 vCPU / 0.5 GiB, minReplicas=1, maxReplicas=1, Single revision**. Validate it with the real application and a modest two-user/phone load before approval. If it cannot meet the acceptance limits, resize only after a fresh cost quote and approval. Do not allow autoscaling to create multiple writers against the same journal files.

The absence of Azure CLI and `~/.azure/azureProfile.json` means no authorized Azure resource was identified. Docker CLI exists but its harmless image inventory returned no inventory and exit code 1; no Docker image/build validation occurred. See [metadata receipt](READ_ONLY_METADATA_RECEIPT.json). No token caches, environment secrets or account identifiers were read or exposed.

## App/data boundary

Public: a landing page, scope/disclosure, access form and ordinary static assets. Controlled: per-browser synthetic match, evidence and correction workflow behind revocable high-entropy grants and secure session cookies. Root's app contract has no default grant, no model route, no public admin/export path, same-origin/CSRF checks and bounded requests.

The data directory is mounted at `/data`. The backend retains one separate durable match store per tester/session, bounded generations so a fresh synthetic match archives old approved corrections rather than mutating another tester's match, and one private metadata/feedback store. Proposed caps are 100 sessions, eight cached Desk objects and three retained match generations per session, as confirmed by the implementation owner; actual tests and byte growth must establish their effects. Do not store runtime databases or grants in the image or Git.

Feedback is optional and consent-aware: bounded ratings/comment, optional role category, coarse device class, pseudonymous session linkage and timestamp. Avoid names, email, IP, detailed device fingerprint or third-party analytics in application feedback. Do not promise that the hosting platform processes no operational network metadata; confirm its log categories and retention separately. Disable request-body, cookie, Authorization and feedback-comment logging. Keep access codes out of URL query strings and referrers.

The owner uses the authenticated provider control plane to invoke `feedback_admin.py --data-dir /data list`, then private `export` or `triage`. Use JSON for free-text exports; a later spreadsheet export needs formula-safe text handling. No owner dashboard or shared admin password is exposed on the public host. Query feedback through the intended CLI/API, not a second live SQLite connection mounted from another machine. Owner access itself is restricted to explicitly approved operators and audited by the provider. No automatic alerts or external messages are configured by this preparation.

## Persistence is a release gate

Container and replica filesystems in ACA are temporary; Azure Files is its permanent mount option. An ephemeral `/data` is therefore rejected for the judge commitment. [Microsoft storage documentation](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts).

The supplied template references an existing approved Azure Files environment link. It does not create a share, retrieve a key or grant a role. Current Microsoft guidance offers managed-identity SMB mounting in preview; that avoids copying storage account keys but requires specific identity/role approval and host validation. [Microsoft Azure Files tutorial](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts-azure-files).

**A persistent share is not sufficient proof of SQLite correctness.** SQLite documents sync/locking risks on network filesystems and recommends a client/server database when storage is remote. The reviewed durable controller requests `synchronous=FULL` and a busy timeout but does not independently prove the mounted filesystem's semantics. Do not turn on WAL for an Azure Files database: SQLite's WAL documentation excludes network-filesystem use. [SQLite network guidance](https://www.sqlite.org/useovernet.html), [SQLite WAL limits](https://www.sqlite.org/wal.html).

ACA + Azure Files remains a conditional playtest design until the actual Linux image/mount passes restart, power-loss-style termination, locking, integrity, same-session serialization, two-session isolation and live export tests. Even passing those is bounded deployment evidence, not a general production guarantee. Also verify that revision replacement cannot create simultaneous old/new writers; one active revision/max-one replica is a desired state, not evidence that rollout transitions are safe. Prefer a frozen image through judging and explicitly test any required rollout.

If this gate fails, the justified alternative is **a persistence adapter using a client/server database** before publishing the app, or a separately approved single-host deployment with local persistent block storage and provider backups. Both are new scoped work and cost decisions. Do not quietly substitute ephemeral storage, mount a host PC publicly, or claim that a backup recovers every acknowledged action.

## Price and availability boundary

Current authorized spend is **USD 0**. Proposed approval amount is **USD 25 total** for the trial; there is no verified regional quote yet. A 20-day fully active 0.25/0.5 allocation is 432,000 vCPU-seconds and 864,000 GiB-seconds before shared monthly free grants. ACA's monthly grant is subscription-wide, not a promise of this app's zero bill. Storage, transactions, registry, egress and logs can add costs. Obtain a complete East US quote and remaining-grant view from the actual personal subscription. [ACA pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/).

The owner budget is an operational spending ceiling, not a hard provider stop. Azure budgets notify and their usage data/evaluation can lag; consumption continues. Configure billing alerts only after approval, monitor daily, and escalate a projected overrun before access is threatened. Do not shut down before the judge deadline solely because an alert was mistaken for a cap. If a true no-overrun requirement is mandatory, this plan is not approved until a matching provider spending control or alternative hosting commitment is verified. [Microsoft budgets](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets).

Keep free judge access through **2026-11-11 07:59 UTC**. Plan a post-deadline review at 08:00 UTC; do not schedule automatic deletion during preparation. A provider default hostname avoids custom DNS and a separate certificate workflow. ACA HTTP ingress supplies HTTPS and normally redirects HTTP; exact ingress settings still require verification after the authorized deployment. [ACA ingress](https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview).

## Templates and launch contract

- `Dockerfile`: no package installation; explicit application files and base snapshot; numeric non-root user; approved digest-pinned Python 3.12 Linux base required; mounted data directory.
- `Dockerfile.dockerignore`: Dockerfile-specific context allowlist. Inspect the built image after approval to prove no runtime data, test grants or workstation metadata entered it.
- `aca.template.json`: Consumption 0.25/0.5, one replica, provider TLS ingress, mount reference. There are no secret values or app grants. Readiness probes `/healthz` with the configured Host header and confirms metadata database reads; it does not prove journal writes, cloud locking/fsync or recovery safety.
- `render_deploy_plan.py`: renders JSON for review only; it never invokes Azure/Docker/network commands or changes cloud resources. An approved origin/image/environment/storage link must be supplied. It does not convert preparation into authorization.
- `DEPLOYMENT_COMMANDS.ps1.txt`: nonexecuting example steps with separate provisioning, storage-grant, image-publication, app-publication and owner-data boundaries.

Launch contract confirmed by root: `python -B hosted_app.py --data-dir /data --origin https://<approvedhostname> --bind 0.0.0.0 --port 8080`. Secure cookies remain the default. Reverse-proxy origin/host handling must be tested with the actual ACA headers; do not trust arbitrary incoming forwarded headers.

## Acceptance before friends or judges receive access

Run local application tests first, then the same cases against the approved deployed host without a live model. Capture sanitized request/status/state evidence. Test two separately authenticated browsers/cookie jars, not two tabs sharing one cookie jar.

1. Public user reaches landing but cannot read state, feedback, match files, grants, admin endpoints or traces. Requests to guessed static paths/traversal fail. Bad Host/Origin/CSRF, missing/expired/revoked access and tampered sessions fail safely.
2. Two testers see independent scores/revisions; A's correction, new match, rewind and logout cannot change B. Concurrent requests for one session serialize; repeated operation IDs do not double-apply. Old corrected generations remain private and cannot revive on reset.
3. Authentication/feedback/control/read limits return useful 429s and bounded retry instructions. Oversized/malformed bodies and stalled connections do not exhaust worker slots. Measure memory/CPU under the admitted session limit; do not equate a limit constant with a load test.
4. Consent is required for feedback writes. Another tester and anonymous user cannot enumerate/read it. Comments are escaped in any owner interface; JSON export preserves bounded content and triage persists. Exporting while the app serves traffic uses its supported path without copying a live database file unsafely.
5. Commit a correction and feedback; terminate the replica, restart and redeploy the identical image, then verify both stores and e010 revision. Verify a mounted-store unavailability fails closed. Restore a provider snapshot to a separate location and compare committed records without overwriting live data.
6. Verify mount permissions under UID 10001, transaction locking/fsync behavior, disk quota exhaustion and storage integrity. Do not permit two revisions to write simultaneously. Keep WAL disabled for the network share.
7. Real HTTPS host: secure/HttpOnly/SameSite cookies, no mixed content, origin binding, no cross-origin credential leaks; access code cannot appear in referrers/log URLs. Verify the public landing and protected workflow signed out and from phone/tablet/desktop.
8. Judge grant works for the promised period without payment, signup or an expiring third-party developer tunnel. No cold start/health probe can silently clear session data. No administrator credential is handed to judges.
9. Actual operational evidence confirms no inference/provider requests; all synthetic/recorded/failure labels remain true. Export and retention instructions match the UI. Recheck source/image hashes before the final access check.

## Smallest next user step

Identify a personal Azure subscription and its billing owner without providing secrets. Then approve read-only resource/price inspection there. Only after the exact image, resources, storage gate, price ceiling and data boundary are reviewable should deployment/access grants be approved. See [approval boundary](APPROVAL_BOUNDARY.md). No resource is denied or uncertain: these operations were deliberately **not attempted and remain pending approval**.
