# Controlled playtest frontend handoff

These five static files are isolated additions, not a change to review3's canonical source. They require the parent-owned `hosted_app.py` HTTP boundary. There are no framework dependencies, remote scripts/fonts, analytics, or model calls.

## Files and routes

- `landing.html`: public `/` — plain product boundary, static fictional example clearly labeled as an example, paste/password-manager-friendly access form, no signup.
- `playtest.html`: authenticated `/playtest` — a single match workspace with producer verification primary and Fan/Analyst presentation depth.
- `site.css`: `/static/site.css` — phone-first reflow at 650px, tablet breakpoint at 900px, natural-height publication content, touch controls generally at least46px, reduced-motion treatment, visible focus and skip link.
- `landing.js`: `/static/landing.js` — accepts32–128 URL-safe characters, posts code only in a JSON request body, clears form on success, no storage/logging of code.
- `playtest.js`: `/static/playtest.js` — authenticates with `/api/session`, CSRF-protects mutations, sends explicit operation IDs, polls only when visible, preserves feedback drafts on errors, and clears expired preview content locally.

## Backend contract checked

Read-only check against the parent's current `hosted_app.py` found the expected `publication`, `envelope.provenance`, `recap`, `recorded_replay`, audience/language and watermark fields. Session quota UI uses actual `matches_used` and `max_matches`. The parent's feedback/logout/delete routes return JSON, which the request helper expects. Feedback posts `consent`, three integer1–5 ratings, allowed role category, optional comment up to1,000 client characters (under2,000 backend maximum), and coarse phone/tablet/desktop category.

The UI does not expose owner/admin controls, runtime paths, raw durability headers, live-inference controls, or a public feedback list. Evidence disclosure contains only fictional match records and public historical model/SDK metadata. Publication preview is rendered directly from the authenticated state; it does not claim to be an independent consuming overlay.

## Implemented experience

- Score has adjacent replay-time versus device wall-clock last-confirmed state. Offline status sits beside it; no invented verified score appears before a confirmed response.
- Stable four-step layout with a single mint-bordered next action; inspecting evidence promotes final recap as the next action.
- Correction panel explains withdrawn goal, retained shot and exact source revision; raw JSON is secondary.
- Fixed English/Spanish templates and Fan/Analyst presentation presets are labeled as such, without personalized-AI claims.
- Rewind retains corrections. New match requires explicit confirmation and says current personal journal is archived; up tothree generations. Backend remains authoritative for the limit.
- Feedback is optional with unchecked consent; it is explicitly pseudonymous/private, asks for no name/email, warns against sensitive text, and says **planned retention until18November2026**. Actual retention and operator access need the approved hosting/operations boundary.
- Explicit session-feedback deletion has a second confirmation and a truthful result/uncertainty status. No automatic POST retry.
- Errors are mapped to bounded user wording, never arbitrary raw error pages or exception traces. Stale GET responses cannot overwrite a completed action. Old producer streams are retired within the loaded app.

## Verification completed

- `node --check landing.js` and `node --check playtest.js`: pass.
- Python stdlib HTML parsing: no duplicate IDs, missing label/ARIA reference targets, or inline event handlers in either HTML file. Scripts and CSS are same-origin.
- No real browser, screen-reader, device, or user test was performed by this frontend agent. Parent owns HTTP integration and any later rendered acceptance; static tests must not be described as mobile usability proof.

## Remaining acceptance

1. Actual HTTP login/session/control/feedback/delete/logout integration, including all server-denied paths.
2. Render and keyboard-check320/390px phone,768px tablet,1280px desktop; compare document scroll width, control sizes, translated content and focus visibility.
3. Verify screen reader only announces changed preview/action status, not every poll. Last-confirmed time is deliberately outside a live region.
4. Verify no private content appears in public landing/error responses and no feedback crosses sessions.
5. Configure approved production origin, cookie/TLS/access grants, private storage/retention/export and resource limits before deployment. This handoff makes no public availability or production-readiness claim.
