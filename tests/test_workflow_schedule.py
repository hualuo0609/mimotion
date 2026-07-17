import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class WorkflowScheduleTest(unittest.TestCase):
    def test_step_workflow_uses_fixed_on_the_hour_schedule(self):
        workflow = (REPO_ROOT / ".github/workflows/run.yml").read_text()

        self.assertIn("cron: '0 0,2,4,6,8,14 * * *'", workflow)

    def test_random_cron_is_manual_only(self):
        workflow = (REPO_ROOT / ".github/workflows/cron.yml").read_text()

        self.assertNotIn("workflow_run:", workflow)
        self.assertIn("workflow_dispatch:", workflow)


if __name__ == "__main__":
    unittest.main()
