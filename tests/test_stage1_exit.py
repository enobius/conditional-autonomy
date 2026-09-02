from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from runtime.conditional_autonomy.stage1_exit import (
    EXIT_CATEGORY_TESTS,
    MUTATIONS,
    _apply_mutation,
    run_stage1_exit,
)


class Stage1ExitGateTests(unittest.TestCase):
    def test_four_authoritative_exit_categories_are_explicit_exact_tests(self) -> None:
        self.assertEqual(set(EXIT_CATEGORY_TESTS), {"deterministic-replay", "leakage", "hard-unknown", "invariant-tests"})
        names = [name for tests in EXIT_CATEGORY_TESTS.values() for name in tests]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(name.startswith("tests.test_") for name in names))
        self.assertEqual({item.workstream for item in MUTATIONS}, {"1B", "1C", "1D", "1E"})
        self.assertTrue(all(item.expected_signal for item in MUTATIONS))

    def test_clean_aggregate_reports_four_green_exits_and_sixteen_verified(self) -> None:
        report = run_stage1_exit()
        self.assertTrue(report.passed)
        self.assertEqual(report.invariants_verified, 16)
        self.assertEqual(
            {item.category for item in report.categories}, set(EXIT_CATEGORY_TESTS)
        )
        self.assertTrue(all(item.passed for item in report.categories))

    def test_each_mutation_is_unique_reversible_and_confined_to_temp_copy(self) -> None:
        for mutation in MUTATIONS:
            with self.subTest(workstream=mutation.workstream), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / mutation.relative_path
                target.parent.mkdir(parents=True)
                original = ("prefix\n" + mutation.original + "\nsuffix\n").encode()
                target.write_bytes(original)
                saved = _apply_mutation(root, mutation)
                self.assertEqual(saved, original)
                self.assertIn(mutation.replacement, target.read_text(encoding="utf-8"))
                target.write_bytes(saved)
                self.assertEqual(target.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
