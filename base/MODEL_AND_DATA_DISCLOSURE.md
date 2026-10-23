# Model and data disclosure

All match events, clubs and players are synthetic. No match footage, real club assets, copyrighted music or personal data are required by the demo.

The historical experiment used Microsoft Agent Framework core 1.22.0, `agent-framework-ollama` 1.0.0b261015 and the Ollama Python client 0.5.3. One SDK Agent selected an ID from engine-supplied candidates using the existing local `gemma4:12b` tag. It did not generate free-form broadcast text. Deterministic code expanded the selected ID, validated its evidence, computed statistics and rendered the final wording.

The completed measurement record contains four actual local model attempts: two client timeouts and two accepted selections. Those accepted receipts select the same candidate and moment; they are not two independent successful events. Their original bytes are hash-verified. Total recorded wall time across the four attempts was 38,369.290 milliseconds, including timeouts and cold loading. This is not a latency distribution for successful inference.

The default `app_advisory.py` judge demo is recorded-only. It preserves the earlier desk behavior and adds captured clause-review advice. It imports no model SDK and exposes no live-review opt-in. After a correction, the original selection cannot be applied to the changed snapshot. Recorded selection is transient: saved-command recovery restores facts and revisions, then starts a new publication stream with deterministic fallback.

A separate claim-review experiment ran four actual sequential SDK calls from 12:06:01 to 12:06:57 UTC on October 22, 2026. It used the same cached local model and Microsoft SDK versions. It passed three of four strict frozen cases. All four kept/removed the expected clauses and used the expected evidence. One response called an obsolete corrected score a generic contradiction rather than a stale revision. The original NO_GO result and raw reason remain unchanged. Whole-process times were 22.125, 10.297, 7.359 and 15.250 seconds; this small selected set is not a general latency or accuracy benchmark. No retries, timeouts, model downloads or paid cloud calls occurred in that trial.

Current copy review replays those captured responses and labels them recorded. Explicit producer approval creates only a transient copy draft, not an on-air publication. A deterministic explanation can identify a withdrawn goal from current ledger history, separately from the preserved model reason. Review/approval recheck source, event-time, revisions and view context. Current runtime makes zero new model calls. Evaluation files are not runtime approval labels.

Separate `app_final.py` adds a local selection route that is disabled by default. Its default startup imports no model SDK and makes no provider request. The optional route was checked with controlled mocks only; finalization made zero new real provider calls. Those checks establish no fresh model-quality, latency or server-cancellation result. `OPTIONAL_LOCAL_INFERENCE.md` documents the exact explicit opt-in procedure, existing-model prerequisites and bounded resource window. This route is not part of the recorded quick start or the video script.

The current timeout control is an explicit injected failure. Separate mocked lifecycle tests demonstrate that a client can close while a detached backend continues. Actual deployed server/GPU cancellation after the historical timeouts was not verified.

The fixed `judge_test_plan.json` separates primary recorded-runtime checks from the SDK mock modules. `test_final_live` uses injected transports rather than a real provider, despite its name. Historical SDK receipts remain the evidence of actual prior inference.

`MODEL_PROVENANCE.json` preserves the model's server-reported custom digest and runtime details. That tag differs from the public catalog manifest. It must not be described as a freshly computed weight-file hash or as byte-identical to the public tag. Model weights are not distributed, and the recorded-only demo requires no model installation.

Each recorded workflow uses one SDK Agent. The prototype does not demonstrate multiple specialist model agents, Azure deployment or Foundry use. The multilingual views use fixed reviewed templates with the same fact and evidence IDs. Recorded clause advice is English and is not silently translated into other views. No native-speaker certification is claimed.

The intended operator benefit is inspectable explanations and predictable correction handling. That is a proposed use case, not a measured result from a broadcaster or a claim of real-match validation.
