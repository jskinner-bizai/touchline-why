# Core version recovery proof

F6 passed on 22 October 2026 in a local scratch runtime using Python 3.12.2 on Windows. No application source or existing journal was edited. No model, network, browser, deployment, or credentials were used.

## Observed result

The rehearsal created a new synthetic SQLite journal and committed `pattern`, `correct`, `finish`, `reset`, and `pattern`. That includes an approved correction, a recap, a rewind, and reopening the corrected evidence window.

It then appended exactly one newline byte to the scratch copy of `app_m2.py`. A new Python process refused to open the existing journal with:

```text
DurableIntegrityError: Fixture, source or schema fingerprint mismatch
```

After restoring the exact original `app_m2.py` bytes, another new process reopened the same journal. Event `e010` retained revision 2, its goal was removed, Harbor Owls retained score 0, all five commands and the journal head were preserved, and the factual state matched the state before source drift. Reopening emitted a safe deterministic fallback with reason `recovered`.

The journal stayed byte-for-byte identical before the rejected open and after the restored-source open:

```text
1aa975487050f2d88bc478f31e2e8239d7f20c7764f8aa60a40cb0f4cf966b49
```

The source-plus-fixture identity for this proof is:

```text
57d18c4573da6d2e3b41046160e633b7c84ef3eea5a5acb24c15e90b0d3c03e1
```

`SOURCE_CORE_SHA256.json` contains the five exact file hashes. `REHEARSAL_RESULT.json` contains outcomes, environment, paths, and limitations. The retained `run-20261022T142120Z-8be86b08` directory contains the exact runtime, preserved journal, and separate-process receipts for creation, refusal, and recovery. No journal was deleted, reset, migrated, or edited to accept a different fingerprint.

## Release and recovery policy

1. Freeze the four journal-identity modules and synthetic fixture for this release. The modules are `durable_controller.py`, `app_m2.py`, `overlay_state.py`, and `touchline_core.py`. Even a harmless source-byte change requires an explicit compatibility decision. UI and advisory changes still need the normal whole-release tests and manifest.
2. Retain the complete versioned application package, pinned dependencies/runtime instructions, full source manifest, this core fingerprint manifest, and the matching journal backup together. This proof's manifest identifies core compatibility; it does not replace the full application release manifest or provide cryptographic signing.
3. If an existing journal refuses to open, stop the rollout and prevent competing writers. Preserve the journal and any SQLite companion files using a consistent backup procedure. Restore the exact matching release package identified by the journal and retained manifests. Do not modify stored hashes, disable validation, delete the journal, or silently create a replacement journal at the same user path.
4. Reopen with that matching runtime and verify correction revision, score, command count/head, and safe recovery status before resuming writes. The scratch rehearsal demonstrates this exact-source restoration path, including unchanged journal bytes.
5. A future core change must retain access to the old runtime for old journals. A release-to-data mapping and separate versioned journal locations can support that isolation, but no automatic router or migration is implemented by this patch. Any later migration needs its own reviewed, backup-preserving procedure and regression evidence.

## Reproduce

From the separate recovery-proof directory in the review packet, run the retained script with a supported Python interpreter:

```powershell
python -B .\rehearse_core_recovery.py
```

Each run creates a new scratch directory, preserves its journal, verifies the source remained unchanged, and refreshes the two top-level JSON result files. Child processes also use `-B` and `PYTHONDONTWRITEBYTECODE=1`. Only the scratch `app_m2.py` changes during the test, and it is restored in a `finally` block.

This is a source-compatibility and journal-preservation proof. Azure mounted storage, remote backup/restore, rolling deployment, and migration between core versions remain untested. Host qualification must verify those separately before making corresponding availability claims.
