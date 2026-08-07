from dataclasses import FrozenInstanceError
import unittest


class CapabilityGateTests(unittest.TestCase):
    def test_capability_report_accepts_only_three_states_and_is_stably_immutable(self):
        import selfworkflow.model as model

        self.assertTrue(
            hasattr(model, "CapabilityState") and hasattr(model, "CapabilityReport"),
            "capability report behavior is not implemented",
        )
        report = model.CapabilityReport(
            {
                "test-execution": "unverified",
                "filesystem-write": "unsupported",
                "filesystem-read": "supported",
            }
        )

        self.assertEqual(
            report.states,
            (
                ("filesystem-read", model.CapabilityState.SUPPORTED),
                ("filesystem-write", model.CapabilityState.UNSUPPORTED),
                ("test-execution", model.CapabilityState.UNVERIFIED),
            ),
        )
        self.assertEqual(
            {state.value for state in model.CapabilityState},
            {"supported", "unsupported", "unverified"},
        )
        with self.assertRaises(ValueError):
            model.CapabilityReport({"filesystem-read": "degraded"})
        with self.assertRaises(FrozenInstanceError):
            report.states = ()

    def test_unsupported_required_capability_returns_structured_pause(self):
        import selfworkflow.classifier as classifier
        import selfworkflow.model as model

        self.assertTrue(
            hasattr(classifier, "check_capabilities")
            and hasattr(model, "ExecutionStatus"),
            "capability gate behavior is not implemented",
        )
        report = model.CapabilityReport({"filesystem-write": "unsupported"})
        self.assertEqual(
            {status.value for status in model.ExecutionStatus},
            {"active", "paused", "blocked", "failed", "completed"},
        )

        pause = classifier.check_capabilities(
            ["filesystem-write"],
            report,
            purposes={"filesystem-write": "persist generated workflow files"},
        )

        self.assertEqual(pause.status, model.ExecutionStatus.PAUSED)
        self.assertEqual(pause.code, "required-capabilities-unavailable")
        self.assertEqual(pause.missing_capabilities, ("filesystem-write",))
        self.assertEqual(
            pause.purposes,
            (("filesystem-write", "persist generated workflow files"),),
        )
        self.assertEqual(
            pause.reasons,
            (("filesystem-write", "capability is unsupported"),),
        )
        self.assertTrue(pause.recommendations)
        with self.assertRaises(FrozenInstanceError):
            pause.status = model.ExecutionStatus.ACTIVE

    def test_only_supported_required_capability_passes_the_gate(self):
        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import CapabilityReport

        unverified_pause = check_capabilities(
            ["test-execution"],
            CapabilityReport({"test-execution": "unverified"}),
            purposes={"test-execution": "run the required unit suite"},
        )

        self.assertIsNotNone(unverified_pause)
        self.assertEqual(
            unverified_pause.reasons,
            (("test-execution", "capability support is unverified"),),
        )
        self.assertIn("manually verify", unverified_pause.recommendations[0][1])

        supported_result = check_capabilities(
            ["test-execution"],
            CapabilityReport({"test-execution": "supported"}),
        )
        self.assertIsNone(supported_result)

    def test_unreported_required_capability_pauses_instead_of_degrading(self):
        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import CapabilityReport

        pause = check_capabilities(
            ["filesystem-write"],
            CapabilityReport({"filesystem-read": "supported"}),
        )

        self.assertIsNotNone(pause)
        self.assertEqual(pause.missing_capabilities, ("filesystem-write",))
        self.assertEqual(
            pause.purposes,
            (("filesystem-write", "required task capability"),),
        )
        self.assertEqual(
            pause.reasons,
            (("filesystem-write", "capability was not reported"),),
        )
        self.assertIn("report and verify", pause.recommendations[0][1])

    def test_verification_status_derives_unverified_from_not_run_or_partial_only(self):
        import selfworkflow.model as model

        self.assertTrue(
            hasattr(model, "VerificationStatus"),
            "verification status behavior is not implemented",
        )
        expected = {
            "not-applicable": False,
            "not-run": True,
            "partial": True,
            "passed": False,
            "failed": False,
        }

        self.assertEqual(
            {status.value for status in model.VerificationStatus},
            set(expected),
        )
        for value, is_unverified in expected.items():
            with self.subTest(value=value):
                self.assertIs(
                    model.VerificationStatus(value).is_unverified,
                    is_unverified,
                )
        with self.assertRaises(ValueError):
            model.VerificationStatus("skipped")

    def test_missing_capabilities_are_deduplicated_in_stable_lexical_order(self):
        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import CapabilityReport

        pause = check_capabilities(
            (
                "test-execution",
                "filesystem-write",
                "command-execution",
                "test-execution",
                "filesystem-write",
            ),
            CapabilityReport(
                {
                    "command-execution": "unsupported",
                    "filesystem-write": "unverified",
                    "test-execution": "unsupported",
                }
            ),
        )

        self.assertEqual(
            pause.missing_capabilities,
            ("command-execution", "filesystem-write", "test-execution"),
        )
        self.assertEqual(
            tuple(name for name, _ in pause.reasons),
            pause.missing_capabilities,
        )
        self.assertEqual(
            tuple(name for name, _ in pause.recommendations),
            pause.missing_capabilities,
        )


if __name__ == "__main__":
    unittest.main()
