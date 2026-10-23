# Touchline Why

A correction-aware evidence desk for football studio producers. When synthetic match data changes, inspect the affected claim and see which facts remain usable.

## See the demo in 60 seconds

Use Python 3.12+ and a browser. The recorded demo needs no SDK, Node.js, credentials, GPU or paid model service. Extract the source or judge ZIP, then open PowerShell in its folder:

```powershell
python -B verify_package.py
$demoDb = Join-Path '..\touchline-runtime' ('demo-' + [guid]::NewGuid().ToString('N') + '.sqlite3')
python -B app_advisory.py --port 8770 --db-path $demoDb
```

Open `http://127.0.0.1:8770`. A fresh journal starts at 0s with Harbor Owls 0, Meadow Foxes 0. `app_advisory.py` starts in recorded-only mode, with live inference unavailable. Select Casual and English, then choose **Show 50s pattern**. Review a sample producer draft and its captured clause advice. Explicit approval creates a draft, without transmitting it or changing the match facts. Apply the late correction and inspect which copy is now obsolete. `ADVISORY_REVIEW.md` describes the approval boundary and recorded evaluation failure.

On Linux or macOS, open a terminal in this same extracted `base/` folder. This one-line launch verifies the package, prints a fresh scratch journal path outside the source, and starts the same recorded entry point with Python 3.12+:

```sh
python3 -B -c 'import pathlib,subprocess,sys,tempfile; subprocess.run([sys.executable,"-B","verify_package.py"],check=True); db=pathlib.Path(tempfile.mkdtemp(prefix="touchline-demo-"))/"match.sqlite3"; print("Journal:",db,flush=True); subprocess.run([sys.executable,"-B","app_advisory.py","--port","8770","--db-path",str(db)],check=True)'
```

Both launch routes need no SDK installation and create a new journal outside the source folder. Preserve the printed or PowerShell journal path and previous journals, including corrected ones. Stop with Ctrl+C. If 8770 is occupied, use another unprivileged port and change the URL to match. A fresh journal is a separate match; it does not import accepted corrections from an older journal.

## What the demo shows

- A pattern selected from exact rolling statistics, with source event IDs.
- Short fan summaries and analyst views with window/proxy qualifications in English and Spanish. Both keep the same facts; evidence IDs stay in the producer layer rather than fan copy.
- A late correction that changes the score and retracts the previous overlay.
- An explicit timeout injection that keeps verified facts available.
- Saved command replay that restores facts and revisions without renewing an old selected insight.
- A final recap that keeps corrected events and historical selections distinct.
- Recorded AI advice about individual clauses, with evidence and explicit producer approval. Match/view changes clear stale draft approval.

Harbor Owls, Meadow Foxes, their players and all match events are fictional. Observed shot and activity counts are not causal tactical intent or calibrated xG.

## Exact replay and correction rules

Recorded replay requires the original 50-second event snapshot, with no later approved correction changing its digest. After a correction, replay stays blocked even when its shot-count claim remains supported historically. Rewind keeps approved corrections and their revisions; it cannot restore the original goal. Start a separate fresh journal with the command above when another uncorrected fixture is needed.

The primary manual sequence and recovery checks are in `TESTING_INSTRUCTIONS.md`. The single current recording proposal is `REVISED_DEMO_PLAN.md`; narration and VTT files are drafts, not evidence of a completed capture.

## Model provenance

Microsoft Agent Framework core 1.22.0 and its Ollama provider 1.0.0b261015 were used for four historical local model attempts: two accepted candidate selections and two client timeouts. The accepted outputs select the same moment. The model chooses a candidate ID; deterministic code owns arithmetic, evidence validation and final wording.

The default judge build is recorded-only. It verifies the original accepted receipt bytes before replaying their selections against identical facts. Its labels identify recorded output, deterministic fallback and injected failure. No model weights, credentials, GPU, paid service or live inference are needed to use this demo. See `MODEL_PROVENANCE.json` and `evidence/m2-model-measurements.json` for the earlier selection experiment.

A separate four-call local claim-review trial used the same Microsoft SDK and cached model. It passed three of four strict frozen cases; all four made the expected clause/evidence choices, but one missed the correction-specific reason. That original NO_GO remains unchanged. Its actual receipts and evaluation are under `evidence/claim-review/`. Current review controls replay recorded advice and never call the model. Producer drafts are transient and are not broadcast publications.

`app_advisory.py` is the recorded-only entry point used above. The older `app_m3.py` and `app_final.py` preserve the previous desk and optional selection experiment. Their presence does not authorize more inference. No live review opt-in exists in the advisory entry point.

## Verification status

The reviewed predecessor, identified by source manifest `b7c3d6d893e702c675f40a17f230b10d3af313b81a6e9c0cd5e9afa86a467b8e`, has supplied Windows evidence for 272 base checks, 45 hosted checks and 17 hosted DOM checks: 334 total. Claude independently reproduced 300 of those 334 checks and 37 HTTP steps on Linux; 34 Windows-wheel-dependent checks were not reproduced there. These are predecessor results. Current review-fix counts and final manifest pins are recorded in the delivered verification/REVIEW_RESULT.json and RELEASE_EVIDENCE_INDEX.json; predecessor counts are not current results. The runner writes a new `judge-results.json` outside the immutable source folder. See `TESTING_INSTRUCTIONS.md` for the exact scope; tests do not establish current public links or a fresh video.

The full offline suite uses 19 hash-locked Windows wheels and Node.js. It is optional for trying the recorded demo. `app_final.py` is an optional local-inference entry point and is unnecessary for the judge quick start; its inference route remains disabled by default and has mock coverage only.

## Limits

`app_advisory.py` is the current recorded entry point. `app_m2.py` supplies shared controller and HTTP behavior; its historical standalone UI is not part of this package.

This is a single-owner synthetic prototype. The saved journal is bounded to 500 commands, with no automatic migration or compaction. Changing its core source or fixture can cause an old database to fail verification. Preserve the old database. A fresh runtime path starts an independent match and does not transfer its corrections. Versioned recovery must use the separately documented and verified release procedure; do not treat a fresh empty journal as recovery.

The timeout control is a declared injection. Client timeout and transport closure do not prove that a real server or GPU stopped inference. Actual server cancellation remains unverified. There is no Azure, Foundry, live ingestion or multi-agent implementation claim.

## Licenses and data

Application licensing is documented separately in `LICENSE_STATUS.md`. Do not infer an open-source grant from a public repository or from the Microsoft framework's MIT license. Third-party notices and model terms remain under their own licenses. The dependency set includes MIT, BSD, Apache, MPL and historical Python license terms. `CORRESPONDING_SOURCE.md` identifies the pinned certifi source archive. Model weights and video encoder binaries are excluded.
