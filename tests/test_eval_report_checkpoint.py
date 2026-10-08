import unittest

from eval.report_checkpoint import build_checkpoint


class CheckpointReportTests(unittest.TestCase):
    def test_report_marks_partial_architecture_b_scope(self):
        summary, report = build_checkpoint()

        metrics = summary["summary"]
        self.assertEqual(metrics["A"]["runs"], 22)
        self.assertEqual(metrics["B"]["runs"], 4)
        self.assertEqual(metrics["B"]["measured_tokens"], 36249)
        self.assertIn("not a completed head-to-head comparison", report)
        self.assertIn("holdout split has not been run", report)
        self.assertIn("only recommendation mismatch is C-003", report)
        self.assertIn("36,249", report)
        self.assertNotIn("Interpret this section from the actual traces", report)
        self.assertIn("0.452", report)


if __name__ == "__main__":
    unittest.main()
