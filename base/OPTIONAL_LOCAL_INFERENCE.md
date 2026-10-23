# Optional local inference

The normal `app_m3.py` judge demo stays recorded-only. `app_final.py` adds a separate optional local selection route. Its default mode imports no model SDK, starts no model request and shows the same recorded demo. The historical budget is exhausted: four attempts, two accepted outputs and two client timeouts.

Use the judge ZIP's verified offline setup and its runtime interpreter. Dependencies, local wheels and hashes are included there. This guide does not install Ollama, download a model or grant permission to use shared compute. Before enabling inference, obtain the machine owner's consent for a new local resource window and confirm an already installed supported model is available at the literal loopback endpoint `http://127.0.0.1:11434`. The application never probes model inventory or contacts a cloud provider.

From the extracted judge directory, the default starts with zero provider calls:

```powershell
$project = (Get-Location).Path
$runtime = Join-Path (Split-Path $project -Parent) ((Split-Path $project -Leaf) + '-runtime')
$runtimePython = Join-Path $runtime '.venv\Scripts\python.exe'
$database = Join-Path $runtime 'optional-local.sqlite3'
& $runtimePython -B .\app_final.py --port 8770 --db-path $database
```

For an explicitly approved 15-minute resource window, compute a fresh cutoff and opt in:

```powershell
$cutoffMs = [DateTimeOffset]::UtcNow.AddMinutes(15).ToUnixTimeMilliseconds()
& $runtimePython -B .\app_final.py --port 8770 --db-path $database --enable-model --model-until-ms $cutoffMs --model 'gemma4:12b'
```

`qwen2.5:14b` is the other supported existing tag. No weights are bundled. The cutoff must be in the future and at most 45 minutes away. Choose an unused port if 8770 is occupied, then open its loopback URL.

Startup still makes zero provider calls. In the browser, choose **Show 50s pattern**, then **Run local model once**. Each press requests one supplied-candidate selection through the existing Agent Framework adapter. Facts, arithmetic and wording remain deterministic. The app never retries a request automatically. The **Replay accepted model output** button continues to replay historical evidence without calling a model.

Before a request can consume an attempt or allocate a selection token, the producer and adapter use the same pure catalog preflight. Candidate-ID selection needs at least two valid current candidates. Schema, duplicate, evidence and UTF-8 size limits are checked there as well. Ineligible state exposes its exact reason, keeps the worker idle and preserves the allowance; a disabled button is not evidence of a model failure.

The optional process permits at most four attempts and 50 seconds of cumulative client wall time, with a 12-second client timeout per call and one request in flight. Match reset and durable recovery do not restore the call budget. These counters are per process, so restarting requires a fresh resource decision and must not be used to bypass an exhausted window. The adapter's cleanup failure disables further attempts. Client cleanup and mocked cancellation tests do not prove server-side model cancellation.

New inference traces appear separately from recorded traces. Results arriving after a correction, reset, view change or recovery are rejected. Trace details from a later event watermark or another replay epoch are withheld. Durable journal verification runs before dispatch and before publishing a model result.

This new entry point has been checked with controlled mocks only. Finalization made zero new real model calls. Historical SDK receipts remain the evidence of actual prior inference. A successful mock test does not establish fresh model quality, runtime latency or server cancellation.

Run the added regressions without contacting a provider:

```powershell
& $runtimePython -B -m unittest test_final_runtime
& $runtimePython -B -m unittest test_final_live
node --test test_m3_poll.cjs test_final_ui.cjs
```

`test_final_live.py` checks startup isolation, explicit call deduplication, budgets, timeout fallback, stale-result races, journal failure, trace withholding and live versus recorded labels. `test_final_runtime.py` covers the preserved recorded demo, receipt verification, English companions, finish IDs and incomplete request timeout. The existing `mock_lifecycle_test.py` checks the adapter's mocked client cleanup and shared preflight boundaries separately, including an injected valid SDK dispatch. Catalog rejection makes no dispatch and consumes no attempt. No test in these groups calls a real provider.
