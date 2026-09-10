import unittest

from selfworkflow.v3.review_report import (
    MAX_REVIEW_REPORT_BYTES,
    ReviewReportError,
    normalize_review_report,
)


class ReviewReportTests(unittest.TestCase):
    def test_report_is_bounded_and_hashed(self):
        value, digest = normalize_review_report("# Review\n\nNo findings.")
        self.assertEqual(value, "# Review\n\nNo findings.")
        self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")

    def test_report_rejects_empty_or_nul_content(self):
        for value in ("", "   ", "# Review\x00"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ReviewReportError, "review-report-invalid"):
                    normalize_review_report(value)

    def test_report_rejects_oversized_content(self):
        with self.assertRaisesRegex(ReviewReportError, "review-report-too-large"):
            normalize_review_report("x" * (MAX_REVIEW_REPORT_BYTES + 1))


if __name__ == "__main__":
    unittest.main()
