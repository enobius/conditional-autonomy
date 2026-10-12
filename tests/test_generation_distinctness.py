"""Paired reproducibility/distinctness regression; no experiment collection."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from runtime.conditional_autonomy.generation import generate_thanksgiving_instance
from runtime.conditional_autonomy.generation_validation import (
    GenerationValidationError, semantic_task_fingerprint, verify_distinct_instances,
)
from runtime.conditional_autonomy.thanksgiving import (
    DINNER, evaluate_schedule, initial_thanksgiving_state, normalized_time,
    thanksgiving_actions, utc_minute,
)
from runtime.conditional_autonomy.projection import project_observation
from tests.test_generation import generate, private_state, user_model

GRID = (11, 29, 47, 101, 103, 107, 109, 113)
ROOT = Path(__file__).resolve().parents[1]


class GeneratorDistinctnessTests(unittest.TestCase):
    def _assert_projectable(self, generated):
        state = generated.instance['initial_state']
        result = project_observation(
            state, observation_id='observation:variant-test', actor_id='actor:planner',
            source_paths=['/resources/projection_facts/sides_earliest_start'],
            goal_refs=['goal:thanksgiving-dinner'], generated_at=normalized_time(DINNER))
        self.assertEqual(result.observation['visible_facts'],
                         [state['resources']['projection_facts']['sides_earliest_start']])

    def test_approved_grid_is_reproducible_and_semantically_distinct(self):
        first = [generate(seed=s) for s in GRID]
        second = [generate(seed=s) for s in GRID]
        self.assertEqual([g.canonical_bytes() for g in first],
                         [g.canonical_bytes() for g in second])
        self.assertEqual(len(set(verify_distinct_instances(first))), len(GRID))
        for generated in first:
            self._assert_projectable(generated)

    def test_generated_release_is_projectable_under_existing_contract(self):
        self._assert_projectable(generate(seed=11))

    def test_generated_window_changes_an_executable_constraint(self):
        low, high = generate(seed=11), generate(seed=113)
        actions = thanksgiving_actions()
        sides = next(a for a in actions if a.action_type == 'thanksgiving:prepare-sides')
        obligation = next(o for o in low.instance['initial_state']['obligations']
                          if o['obligation_id'] == sides.obligation_id)
        start = utc_minute(obligation['window']['start']['instant'])
        delta = start + 120 - sides.end_minute
        candidate = replace(sides, start_minute=start, end_minute=start + 120,
                            effects=tuple(replace(e, earliest_minute=e.earliest_minute + delta,
                                                  latest_minute=e.latest_minute + delta)
                                          for e in sides.effects))
        schedule = tuple(candidate if a is sides else a for a in actions)
        check = lambda g: next(e.passed for e in evaluate_schedule(
            g.instance['initial_state'], schedule) if e.constraint.constraint_id == 'constraint:time-windows')
        self.assertTrue(check(low))
        self.assertFalse(check(high))

    def test_metadata_and_graph_hash_changes_cannot_fake_distinctness(self):
        first = generate(seed=11).instance
        changed = deepcopy(first)
        changed.update(seed=999, instance_id='instance:forged', source_dataset_lineage=['other'])
        changed['constraint_graph'] = {'forged': True}
        changed['entity_graph'] = {'forged': True}
        self.assertEqual(semantic_task_fingerprint(first), semantic_task_fingerprint(changed))
        with self.assertRaises(GenerationValidationError):
            verify_distinct_instances([generate(seed=11), generate(seed=131)])

    def test_graph_preserving_id_renaming_does_not_create_a_new_task(self):
        instance = generate(seed=11).instance
        identities = list(instance['initial_state']['entities'])
        identities += list(instance['initial_state']['resources']['capacities'])
        identities += [o['obligation_id'] for o in instance['initial_state']['obligations']]
        identities += [a['action_id'] for a in instance['action_plan']]
        identities += [d['deadline_id'] for d in instance['initial_state']['deadlines']]
        text = json.dumps(instance)
        for index, old in enumerate(identities):
            text = text.replace(old, 'renamed:' + str(index))
        self.assertEqual(semantic_task_fingerprint(instance),
                         semantic_task_fingerprint(json.loads(text)))

    def test_legacy_canonical_version_is_preserved(self):
        legacy = generate_thanksgiving_instance(
            seed=11, generator_version='1.0', difficulty_parameters={'entities': 8},
            user_model=user_model(), private_world_state=private_state(),
            source_dataset_lineage=['dataset:realm-p6'], split_assignment='TEST')
        legacy.verify()
        self.assertEqual(legacy.instance['initial_state'], initial_thanksgiving_state())

    def test_zero_offset_mirror_does_not_fake_a_new_canonical_task(self):
        legacy = generate_thanksgiving_instance(
            seed=120, generator_version='1.0', difficulty_parameters={'entities': 8},
            user_model=user_model(), private_world_state=private_state(),
            source_dataset_lineage=['dataset:realm-p6'], split_assignment='TEST')
        self.assertEqual(semantic_task_fingerprint(legacy.instance),
                         semantic_task_fingerprint(generate(seed=120).instance))

    def test_legacy_bytes_match_the_verified_pre_change_clone(self):
        legacy = generate_thanksgiving_instance(
            seed=11, generator_version='1.0',
            difficulty_parameters={'entities': 8, 'disruptions': 0},
            user_model=user_model(), private_world_state=private_state(),
            source_dataset_lineage=['dataset:realm-p6', 'dataset:reviewed-static'],
            split_assignment='TEST')
        # Independently measured from the verified 8560527 clone, not the new generator.
        self.assertEqual(hashlib.sha256(legacy.canonical_bytes()).hexdigest(),
                         'c7000df23dc22d1a7fd4dc75c6da82c98d4dc7f8ce12276d1ab77ed2e77d6ec8')

    def test_constant_generator_mutation_is_detected_and_restoration_is_green(self):
        from runtime.conditional_autonomy import generation
        original = generation._seeded_variant_state
        with mock.patch.object(generation, '_seeded_variant_state',
                               side_effect=lambda seed, version: original(11, version)):
            with self.assertRaises(generation.InstanceGenerationError):
                generate(seed=29)
        self.assertEqual(len(verify_distinct_instances([generate(seed=s) for s in GRID])), len(GRID))

    def test_fresh_processes_reproduce_the_complete_regression_grid(self):
        command = 'from tests.test_generation import generate; from tests.test_generation_distinctness import GRID; import sys; sys.stdout.buffer.write(b"\\n".join(generate(seed=s).canonical_bytes() for s in GRID))'
        results = [subprocess.check_output([sys.executable, '-B', '-c', command], cwd=ROOT,
                   env=dict(os.environ, PYTHONHASHSEED=s)) for s in ('1', '91')]
        self.assertEqual(results[0], results[1])


if __name__ == '__main__':
    unittest.main()
