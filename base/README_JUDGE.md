# Touchline Why: judge build

Use the **See the demo in 60 seconds** panel in `README.md` as the single launch route. It verifies the extracted files and starts recorded-only `app_advisory.py` with a fresh journal outside the source folder. Python 3.12+ and a browser are enough for that demo. The README provides Windows and one-line Linux/macOS launches. No SDK install, account, credential, GPU or paid model service is needed. Keep existing corrected journals.

`TESTING_INSTRUCTIONS.md` gives the exact expected observations and separate full-verification procedure. `REVISED_DEMO_PLAN.md` is the one primary 114-second recording proposal. Its narration and subtitles are drafts; a current capture has not been made.

## Package and verification scope

`PACKAGE_MANIFEST.json` distinguishes the wheel-free source bundle from the judge bundle with 19 hash-locked wheels. Both retain the original third-party notices. Python, Node.js, model weights and video encoder binaries are not bundled.

For the reviewed predecessor manifest `b7c3d6d893e702c675f40a17f230b10d3af313b81a6e9c0cd5e9afa86a467b8e`, supplied Windows results total 334 checks: 272 base, 45 hosted and 17 hosted DOM. Claude independently reproduced 300/334 and 37 HTTP steps on Linux; 34 Windows-wheel-dependent checks were not reproduced. Current review-fix verification is recorded in the delivered verification/REVIEW_RESULT.json and RELEASE_EVIDENCE_INDEX.json. The final release evidence index must identify the corrected manifests, exact run environment/results, Git commit, public repository, working judge/demo URL and fresh video. Missing or historical artifacts do not become current release evidence.

For full checks, `judge_setup.ps1` requires an installed, supported CPython 3.12.2 interpreter on Windows AMD64, installs only included wheels with hashes and no index access, and runs `pip check`. `judge_verify.py` uses `judge_test_plan.json`, separates SDK mocks into their own processes and verifies source membership before and after. The Node tests use DOM stubs rather than a rendered browser. Results and mutable databases stay outside the source folder. A watchdog timeout is a failed run.

## Evidence limits

The default uses preserved historical model receipts and deterministic fallback. It makes no live provider request. Clause review replays captured advice; producer approval creates only a draft. The original claim-review pilot remains NO_GO, three of four strict cases. A deterministic correction explanation is labeled separately from the captured model reason. Historical receipts retain their exact bytes and hashes. Mocks do not establish fresh model execution or real server/GPU cancellation.

Final recap now uses one durable finish command; its UI result does not itself prove crash atomicity. In-process reopen, actual process restart, DOM-stub tests and rendered visual checks are distinct evidence. Follow the explicit recovery checks in `TESTING_INSTRUCTIONS.md`.

All clubs, players and events are fictional. There is no real footage, live feed, Azure, Foundry or multi-agent implementation claim. Application rights and optional licensing remain governed by `LICENSE_STATUS.md`; dependency and model terms are separate. Hashes detect drift against a manifest and are not a digital signature.

The package excludes private account/registration/support records, credentials, coordination history, environments, runtime databases and unrelated desktop content. Local testing does not establish public access, eligibility, permission to publish, submission or a result.
