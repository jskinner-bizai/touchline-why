# Durable synthetic replay

`DurableController` journals deterministic M2 commands in SQLite, verifies them
on recovery, and restores the current facts, revisions, watermark, position and
audience/language view. Recovery always starts a new stream with a labelled
deterministic fallback. Live and recorded insights are never persisted.

## Interface

```python
from durable_controller import DurableController

store = DurableController(events, db_path, clock=milliseconds_callable)
state = store.control({"action": "pattern"}, operation_id="pattern-001")
state = store.state()
recovery = store.recovery_info
store.close()
```

The constructor accepts `max_commands=500` and an optional test-only `fault_hook`.
The hook receives `before_commit` or `after_commit_before_apply`.
The database parent directory must already exist. The supplied clock returns
nonnegative integer milliseconds and cannot precede the last committed command.

Allowed commands are `reset`, `next`, `pattern`, `duplicate`, `correct`, `finish` and `view`.
View requires exactly `action`, `audience` and `language`. Other actions require
exactly `action`. Operation IDs contain 1 to 128 letters, digits or `_.:-`, starting
with a letter or digit. Reusing an ID with the same command returns present state
without another commit. Reusing it with a different command fails.

`state()` returns the M2 state plus `durability` and `recovery_audit`. It preserves
the existing `publication` and `envelope` shapes. The additional durability fields
include the journal count, limit, head hash, fixture hash, last commit time and
recovery status. `control()` adds the operation ID, original sequence and a
duplicate flag to that response only.

## Commit and recovery

The wrapper holds one RLock shared with its M2 controller. It verifies the current
journal and facts, prepares the command on a detached controller, and inserts the
command and checkpoint in one `BEGIN IMMEDIATE` transaction. Only after SQLite
commits does it replace the live controller. Invalid commands and precommit
failures change neither the database nor the live controller.

A crash after commit but before application leaves the committed command in the
journal. On reopen, replay applies it once. A raised postcommit fault marks that
instance unusable and raises `CommittedCommandError` with `committed=True`.
Close and reopen it. Retrying the same operation ID after reopen is idempotent.

Opening a database checks SQLite integrity, the exact schema, fixture and source
hashes, canonical command JSON, sequence and time ordering, the hash chain and
its committed checkpoint. It then replays every command at its recorded time and
checks the resulting deterministic fact hash after every row. A logical tail
deletion fails the checkpoint check. An existing empty or physically truncated
database is refused rather than silently recreated.

The source fingerprint includes this module and the imported M2 controller,
overlay state and core files. Apply any source changes before creating the final
database. An old database under changed source fails closed; there is no automatic
migration. The hashes detect corruption and unexpected changes. They are not an
authentication mechanism against someone who can rewrite the database and hashes.

## Atomic recap completion

`finish` advances to the final fixture watermark and commits once under its exact parent operation ID. It is not a loop of separately committed child commands. A crash before commit leaves the old fact state; after commit, recovery replays the complete transition once. An exact retry returns the current state without advancing a later rewind, and its response labels whether this was a duplicate. A new finish operation ID completes the current replay. Conflicting durable IDs are rejected, including attempts to reuse a committed ID for transient selection or optional inference. The SQLite schema/version is unchanged. Preserve old-source journals; source fingerprint changes require a new runtime database.

## Transient recorded selection

The wrapper exposes `.controller` and `.lock` for a labelled recorded-selection
replay. Read the controller reference fresh while holding the lock; successful
commands replace that reference. Selection requests, accepted cards, job details,
tokens, delivery identities and TTLs are deliberately absent from the journal and
the deterministic fact hash. A transient selection therefore does not prevent a
later deterministic command from committing or recovering.

```python
with store.lock:
    controller = store.controller
    request = controller.engine.selection_request("casual", "en")
    controller.engine.apply_selection(request, recorded_selection)
    controller.job = {"status": "recorded_replay"}
```

The caller must separately label that source as recorded, with no live inference.
Do not call live selection workers. Direct changes to facts, corrections,
watermark, position or audience/language bypass persistence and are refused by
the next durable read or command. Use `store.control()` for those changes.

## Correction evidence

Public `recovery_audit.corrections` and envelope/publication
`provenance.corrections` only include corrections whose replacement event is at
or before the current watermark. Future corrections stay private until visible.
Each row contains `correction_id`, `target_event_id`, `from_revision`,
`to_revision`, `before`, `after` and `source_id`. The internal audit verifies a
contiguous revision chain and checks its final payload against the current engine.
Reset rewinds presentation time and transient selection only. Accepted correction bodies and revision history are reapplied in order, so approved corrections survive reset and implicit rewind. Details beyond the current watermark remain withheld.

## Bounds and validation

The journal holds at most 500 commands. A smaller positive limit can be set at
creation and must be supplied again when reopening that store. An exact retry
still works at capacity. There is no compaction, multi-process live synchronization
or durable model-result storage. A second live owner refuses stale state after
another owner commits and must reopen. The event bound remains M2's 500 records.

Run from this folder, with the M2 modules importable:

```text
python -B -m unittest -v test_m3_durable
```

The recorded M3 review run passed 31 tests in 1.875 seconds. That result describes the milestone snapshot, not a fresh run against later source changes. Tests use real SQLite files,
actual subprocess exits on both sides of commit, close/reopen, concurrent unique
and duplicate operation IDs, invalid commands, rollback file hashes, source and
fixture binding, schema and journal tampering, logical and physical truncation,
revision/view restoration and recorded-insight exclusion.

One review defect was fixed before this run: the administrative recovery audit
initially exposed a future correction. Public audits now use the same watermark
filter as overlay provenance. One test-harness issue was also fixed: SQLite
context managers do not close connections, so explicit closing was needed for
Windows temporary-file cleanup.

No model, browser, network, credential, access, canonical-file or publication
actions are part of this module or its tests.
