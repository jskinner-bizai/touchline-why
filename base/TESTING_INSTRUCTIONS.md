# Judge testing instructions

Start with the **See the demo in 60 seconds** panel in `README.md`. Use recorded-only `app_advisory.py`, which accepts `--port` and required `--db-path`; no mode flag or SDK setup is needed. The quick-start command gives each original fixture a new journal name outside the source folder. It never deletes an existing corrected journal. Stop the server with Ctrl+C before copying its database.

## Runtime and evidence scope

| Snapshot | Actual or supplied evidence | Limit |
|---|---|---|
| Reviewed predecessor, manifest `b7c3d6d893e702c675f40a17f230b10d3af313b81a6e9c0cd5e9afa86a467b8e` | Supplied Windows results: 272 base + 45 hosted + 17 hosted DOM = 334 checks. | Supplied evidence for that exact predecessor, not the current review-fix source. |
| Independent Claude second review of that predecessor | Actually reproduced 300/334 checks and 37 HTTP steps on Linux. | The 34 Windows-wheel-dependent checks were not reproduced there. DOM-stub checks and HTTP checks are not full visual or accessibility evidence. |
| Current review-fix candidate | See delivered verification/REVIEW_RESULT.json and RELEASE_EVIDENCE_INDEX.json for exact counts, final manifest and environment. | Do not carry 334, 300 or an older baseline count forward as a result for these changed files. |

The recorded demo uses Python 3.12+, the standard library and a browser. Both Windows and a one-line Linux/macOS fresh-scratch launch appear in `README.md`. The full offline SDK setup requires exact CPython 3.12.2 on Windows AMD64 and contains platform-specific wheels. Node.js 24.14.0 was used for the full packaged checks. These prerequisites are not bundled. A reviewer trying the stdlib demo on another Python 3.12 platform should report the actual environment and outcome rather than infer full platform support.

## Mode, journals and replay prerequisites

`app_advisory.py` is the recommended entry point and always starts recorded-only. It includes captured clause advice and transient producer draft approval without calling a provider. The older `app_m3.py` is historical support code, not the recommended launch route. `app_final.py` is unnecessary here; its optional local route defaults off and has mock coverage only. Do not enable it for this demonstration.

A new journal begins at 0s and 0 to 0. Set Casual and English explicitly, then Show 50s pattern. The original 50s snapshot is 1 to 0 and supports the preserved recorded selection. Replay is available only when the current snapshot digest exactly matches that receipt. The selected card expires after its bounded lifetime; replay it again while facts still match if an active card is needed for a recovery check.

An approved correction changes e010 to revision 2 with `goal:false` and retains `on_target:true`. The score becomes 0 to 0 at 50s. Rewind/reset, implicit rewind and reopen must keep that approved correction. They cannot restore the original-state receipt. The recorded two-shot claim can remain supported historically even though replay against the changed snapshot is blocked.

Preserve journals if source/fixture verification fails. A different database path creates a separate match and does not restore accepted corrections. Use only the documented, tested versioned recovery procedure supplied with the final release when transferring a prior journal; a fresh empty database is not recovery. Never delete an accepted correction just to make a recorded receipt replayable.

## Manual demonstration sequence

This path is a set of expected observations to verify, not a new execution receipt. The recording timing and narration live only in `REVISED_DEMO_PLAN.md`.

| Step | Action | Expected observation |
|---|---|---|
| 1 | Use the README fresh-journal launch; set Casual and English. | At 0s, Harbor Owls 0 / Meadow Foxes 0, with a recorded/no-live-inference label. |
| 2 | Show 50s pattern, then replay the accepted model output. | Score 1 to 0 and a visibly recorded two-shot / two-on-target card. No provider request. |
| 3 | Reopen durable replay while that selected card is active. | Same facts in a new stream; deterministic fallback rather than a revived selected card. If the card expired before the click, repeat from a visible active selection. |
| 4 | Replay again while original facts still match, then apply the late correction. | Score 0 to 0; previous publication replaced; e010 revision 2 has goal false and on-target true. |
| 5 | Inspect evidence, then inspect one Microsoft SDK recording. | Current correction/evidence is distinct from a historical accepted Agent selection. Its original-state replay is blocked, while shot counts can remain historically valid. |
| 6 | Switch casual/analyst presentation, then Casual Spanish with English companion. Return to English. | Bounded presentation text changes; facts and producer evidence remain consistent. Companion text is readable and complete. |
| 7 | Inject timeout after the correction. | The explicit injected/no-model-call label appears; corrected facts remain. Fallback already exists, so this does not prove another selected-card removal or server cancellation. |
| 8 | Final recap, Show 50s pattern, then Final recap again. | Scores 0 to 1 at 130s, corrected 0 to 0 at 50s, then 0 to 1 again. The correction revision remains approved. |
| 9 | Rewind replay (keep corrections), show 50s and finish again if testing explicit reset. | The same correction persists; old recorded replay remains unavailable. |
| 10 | Read the concise final English recap. | Both pass totals 2/3; one withdrawn goal; two accepted historical receipts represent one distinct selection moment. |

Wait for the desk and consuming overlay to show matching stream/publication state before claiming a completed transition. A frame between polls is not proof of coherence. The single recording plan uses one readable historical receipt and avoids reading hashes aloud.

## Recovery and finish checks

Reopen durable replay closes and reopens the local journal within the running process. Actual process stop/start is a separate check. Leave the desk open, stop only the owned test server, wait for stale output to clear, then restart the same app/port/database. Verify that both parent facts and embedded fallback recover coherently without reviving an old insight. Run once from an active selected card and once after an approved correction. The previous CX review found consumer quarantine after real restart; a new result is required before claiming automatic repair.

A standalone consumer intentionally rejects an unrelated changed stream. If it remains quarantined, reload that consumer or the whole page and record the workaround. Do not silently treat a blank/quarantined preview as successful unattended recovery. A new UI recovery control, if included, needs its own actual check.

Final recap now routes one `finish` action through a single durable command keyed by its operation ID. It is not a series of child `next` commits. Separate tests must verify commit/retry/crash boundaries; a successful button click alone proves none of those guarantees. The manual finish/rewind/finish path uses a fresh action each time.

## Run the full offline checks

Return to a fresh extraction or use the unchanged source folder. The setup script derives a sibling runtime folder from the extraction folder name:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$project = (Get-Location).Path
$runtime = Join-Path (Split-Path $project -Parent) ((Split-Path $project -Leaf) + '-runtime')
python -B verify_package.py
powershell -NoProfile -File judge_setup.ps1 -Python python
$runtimePython = Join-Path $runtime '.venv\Scripts\python.exe'
& $runtimePython -B judge_verify.py --output-dir (Join-Path $runtime 'verification')
```

The setup verifies the supported interpreter and source manifest, creates an isolated environment outside the source folder, and installs from the 19 included wheels with no index access and required hashes. `pip check` must pass.

The packaged `judge_test_plan.json` is the authority for test membership. The verifier records its exact test totals, exit codes and source-membership checks in `judge-results.json`, with separate logs. Use the exact primary modules, separate SDK modules and Node files listed in that current plan; do not substitute an older module count. An SDK import smoke check verifies dependency availability without starting inference. The mocks do not contact a provider or enable the optional route. A watchdog exit is a failed verification, not proof of successful timeout recovery.

For focused checks in the verified SDK environment:

```powershell
& $runtimePython -B -m unittest test_m3_desk test_m3_durable test_m3_independent test_m3_recap test_m3_spanish test_final_runtime test_advisory_review test_advisory_app test_pilot_budget
& $runtimePython -B -m unittest mock_lifecycle_test
& $runtimePython -B -m unittest test_final_live
& $runtimePython -B -m unittest test_claim_review_agent
node --test --test-reporter=tap test_m3_poll.cjs
node --test --test-reporter=tap test_final_ui.cjs
node --test --test-reporter=tap test_advisory_ui.cjs
```

Run each SDK mock module in its own process, as shown. Combining an SDK mock with the primary suite imports the optional adapter into a process that checks no provider was imported. Use the fixed packaged plan rather than broad file discovery, which can pick up historical test files outside the final capsule.

`test_final_runtime` covers recorded-mode receipts, English companions, recap event IDs and incomplete-request timeout handling. `test_final_live` uses injected transports to check startup isolation, explicit request deduplication, budgets, stale-result rejection, journal checks, timeout fallback and separate live/recorded labels. `test_final_ui.cjs` checks the corresponding control logic with DOM stubs in Node. It is not a rendered browser test. Despite its module name, `test_final_live` makes no real model call.

## What verification establishes

The fixed plan checks event-time withholding, exact arithmetic, evidence revisions, duplicate operations, correction/retraction, stale output rejection, language/view fact consistency, immutable receipts and recovery boundaries. Node DOM-stub results are not rendered-browser or accessibility proof. Mock SDK lifecycle tests are not real inference or server cancellation.

Keep fresh result files, environments and current package hashes with each test run. In-memory or loopback timings are not audience-facing latency. Tests and local screenshots establish no public delivery link, production reliability, measured audience outcome, legal eligibility, public-sharing permission, submission or result. All supplied match identities and events are fictional.

## Release evidence still required

Use the final release evidence index to bind this source to its exact Git commit, corrected manifests and run logs, functioning deployed judge/demo URL, public repository and fresh functioning-software video. At this documentation pass those public URLs and a new video are absent; the older M3 footage is historical and does not show this candidate. A recording script, a localhost URL, a test pass or an unfilled template does not satisfy those release items.
