import unittest

from eval.report_checkpoint import build_checkpoint


class CheckpointReportTests(unittest.TestCase):
    def test_report_marks_model_mismatch_and_fail_closed_rows(self):
        summary, report = build_checkpoint()

        metrics = summary["summary"]
        self.assertEqual(metrics["A"]["runs"], 22)
        self.assertEqual(metrics["B"]["runs"], 22)
        self.assertEqual(metrics["B"]["measured_tokens"], 175836)
        self.assertEqual(metrics["B"]["execution_failures"], 6)
        self.assertIn("not a matched model comparison", report)
        self.assertIn("No holdout run was performed", report)
        self.assertIn("only recommendation mismatch is C-003", report)
        self.assertIn("C-007, C-008, C-011, C-013, C-016, C-018", report)
        self.assertIn("175,836", report)
        self.assertNotIn("Interpret this section from the actual traces", report)
        self.assertIn("agent execution failures", report)


if __name__ == "__main__":
    unittest.main()
