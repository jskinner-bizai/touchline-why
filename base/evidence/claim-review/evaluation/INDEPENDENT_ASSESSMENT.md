# Independent pilot assessment

**NO_GO under the unchanged frozen gate.** P01-P03 passed; P04 correctly retained the supported shot clause and withdrew the stale goal, but returned `contradicted_fact` instead of the required `stale_revision`. Full rubric: **3/4**. Clause actions and current evidence joins: **4/4**. Do not relabel the failed case or claim a 4/4 result.

Four actual local Microsoft Agent Framework calls completed normally, each with one request, server `done`, and closed client/transport/response. Subprocess lifecycles were 22.125, 10.297, 7.359 and 15.250 seconds; all were below 25 seconds. Outputs totaled 178 tokens, each below 192. The 100-second conservative reservation and all four attempt slots are exhausted. Two health GETs were used. There is no remaining retry or call allowance.

Raw request/response bytes and hashes matched the receipts. Actual case data matched the frozen inputs, without gold labels in the payload. The output schema permitted all reason classes rather than revealing case-specific answers. Reported outputs matched raw response contents.

The safe baseline withheld noncanonical drafts for manual review. The pilot added supported clause retention and useful case-specific diagnosis in P01-P03; P04 retained the right clause but missed the correction-specific explanation. This demonstrates bounded semantic work beyond exact matching. It does not establish measured producer benefit, broader model accuracy, or improved factual safety over an unsafe strawman. These are four hand-picked cases in one trial.

The existing daemon was used; no daemon was started. All calls exited normally, so no real timeout, process kill or server cancellation was exercised. Client cleanup does not prove server cancellation. The watchdog remains a future proof limit: process construction precedes its try/finally, and close can wait up to five seconds after the nominal watchdog wait. Actual measured lifecycles did not overrun. The new-daemon startup race before job assignment was not exercised in this run. No unrelated-process termination was found.

Actual Microsoft Agent Framework execution is now evidenced. H2 is not fully closed for the judged application: this pilot was not integrated, its strict gate failed, and there is no fresh UI demonstration or human usefulness study. Preserve the failed result and all receipts. No further calls, integration or publication follow from this assessment.

This review was separate from the runner implementation owner, but the assessor authored the frozen case capsule and evaluator. It is not a blind independent benchmark. Only local file reads and these new assessment files were used; no provider or browser operations were performed in this assessment.

Evidence: `../actual-run-20261022-01/PILOT_RESULT_PRIVATE.json`, `RECEIPT_P01.json` through `RECEIPT_P04.json`, corresponding `LIFECYCLE_*.json`, and the frozen case capsule. The actual run and source were not modified.
