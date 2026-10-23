# Touchline hosted playtest: journeys and design acceptance

Prepared 22 October 2026 for the isolated playtest candidate. This is a design handoff, not evidence of a deployed service, a completed usability study, or WCAG conformance. No canonical source, accounts, previews, resources or credentials were changed. No browser or desktop control was used for this research pass.

## Design decision

Use **one moment-centered match workspace**. The producer is the primary operator; the analyst and casual fan are different reading depths over the same verified state; the judge is an evaluation context. These are not four disconnected apps or four permission roles. Access-control identities remain separate from presentation preferences.

The central user question is: **“What can I still say about this moment, and what changed?”** Keep score, affected claim, freshness, source revision and the next useful action together. Do not make a chatbot, a wall of debug data or decorative football graphics the entry point.

Review3 already contains useful scaffolding: producer-purpose copy, last-confirmed score status, a correction summary panel, a broadcast preview, reconnect guidance and trace disclosures (`review3-source/desk.html`, `desk.css`). The hosted extension should preserve those concepts while reducing competing primary actions and replacing fixed-height explanation scrolling with normal responsive content. This source read is not a rendered review3 test.

## Role fit and competition boundary

The official challenge addresses studio/broadcast/streaming uses and different fan/analyst experiences. This supports one fact pipeline with multiple presentation depths. The current pitch explicitly chooses a producer checking claims before viewers see them. Judge testing may use private credentials supplied in instructions, but must remain free and unrestricted through the end of judging. Public signup is therefore unnecessary for the requested controlled playtest. Security/resource limits must not prevent complete judge evaluation. The five equal rubric areas are technological implementation, agentic design, impact, UX/presentation, and category fit. Better UX helps demonstrate existing value; hosting and polished traces do not by themselves establish better model decisions or production readiness. [Official rules §§4.1, 4.8, 6.2](https://raw.githubusercontent.com/microsoft/insidethegamehackathon/main/OFFICIAL%20RULES.md).

Roles below are validated task contexts from the challenge/pitch, not personas established by interviews. Proposed time goals are playtest hypotheses to measure, not claimed performance.

## Journey map

| Journey | Trigger and question | Shared-screen path | Moment of value | Likely failure and recovery | Proposed playtest measure |
|---|---|---|---|---|---|
| Producer: verify/correct before air | A late event change may invalidate a studio line. “Which fact changed, and which line remains usable?” | Open moment → read claim/freshness → inspect source → apply the explicit synthetic correction → see score, publication and evidence revise together | Goal is withdrawn; shot remains; e010 revision 2 is visible; old publication is replaced | Offline/uncertain commit: preserve last confirmed state, mark it stale and refresh status before repeating. Rewind must retain accepted corrections | Can identify changed goal versus retained shot without raw JSON; proposed ≤30s after arriving at the prepared moment; record observed time/errors |
| Analyst: trace the sequence | Wants to understand what supports a pattern. “Which timed events and denominator produced this statement?” | Same moment → Analyst depth → expand chronological evidence → inspect event types/revisions/window → compare current totals with window totals | Can connect e008/e010 to the shot card and see pressure/regain events as observations, without an unsupported causal conclusion | Missing/revised evidence: show unavailable/superseded state; retain the visible revision and avoid silently substituting another claim | Correctly states the 0–50s window, 2/2 on-target ratio and evidence IDs; no inference of tactical cause unless explicitly supported |
| Fan: learn quickly on phone | Wants a short understandable takeaway. “What happened and why did the score change?” | Same match → short Fan depth → concise claim → optional “What changed?” → optional language switch | Understands goal removed but on-target shot retained in two short sentences | Dense evidence or clipped translation: expand details in page flow; keep the plain summary readable without another scroll region | Can explain the correction in their own words; proposed first useful takeaway ≤10s; measure rather than assert |
| Judge: reproduce the value | Has limited time and may skip installation. “Does this work as described?” | Public purpose/limits page → supplied access code → prepared private fixture → guided first four steps → optional SDK/resilience evidence → recap | Reproduces selected card, evidence, correction and retained facts with no account purchase/model setup | Invalid/expired code or service outage: clear action and delivery fallback; never force public signup or ask for cloud credentials | Proposed first meaningful outcome ≤90s after successful access; complete essential evaluation without quota lockout |

The first-time path should be **Show moment → Replay recorded selection → Correct goal → Inspect change**. A separate optional “Test recovery” path must replay an active card before reopening, and must occur before the correction or in a clearly labeled new private fixture. The original-state receipt is correctly blocked after correction; do not undo approved facts to make a demonstration convenient.

## Current primary guidance applied

| Guidance | Supported design principle | Touchline implementation decision |
|---|---|---|
| [Fluent 2 buttons](https://fluent2.microsoft.design/components/web/react/core/button/usage) | One primary action in a layout; minor actions should not compete visually; clear action labels | One prominent next step in the guided path, stable placement and ordering. Evidence, recap, resilience and SDK history use neutral/disclosure treatment |
| [Fluent 2 wait UX](https://fluent2.microsoft.design/wait-ux) | Tell people what is happening, keep context, and tie feedback to the relevant action | “Loading your replay…” or “Applying correction…” beside the active control. No fake percentage, “AI thinking” dots or invented latency. Preserve the last confirmed card during short waits |
| [Fluent 2 message bars](https://fluent2.microsoft.design/components/web/react/core/messagebar/usage) | Put a surface-level problem near the affected content and provide a recovery action; do not overload people with assertive interruptions | Connection/freshness state lives beside the score; a failed correction has an inline refresh/recovery action. Important status is not a temporary toast far from the claim |
| [W3C status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html) | Important status changes should be exposed to assistive technology without taking focus | Announce a completed correction, failure or saved feedback once. Do not announce every polling refresh or rewrite an entire live region |
| [W3C reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html) | Preserve content and function at a 320 CSS-pixel equivalent width, normally with a single reading direction | Main claim/translation uses natural page height. Phone stacks context, claim, action, change and evidence. An actual data table may scroll horizontally, but plain paragraphs may not require nested scrolling |
| [W3C target size minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) | AA minimum is 24×24 CSS pixels or an allowed spacing/other exception | Choose a stronger product target of ≥44px for touch controls with clear separation. Do not mislabel 44px as the AA minimum |
| [W3C focus not obscured](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html) | Author-created overlays must not fully cover keyboard focus | Avoid sticky bars on short phones; if used, test keyboard navigation, zoom and safe area. Keep focused controls visible when feedback or error content opens |
| [W3C accessible authentication](https://www.w3.org/WAI/WCAG22/Understanding/accessible-authentication-minimum.html) | Support a mechanism that avoids memory/transcription burden | Access-code field permits paste and browser/password-manager assistance; no puzzle or disabled paste. Give text errors tied to the field |
| [W3C error identification](https://www.w3.org/WAI/WCAG22/Understanding/error-identification.html) | Identify detected input errors in text | “Enter the access code supplied with your invitation” or “This code cannot start a session” with a next step; feedback errors stay beside their fields without deleting the draft |
| [WAI accordion pattern](https://www.w3.org/WAI/ARIA/apg/patterns/accordion/) | Show/hide controls need keyboard operation and exposed expanded state | Native details/summary or correctly named disclosure buttons for evidence/SDK history; avoid proliferating landmarks and nested accordions |
| [W3C pause/stop/hide](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html) | Auto-updating content may require pause/stop/hide or update-frequency control unless essential | Synthetic match advancement stays user-initiated. Do not add autoplay. If a future live event list auto-advances, design a reading-pause mode while keeping an unmistakable current/stale indicator |

These sources provide current primary design/accessibility guidance; they do not certify the hosted candidate. The 44px target and task-time goals are product choices, not quotations or mandatory competition requirements.

## Inspectable football and broadcast benchmarks

These are observations from official descriptions inspected 22 October 2026, not firsthand product use, copied designs or proof of vendor usability claims.

| Benchmark | What the source actually supports | Pattern to adapt, and boundary |
|---|---|---|
| [Premier League platform launch, 1 July 2025](https://www.premierleague.com/en/news/4337361/premier-league-launches-new-fan-facing-platforms-as-part-of-digital-transformation) | Matchday Live brings scores, stats, reporting and table changes together; short vertical stories and preference-based discovery are other parts of the same platform | One match/moment anchor with short default reading and deeper content. Do not copy branding or imply access to PL feeds, Companion, broadcasts or personalisation features |
| [Opta event definitions](https://www.statsperform.com/opta-event-definitions/) | Its definitions distinguish goals, shots and shots on target; both scored goals and goalkeeper-saved attempts can be on target | Explain exactly which field changes. A withdrawn synthetic goal can remain a shot/on-target event. This is semantic context, not an Opta integration or certification |
| [EVS IPDirector](https://evs.com/products/asset-workflow-management/ipdirector) | Live-production product description emphasizes quick review/search, editorial metadata and timecoded annotations | Put claim, replay time and source revision together for fast verification. Do not imply EVS integration, broadcast playout or comparable performance |
| [AP Verify launch, 15 December 2025](https://www.ap.org/media-center/press-releases/2025/ap-introduces-ap-verify-to-strengthen-streamline-online-content-verification/) | AP describes a unified editorial verification interface with saved work and team sharing, developed and vetted by journalists | Organize around a human verification task and durable evidence history. Do not imitate unrelated tools or assert Touchline has AP's workflows, adoption or team collaboration |

The design implication is a recognizable football match context plus editorial traceability, rather than a generic AI dashboard. This is an inference from the sources above, not a tested comparison or assertion that these products use the proposed Touchline layout.

## Proposed shared wireframe

Low-fidelity specification only; it is not a screenshot or an implemented feature claim.

```text
PUBLIC LANDING
Touchline Why                                  [Tester access]
Check what changed before a line goes on air.
Synthetic football • recorded model selection • no live inference
[Enter supplied access code __________________] [Open my playtest]
What you can try: inspect → correct → verify → recap
No public signup or payment. Private optional feedback. [Privacy details]

MATCH WORKSPACE — same information order at every width
Touchline Why       Your private synthetic replay            [Session actions]
Harbor Owls 1 — Meadow Foxes 0       Replay time 0:50
Connected • Last confirmed 14:03:22 UTC    [Refresh if needed]

CLAIM / BROADCAST PREVIEW                         EVIDENCE (desktop side-by-side)
Recorded selection • source state unchanged       0:40 e008 r1 • shot • on target
“Two shots, both on target in 50 seconds.”         0:50 e010 r1 • goal • on target
[1 Show moment] [2 Replay] [3 Correct] [4 Inspect]  [Show observed sequence]
                 ONE current primary action       [Full records]

WHAT CHANGED — present near claim, not hidden in logs
Goal withdrawn • e010 revision 1 → 2
Goal yes → no | shot/on-target unchanged | score 1–0 → 0–0
Previous publication replaced. Original-state replay unavailable.

Presentation [Fan / Analyst]    Language [English / Español]
[Final recap]   [Evidence]   [Recovery tests ▾]   [SDK history ▾]
Private feedback (optional) [Give feedback]
```

Desktop can place concise source evidence next to the claim. Tablet stacks the evidence below the claim if either column would become narrow. Phone keeps the same reading order in one column, uses full-width or wrapping controls, and expands details in normal page flow. No plain-text iframe scroll, hover-only explanations, shrinking to tiny dashboard cards, horizontal carousels or full-screen navigation are required.

An observed event sequence, if the implementation exposes it, should be a simple chronological list with event time, type, team and revision. The current fixture can show pressure → regain → shots as observations. Do not label the arrow sequence a causal tactical explanation. A shot-count card remains a count, even if its presentation improves.

## Interaction and state specification

1. **Before first response:** show “Loading your replay…” with no apparently verified zero score. Establish the initial facts before enabling state-changing actions.
2. **Connected:** distinguish simulated replay time from wall-clock freshness. “Replay time 0:50” and “Last confirmed at …” answer different questions. Keep selected-card origin adjacent to the sentence.
3. **Action pending:** disable duplicate submission of that action; keep the current context and visible progress text. Do not replace an entire page with a spinner or announce fabricated progress.
4. **Action confirmed:** show the actual resulting revision, score and publication together. Announce the meaningful result once. Keep keyboard focus at the triggering control unless the user requested navigation.
5. **Response uncertain:** say it is unconfirmed and refresh current state before repeating. Do not claim an operation failed merely because the client timed out, or auto-create another operation ID as an invisible retry.
6. **Offline/expired:** retain useful last-confirmed facts with an explicit stale/offline marker; expire selected insight as designed. Place the recovery action at the score/card, not below a long evidence panel.
7. **Correction:** label the concrete synthetic change before it is committed. Afterward retain an event-level diff and history. Do not “undo” an approved correction by rebuilding the original fixture. A later correction-of-correction would need a new audited revision, and is not an implemented claim here.
8. **Rewind:** changes presentation time while retaining approved corrections. The wording must not suggest it creates the original uncorrected fixture.
9. **New personal match:** disclose whether the prior journal is archived or discarded, confirm the effect on the current tester only, and offer Cancel. If generations are archived, say so only after tests establish that behavior. Feedback remains a separate private record.
10. **Presentation switch:** reversible immediately; fact IDs and revisions remain consistent. Short fan copy and richer analyst detail are named presets, not per-person learning. English companion and Spanish text reflow fully.
11. **Feedback:** optional and not blocking the workflow; ratings/comment retain a draft on validation/network error. Explicit consent is unchecked. State purpose, owner-only visibility, configured retention, and “do not include personal or sensitive information.” Say pseudonymous, not anonymous, if the session can be linked. Show a confirmation/receipt only after persistence succeeds.
12. **Owner triage:** feedback exports and administrative actions are separate from tester UI. No public feedback feed, tester-to-tester visibility or admin/debug controls are part of the landing/workspace.

## Acceptance matrix

All rows below are **required checks, not completed test results**. Root's implementation/test owner should record pass/fail, environment, evidence and remaining limits. T = technical implementation, A = agentic design, I = impact, U = UX/presentation, C = category fit. These are mappings to the supplied/verified rubric, not promises of points.

| ID / priority | Journey | Observable acceptance | Method / evidence needed | Mapping |
|---|---|---|---|---|
| D01 P0 | All | Two tester sessions can independently correct, rewind and start new fixtures; neither reads or changes the other's state or feedback | Two independent cookie jars; API and persistence tests, including process restart | T, C |
| D02 P0 | Producer | Correction shows e010 revision 2, goal false, shot/on-target retained, 1–0→0–0 and old publication withdrawn as one coherent result | Backend assertions plus rendered capture after consumer/desk agree | T, I, U |
| D03 P0 | Producer/Judge | Rewind, reopen and process restart retain committed correction; an old selected card cannot revive | Existing window left open during real restart; capture stale/recovered state, not only unit tests | T, C, U |
| D04 P0 | Judge | Supplied credentials work without signup/payment/model setup; essential evaluation remains available through Nov11 07:59UTC | Signed-out/private-browser hosted check after approved deployment; quota/capacity rehearsal and downloadable fallback | T, U; §4.8 |
| D05 P0 | All | Hosted UI never exposes raw credentials, feedback of others, administrative export, live-inference controls or private paths | Route/auth tests and public-surface inspection | T, C |
| D06 P1 | Producer/Judge | Purpose, synthetic/recorded scope, current score/freshness and primary next action are understandable at entry | First-impression task with a friend; ask what it does before explaining; capture actual answers | I, U |
| D07 P1 | Producer | Claim opens its timed current evidence in one action; changed fields and unchanged facts are readable without raw JSON | Keyboard and pointer task; screenshot source diff and claim together | I, U, C |
| D08 P1 | Analyst | Chronological evidence retains source event times/revisions; window counts are distinguishable from totals and denominators visible | Task questions plus exact fact/evidence assertions across presets | T, I, U |
| D09 P1 | Fan | Short claim/change summary is readable at 320, 390 and 430 CSSpx; translation/evidence are reachable with one page scroll and no clipped paragraph | Rendered portrait/landscape captures; 320-equivalent reflow and 400% zoom test | U; WCAG reflow |
| D10 P1 | All | Tablet 768/820px and desktop 1280/1440px preserve order/context; disclosure layout does not create tiny columns | Rendered captures at representative sizes, plus content zoom | U |
| D11 P1 | All | Tab/Shift+Tab reach controls logically; Enter/Space activate disclosures; focus stays visible and survives polling | Manual keyboard walkthrough; focus screenshot including feedback/error states | U; WCAG focus/keyboard |
| D12 P1 | All | Screen reader hears correction/error/saved feedback once; routine polling does not continuously announce unchanged content | Actual screen-reader test; log meaningful announcement sequence | U; WCAG status |
| D13 P1 | All | Interactive text/background contrast meets 4.5:1 where applicable; controls/icons and focus are distinguishable; status never relies on color alone | Computed-color checks and rendered inspection in all states | U |
| D14 P1 | Fan/All | Primary touch controls ≥44px product target, sufficiently separated; no hover-only information; touch can expand evidence and dismiss feedback | DOM measurements plus phone touch walkthrough | U; stronger than minimum target-size criterion |
| D15 P1 | Producer | Network outage beside score states last-confirmed/stale facts; chosen insight expires; retry does not fabricate success or duplicate a correction | Real owned-service interruption/recovery plus idempotency test | T, U, C |
| D16 P1 | All | New-match prompt accurately states only own-session effect; Cancel preserves current facts; prior-history behavior matches wording | Two-user test plus journal generation inspection | T, U, C |
| D17 P1 | Tester | Feedback is optional; unchecked consent cannot submit; invalid input is identified; stored result is owner-only; duplicate/network error behavior preserves draft truthfully | API privacy tests, consent tests, rendered form checks and operator export | T, U, C |
| D18 P1 | Judge | First four steps reproduce value without technical documentation detours; original receipt remains blocked after correction with a plain reason | Cold evaluator task and observed time/errors; no invented user-test outcomes | I, U |
| D19 P1 | Judge | The SDK panel says historical and one selected ID; current facts/wording are deterministic; no false live/model-benefit claim | Copy review versus receipt and implementation; current recording correspondence | T, A, U |
| D20 P2 | Fan/Analyst | Presentation/language toggles preserve score, facts, evidence revisions and current source scope, while meaningfully changing reading depth | Fact equality checks and actual comprehension prompts | T, U; §4.1 |
| D21 P2 | All | Access-code paste works; errors are descriptive; no memory puzzle; session expiry offers clear return without pretending unsaved feedback is stored | Authentication form keyboard/paste tests, expiry test | U |
| D22 P2 | All | No autoplay or auto-advance distracts reading; future live updates have a reviewed pause/frequency strategy | Source inspection and rendered observation; evaluate any essential-update exception | U |

Unit/API tests can establish many state and access properties. They cannot by themselves establish usability, screen-reader announcements, phone readability, hosted reliability or production readiness. Mark checks untested where the relevant environment/person/device was not used.

## Small, useful friend playtest

After deployment/access approval, give each friend a private session and a short task, not a feature tour. Do not send invitations in this task.

1. Without explaining the UI, ask what the product does and whether the match/model is live.
2. Ask them to show the recorded moment, then correct the goal and explain what changed and what remains true.
3. Ask where the supporting event is, and whether rewind should remove the correction.
4. On their normal phone, ask for a short English/Spanish or Fan/Analyst view and a final recap.
5. Invite optional private feedback: clarity, usefulness, trust, the most confusing moment and one thing they expected to do. Avoid names, email, employer, precise location, screen recording or background data collection.

Record observed completion, wrong turns and their own explanation separately from ratings. A few football/Microsoft friends can identify friction; they do not establish broadcaster adoption, representative fan demand or production-grade reliability. Ask for a producer/analyst domain review later if available.

## Immediate implementation order

1. Preserve isolated session/fact semantics and explicit state/freshness; they are foundations for a trustworthy design.
2. Build the single-column claim/change/next-action flow; add a two-column evidence enhancement only where space permits.
3. Put human-readable evidence at the decision, secondary raw/SDK/resilience tools behind disclosures.
4. Implement and verify consent-aware private feedback and exact New match/rewind wording.
5. Run the rendered device, keyboard and assistive-technology checks alongside backend isolation tests before claiming the hosted candidate works on phones or is accessible.
6. Use actual playtest evidence to refine copy/hierarchy. Do not add cloud services, four apps or a chat box merely to appear more advanced.
