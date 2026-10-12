"""Independent task-content checks; never invoke the instance generator.

The current generated P6 domain varies the operative earliest side-preparation
time by 0..119 minutes. It is an engineering domain, not a frozen Stage 2
distribution. Canonical hand-authored fixtures and legacy v1 bytes stay intact.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib

from .storage import canonical_json_bytes
from .thanksgiving import initial_thanksgiving_state, normalized_time, utc_minute


class GenerationValidationError(ValueError):
    pass


def check_variant_state(state: Mapping, *, version: str, seed: int) -> None:
    """Check serialized content against the declared domain, not generator output."""
    canonical = initial_thanksgiving_state()
    if version == '1.0':
        if canonical_json_bytes(state) != canonical_json_bytes(canonical):
            raise GenerationValidationError('legacy initial state is not canonical')
        return
    if version != '2.0' or type(seed) is not int:
        raise GenerationValidationError('unsupported variant version or seed')
    candidate = deepcopy(dict(state))
    target = next((o for o in candidate['obligations']
                   if o['obligation_id'] == 'obligation:sides-ready'), None)
    if target is None:
        raise GenerationValidationError('missing side-preparation obligation')
    baseline = next(o for o in canonical['obligations']
                    if o['obligation_id'] == 'obligation:sides-ready')
    actual = utc_minute(target['window']['start']['instant'])
    earliest = utc_minute(baseline['window']['start']['instant'])
    if not 0 <= actual - earliest <= 119 or actual - earliest != seed % 120:
        raise GenerationValidationError('side-preparation release is not seed-bound')
    facts = candidate['resources']['projection_facts']
    expected_fact = {
        'fact_id': 'fact:sides-earliest-start', 'value': normalized_time(actual),
        'access_class': 'POLICY_VISIBLE',
    }
    if facts.pop('sides_earliest_start', None) != expected_fact:
        raise GenerationValidationError('projected release fact is not bound')
    target['window']['start'] = baseline['window']['start']
    if canonical_json_bytes(candidate) != canonical_json_bytes(canonical):
        raise GenerationValidationError('variant changed facts outside the declared domain')


def semantic_task_fingerprint(instance: Mapping) -> str:
    """ID-renaming-invariant fingerprint of operative P6 task content.

    This is not a general graph-isomorphism solver. Role signatures include
    resource use and action types; ambiguous signatures fail closed. Integrity
    and domain validation must precede corpus admission.
    """
    state, actions = instance['initial_state'], instance['action_plan']
    ids: dict[str, str] = {}

    def scrub(value):
        if isinstance(value, Mapping):
            return {k: scrub(v) for k, v in value.items()
                    if k not in {'access_class', 'fact_id', 'obligation_id',
                                 'action_id', 'deadline_id', 'dependency_ids'}}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    def bind(items):
        seen = set()
        for identity, profile in items:
            signature = hashlib.sha256(canonical_json_bytes(profile)).hexdigest()
            if signature in seen:
                raise GenerationValidationError('ambiguous semantic node signatures')
            seen.add(signature)
            ids[identity] = 'semantic:' + signature

    bind((k, scrub(v)) for k, v in state['entities'].items())
    bind((k, {'properties': scrub(v), 'uses': sorted(
        a['action_type'] for a in actions if k in a['resource_ids'])})
         for k, v in state['resources']['capacities'].items())
    bind((o['obligation_id'], scrub(o)) for o in state['obligations'])
    bind((a['action_id'], {'action_type': a['action_type']}) for a in actions)
    bind((d['deadline_id'], scrub(d)) for d in state['deadlines'])

    def normalize(value):
        if isinstance(value, Mapping):
            return {ids.get(k, k): normalize(v) for k, v in value.items()
                    if k not in {'access_class', 'fact_id'}}
        if isinstance(value, list):
            return sorted((normalize(v) for v in value), key=canonical_json_bytes)
        if isinstance(value, str):
            if value in ids:
                return ids[value]
            if value.startswith('/'):
                return '/'.join(ids.get(s, s) for s in value.split('/'))
        return value

    content = {k: state[k] for k in ('entities', 'resources', 'obligations',
                                   'dependencies', 'deadlines', 'permissions')}
    # The projected release mirrors the obligation, not an additional task.
    # A zero-offset v2 case must not look distinct from the canonical v1 case.
    content['resources'] = deepcopy(content['resources'])
    content['resources']['projection_facts'].pop('sides_earliest_start', None)
    content['action_plan'] = actions
    encoded = canonical_json_bytes({'domain': 'p6-semantic-task-v1',
                                    'content': normalize(content)})
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def verify_distinct_instances(instances: Sequence) -> tuple[str, ...]:
    """Admit only verified, structurally distinct bases (not matched variants)."""
    fingerprints = []
    for generated in instances:
        generated.verify()
        fingerprints.append(semantic_task_fingerprint(generated.instance))
    if len(set(fingerprints)) != len(fingerprints):
        raise GenerationValidationError('structurally duplicate task bases')
    return tuple(fingerprints)
