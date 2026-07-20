import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from util.step_state import DailyStepState


class DailyStepStateTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "step_state.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_store(self, candidates):
        values = iter(candidates)
        return DailyStepState(self.state_path, rng=lambda _low, _high: next(values))

    def test_lower_same_day_candidate_becomes_last_plus_one(self):
        store = self.make_store([13284, 11586])
        today = date(2026, 7, 20)

        first = store.select_step("account@example.com", today, 9000, 14000, 25000)
        store.record_success("account@example.com", today, first)
        second = store.select_step("account@example.com", today, 11000, 16000, 25000)

        self.assertEqual(13285, second)

    def test_higher_same_day_candidate_is_retained(self):
        store = self.make_store([14000])
        today = date(2026, 7, 20)

        store.record_success("account@example.com", today, 12000)

        self.assertEqual(
            14000,
            store.select_step("account@example.com", today, 11000, 16000, 25000),
        )

    def test_new_day_uses_normal_candidate_even_when_lower(self):
        store = self.make_store([8000])
        store.record_success("account@example.com", date(2026, 7, 19), 20000)

        selected = store.select_step(
            "account@example.com", date(2026, 7, 20), 6000, 9000, 25000
        )

        self.assertEqual(8000, selected)

    def test_accounts_have_independent_state(self):
        store = self.make_store([9000])
        today = date(2026, 7, 20)
        store.record_success("first@example.com", today, 15000)

        selected = store.select_step("second@example.com", today, 6000, 10000, 25000)

        self.assertEqual(9000, selected)

    def test_step_is_capped_at_configured_daily_max(self):
        store = self.make_store([24900])
        today = date(2026, 7, 20)
        store.record_success("account@example.com", today, 25000)

        selected = store.select_step(
            "account@example.com", today, 18000, 25000, 25000
        )

        self.assertEqual(25000, selected)

    def test_failed_submission_does_not_advance_state(self):
        store = self.make_store([12000, 11000])
        today = date(2026, 7, 20)

        step, ok, _ = store.submit(
            "account@example.com",
            today,
            9000,
            14000,
            25000,
            lambda _step: (False, "temporary error"),
        )
        next_step = store.select_step(
            "account@example.com", today, 9000, 14000, 25000
        )

        self.assertEqual(12000, step)
        self.assertFalse(ok)
        self.assertEqual(11000, next_step)

    def test_same_account_submissions_are_serialized_across_store_instances(self):
        today = date(2026, 7, 20)
        first_store = DailyStepState(self.state_path, rng=lambda _low, _high: 10000)
        second_store = DailyStepState(self.state_path, rng=lambda _low, _high: 10000)

        def submit(store):
            def slow_success(_step):
                time.sleep(0.05)
                return True, "ok"

            return store.submit(
                "account@example.com", today, 9000, 14000, 25000, slow_success
            )[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            steps = list(executor.map(submit, (first_store, second_store)))

        self.assertEqual([10000, 10001], sorted(steps))

    def test_state_is_reserved_before_remote_submission(self):
        store = self.make_store([12000])
        post_step = Mock(return_value=(True, "ok"))

        with patch.object(store, "_write_unlocked", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                store.submit(
                    "account@example.com",
                    date(2026, 7, 20),
                    9000,
                    14000,
                    25000,
                    post_step,
                )

        post_step.assert_not_called()

    def test_ambiguous_post_exception_keeps_reservation(self):
        store = self.make_store([12000, 11000])
        today = date(2026, 7, 20)

        with self.assertRaises(TimeoutError):
            store.submit(
                "account@example.com",
                today,
                9000,
                14000,
                25000,
                lambda _step: (_ for _ in ()).throw(TimeoutError("response lost")),
            )

        next_step = store.select_step(
            "account@example.com", today, 9000, 14000, 25000
        )
        self.assertEqual(12001, next_step)

    def test_successful_submission_records_state_without_plain_account(self):
        store = self.make_store([12000])
        today = date(2026, 7, 20)

        step, ok, _ = store.submit(
            "private-account@example.com",
            today,
            9000,
            14000,
            25000,
            lambda _step: (True, "ok"),
        )

        saved = self.state_path.read_text(encoding="utf-8")
        self.assertEqual(12000, step)
        self.assertTrue(ok)
        self.assertNotIn("private-account@example.com", saved)
        self.assertEqual(0o600, os.stat(self.state_path).st_mode & 0o777)

    def test_corrupt_state_is_treated_as_empty(self):
        self.state_path.write_text("not-json", encoding="utf-8")
        store = self.make_store([10000])

        selected = store.select_step(
            "account@example.com", date(2026, 7, 20), 9000, 11000, 25000
        )

        self.assertEqual(10000, selected)


if __name__ == "__main__":
    unittest.main()
