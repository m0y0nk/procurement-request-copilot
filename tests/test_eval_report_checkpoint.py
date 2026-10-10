import unittest

from eval.report_checkpoint import build_checkpoint


class CheckpointReportTests(unittest.TestCase):
    def test_report_scores_matched_model_and_fail_closed_rows(self):
        summary, report = build_checkpoint()

        metrics = summary["summary"]
        self.assertEqual(metrics["A"]["runs"], 22)
        self.assertEqual(metrics["B"]["runs"], 22)
        self.assertEqual(metrics["B"]["recommendation_accuracy"], 0.5)
        self.assertAlmostEqual(metrics["B"]["approvals_match"], 3 / 22)
        self.assertEqual(metrics["B"]["measured_tokens"], 182876)
        self.assertEqual(metrics["B"]["missing_usage_rows"], 1)
        self.assertEqual(metrics["B"]["execution_failures"], 6)
        self.assertEqual(
            summary["models"],
            {"A": "openai/gpt-oss-120b", "B": "openai/gpt-oss-120b"},
        )
        self.assertIn("used GPT-OSS 120B", report)
        self.assertIn("No holdout run was performed", report)
        self.assertIn("only recommendation mismatch is C-003", report)
        self.assertIn("C-001, C-003, C-004, C-005, C-015, C-017", report)
        self.assertIn("182,876", report)
        self.assertIn("trace-reported subtotal", report)
        self.assertNotIn("Interpret this section from the actual traces", report)
        self.assertIn("agent execution failures", report)


if __name__ == "__main__":
    unittest.main()
