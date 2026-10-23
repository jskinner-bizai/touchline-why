"""Pure frozen-rubric evaluator. No provider, browser, SDK or runtime mutation.

The adapter owns strict response parsing. This evaluator also checks shape so
malformed data cannot accidentally earn credit. Evidence joins and semantic
labels are separate: a current fact ID can still support the wrong draft clause.
"""
from __future__ import annotations

KEYS = {'decision', 'keep', 'drop', 'facts', 'reason'}
DECISIONS = {'allow', 'revise', 'withhold'}
REASONS = {'supported', 'unsupported_causality', 'contradicted_fact', 'stale_revision'}


def _shape(value):
    if not isinstance(value, dict) or set(value) != KEYS:
        return False
    if (not isinstance(value.get('decision'), str) or not isinstance(value.get('reason'), str)
            or value['decision'] not in DECISIONS or value['reason'] not in REASONS):
        return False
    for key, maximum in [('keep', 3), ('drop', 3), ('facts', 4)]:
        rows = value.get(key)
        if (not isinstance(rows, list) or len(rows) > maximum
                or any(not isinstance(item, str) or not 1 <= len(item) <= 32 for item in rows)
                or len(rows) != len(set(rows))):
            return False
    return True


def evaluate_baseline(case_input):
    """Conservative exact-canonical matcher; performs no semantic diagnosis."""
    normalize = lambda text: ' '.join(text.casefold().strip().rstrip('.').split())
    known = {normalize(fact['text']): fact_id for fact_id, fact in case_input['facts'].items()}
    keep, drop, facts = [], [], []
    for clause in case_input['draft_clauses']:
        fact_id = known.get(normalize(clause['text']))
        if fact_id is None:
            drop.append(clause['id'])
        else:
            keep.append(clause['id'])
            if fact_id not in facts:
                facts.append(fact_id)
    return {'decision': 'allow' if not drop else 'revise' if keep else 'withhold',
            'keep': keep, 'drop': drop, 'facts': facts,
            'reason': 'exact_canonical_match' if not drop else 'manual_review_noncanonical',
            'semantic_assessment_performed': False, 'raw_draft_published': False}


def evaluate_case(expected, response):
    """Evaluate one ground_truth.json cases[opaque_id] record and response dict.

    Array order carries no meaning in this contract; duplicates are invalid.
    This is a four-case static rubric, not a validator of arbitrary prose or a
    live-state check. Runtime digest/expiry checks remain the runner's duty.
    Neither argument is mutated. Invalid frozen ground truth is a caller error.
    """
    if not isinstance(expected, dict) or not _shape(expected.get('expected_response')):
        raise ValueError('Invalid frozen expected record')
    gold = expected['expected_response']
    context = expected['context']
    clause_ids = set(expected['draft_clause_ids'])
    justified = set(expected['justified_fact_ids'])
    baseline = expected['baseline']
    shape = _shape(response)
    actual = response if shape else {'decision': '', 'keep': [], 'drop': [], 'facts': [], 'reason': ''}
    keep, drop = set(actual['keep']), set(actual['drop'])
    partition = shape and not (keep & drop) and keep | drop == clause_ids
    decision_consistent = shape and (
        (actual['decision'] == 'allow' and keep == clause_ids and not drop)
        or (actual['decision'] == 'withhold' and not keep and drop == clause_ids and not actual['facts'])
        or (actual['decision'] == 'revise' and bool(keep) and bool(drop))
    )
    joins = []
    for fact_id in actual['facts']:
        fact = context['facts'].get(fact_id)
        present = isinstance(fact, dict)
        ids = fact.get('evidence_ids', []) if present else []
        revisions = fact.get('event_revisions', {}) if present else {}
        times = context['evidence_times_ms']
        current = context['event_revisions']
        timed = bool(ids) and all(type(times.get(event)) is int and 0 <= times[event] <= context['watermark_ms'] for event in ids)
        revision_join = bool(ids) and set(revisions) == set(ids) and all(
            type(revisions.get(event)) is int and revisions[event] >= 1 and revisions[event] == current.get(event)
            for event in ids)
        joins.append({'fact_id': fact_id, 'present_in_input': present,
                      'event_time_join_valid': bool(timed), 'revision_join_valid': bool(revision_join),
                      'justified_for_retained_clause': fact_id in justified})
    current_joins = shape and all(row['present_in_input'] and row['event_time_join_valid']
                                  and row['revision_join_valid'] for row in joins)
    scope_joins = shape and set(actual['facts']) <= justified
    scores = {
        'decision': int(shape and actual['decision'] == gold['decision']),
        'retained_clauses': int(shape and keep == set(gold['keep'])),
        'dropped_clauses': int(shape and drop == set(gold['drop'])),
        'fact_support': int(shape and set(actual['facts']) == set(gold['facts'])),
        'reason': int(shape and actual['reason'] == gold['reason']),
        'current_evidence_joins': int(current_joins),
    }
    semantic = bool(shape and partition and decision_consistent
                    and all(scores[key] for key in ('decision', 'retained_clauses', 'dropped_clauses', 'fact_support', 'reason')))
    evidence = bool(current_joins and scope_joins)
    baseline_keep = set(baseline['keep'])
    retention_gain = len(keep - baseline_keep) if semantic else 0
    reason_added = bool(semantic and not baseline['semantic_assessment_performed'])
    return {
        'schema_shape_valid': bool(shape), 'clause_partition_valid': bool(partition),
        'decision_consistent_with_partition': bool(decision_consistent),
        'scores': scores, 'semantic_pass': semantic, 'evidence_join_pass': evidence,
        'rubric_pass': bool(semantic and evidence), 'evidence_joins': joins,
        'baseline_comparison': {
            'baseline_decision': baseline['decision'],
            'baseline_reason': baseline['reason'],
            'baseline_publishes_unsafe_draft': False,
            'retained_supported_clauses_above_baseline': retention_gain,
            'case_specific_semantic_reason_added': reason_added,
            'useful_diagnosis_candidate': bool(semantic and evidence and (reason_added or retention_gain)),
            'human_usefulness_measured': False,
            'qualification': 'A correct frozen-case diagnosis/retention beyond generic manual review; not measured producer benefit or general model accuracy.',
        },
        'qualification': 'Current ID/revision joins do not by themselves prove semantic correctness. No model output is published by this evaluator.',
    }
