from dataclasses import FrozenInstanceError
import unittest


class CapabilityGateTests(unittest.TestCase):
    def test_public_ordered_inputs_reject_set_and_frozenset(self):
        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import (
            CapabilityReport,
            PauseResult,
            TaskClassification,
        )

        report = CapabilityReport({})
        for unordered_type in (set, frozenset):
            cases = (
                (
                    "classification reasons",
                    "classification-input-invalid",
                    lambda: TaskClassification(
                        "C0", "R0", unordered_type(["hidden-reason"])
                    ),
                ),
                (
                    "pause missing capabilities",
                    "pause-result-invalid",
                    lambda: PauseResult(
                        unordered_type(["filesystem-read"]), (), (), ()
                    ),
                ),
                (
                    "pause purposes",
                    "pause-result-invalid",
                    lambda: PauseResult(
                        (),
                        unordered_type([("filesystem-read", "hidden-purpose")]),
                        (),
                        (),
                    ),
                ),
                (
                    "pause reasons",
                    "pause-result-invalid",
                    lambda: PauseResult(
                        (),
                        (),
                        unordered_type([("filesystem-read", "hidden-reason")]),
                        (),
                    ),
                ),
                (
                    "pause recommendations",
                    "pause-result-invalid",
                    lambda: PauseResult(
                        (),
                        (),
                        (),
                        unordered_type(
                            [("filesystem-read", "hidden-recommendation")]
                        ),
                    ),
                ),
                (
                    "capability report entries",
                    "capability-report-invalid",
                    lambda: CapabilityReport(
                        unordered_type([("filesystem-read", "supported")])
                    ),
                ),
                (
                    "required capabilities",
                    "capability-gate-input-invalid",
                    lambda: check_capabilities(
                        unordered_type(["filesystem-read"]), report
                    ),
                ),
            )

            for label, expected_code, call in cases:
                with self.subTest(unordered_type=unordered_type, boundary=label):
                    try:
                        call()
                    except Exception as error:
                        self.assertIsInstance(error, ValueError)
                        self.assertEqual(str(error), expected_code)
                        self.assertNotIn("hidden", str(error))
                    else:
                        self.fail("unordered public input was accepted")

    def test_top_level_iterable_failures_are_redacted_at_public_boundaries(self):
        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import (
            CapabilityReport,
            PauseResult,
            TaskClassification,
        )

        no_value = object()

        class ExplodingIterable:
            def __init__(self, first=no_value):
                self.first = first

            def __iter__(self):
                if self.first is not no_value:
                    yield self.first
                raise ValueError("TOP-SECRET-ITERATION")

        report = CapabilityReport({})
        for phase in ("before-first", "after-first"):
            first_values = (
                no_value
                if phase == "before-first"
                else {
                    "classification": "valid reason",
                    "pause": "filesystem-read",
                    "report": ("filesystem-read", "supported"),
                    "gate": "filesystem-read",
                }
            )
            cases = (
                (
                    "classification",
                    "classification-input-invalid",
                    lambda: TaskClassification(
                        "C0",
                        "R0",
                        ExplodingIterable(
                            no_value
                            if first_values is no_value
                            else first_values["classification"]
                        ),
                    ),
                ),
                (
                    "pause",
                    "pause-result-invalid",
                    lambda: PauseResult(
                        ExplodingIterable(
                            no_value
                            if first_values is no_value
                            else first_values["pause"]
                        ),
                        (),
                        (),
                        (),
                    ),
                ),
                (
                    "report",
                    "capability-report-invalid",
                    lambda: CapabilityReport(
                        ExplodingIterable(
                            no_value
                            if first_values is no_value
                            else first_values["report"]
                        )
                    ),
                ),
                (
                    "gate",
                    "capability-gate-input-invalid",
                    lambda: check_capabilities(
                        ExplodingIterable(
                            no_value
                            if first_values is no_value
                            else first_values["gate"]
                        ),
                        report,
                    ),
                ),
            )

            for boundary, expected_code, call in cases:
                with self.subTest(phase=phase, boundary=boundary):
                    try:
                        call()
                    except Exception as error:
                        self.assertIsInstance(error, ValueError)
                        self.assertEqual(str(error), expected_code)
                        self.assertIsNone(error.__cause__)
                        self.assertNotIn("TOP-SECRET", str(error))
                    else:
                        self.fail("exploding iterable was accepted")

    def test_pause_result_redacts_iteration_failures_for_all_four_collections(self):
        from selfworkflow.model import PauseResult

        class ExplodingIterable:
            def __init__(self, first):
                self.first = first

            def __iter__(self):
                yield self.first
                raise ValueError("TOP-SECRET-PAUSE-ITERATION")

        cases = (
            lambda: PauseResult(
                ExplodingIterable("filesystem-read"), (), (), ()
            ),
            lambda: PauseResult(
                (),
                ExplodingIterable(("filesystem-read", "read task inputs")),
                (),
                (),
            ),
            lambda: PauseResult(
                (),
                (),
                ExplodingIterable(("filesystem-read", "not reported")),
                (),
            ),
            lambda: PauseResult(
                (),
                (),
                (),
                ExplodingIterable(("filesystem-read", "report capability")),
            ),
        )

        for index, call in enumerate(cases):
            with self.subTest(field_index=index):
                try:
                    call()
                except Exception as error:
                    self.assertIsInstance(error, ValueError)
                    self.assertEqual(str(error), "pause-result-invalid")
                    self.assertIsNone(error.__cause__)
                    self.assertNotIn("TOP-SECRET", str(error))
                else:
                    self.fail("exploding pause collection was accepted")

    def test_pair_materialization_failures_are_redacted(self):
        from selfworkflow.model import CapabilityReport, PauseResult

        class ExplodingPair:
            def __iter__(self):
                yield "filesystem-read"
                raise ValueError("TOP-SECRET-PAIR-ITERATION")

        cases = (
            (
                "pause purposes",
                "pause-result-invalid",
                lambda: PauseResult((), [ExplodingPair()], (), ()),
            ),
            (
                "pause reasons",
                "pause-result-invalid",
                lambda: PauseResult((), (), [ExplodingPair()], ()),
            ),
            (
                "pause recommendations",
                "pause-result-invalid",
                lambda: PauseResult((), (), (), [ExplodingPair()]),
            ),
            (
                "capability report",
                "capability-report-invalid",
                lambda: CapabilityReport([ExplodingPair()]),
            ),
        )

        for boundary, expected_code, call in cases:
            with self.subTest(boundary=boundary):
                try:
                    call()
                except Exception as error:
                    self.assertIsInstance(error, ValueError)
                    self.assertEqual(str(error), expected_code)
                    self.assertIsNone(error.__cause__)
                    self.assertNotIn("TOP-SECRET", str(error))
                else:
                    self.fail("exploding pair was accepted")

    def test_pause_pair_mappings_are_normalized_in_lexical_key_order(self):
        from selfworkflow.model import PauseResult

        descending = {
            "test-execution": "second",
            "filesystem-read": "first",
        }
        ascending = {
            "filesystem-read": "first",
            "test-execution": "second",
        }
        expected = (
            ("filesystem-read", "first"),
            ("test-execution", "second"),
        )

        for field_index in (1, 2, 3):
            descending_arguments = [(), (), (), ()]
            ascending_arguments = [(), (), (), ()]
            descending_arguments[field_index] = descending
            ascending_arguments[field_index] = ascending

            with self.subTest(field_index=field_index):
                descending_pause = PauseResult(*descending_arguments)
                ascending_pause = PauseResult(*ascending_arguments)
                field_name = ("purposes", "reasons", "recommendations")[
                    field_index - 1
                ]
                self.assertEqual(getattr(descending_pause, field_name), expected)
                self.assertEqual(
                    getattr(descending_pause, field_name),
                    getattr(ascending_pause, field_name),
                )

    def test_mapping_materialization_failures_are_redacted(self):
        from collections.abc import Mapping

        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import CapabilityReport, PauseResult

        class ExplodingMapping(Mapping):
            def __init__(self, value):
                self.value = value

            def __getitem__(self, key):
                return self.value

            def __iter__(self):
                yield "filesystem-read"
                raise ValueError("TOP-SECRET-MAPPING-ITERATION")

            def __len__(self):
                return 2

            def items(self):
                yield ("filesystem-read", self.value)
                raise ValueError("TOP-SECRET-MAPPING-ITEMS")

        cases = (
            (
                "pause pairs",
                "pause-result-invalid",
                lambda: PauseResult(
                    (), ExplodingMapping("read task inputs"), (), ()
                ),
            ),
            (
                "capability report entries",
                "capability-report-invalid",
                lambda: CapabilityReport(ExplodingMapping("supported")),
            ),
            (
                "capability gate purposes",
                "capability-gate-input-invalid",
                lambda: check_capabilities(
                    ["filesystem-read"],
                    CapabilityReport({"filesystem-read": "unsupported"}),
                    purposes=ExplodingMapping("read task inputs"),
                ),
            ),
        )

        for boundary, expected_code, call in cases:
            with self.subTest(boundary=boundary):
                try:
                    call()
                except Exception as error:
                    self.assertIsInstance(error, ValueError)
                    self.assertEqual(str(error), expected_code)
                    self.assertIsNone(error.__cause__)
                    self.assertNotIn("TOP-SECRET", str(error))
                else:
                    self.fail("exploding mapping was accepted")

    def test_materialization_does_not_catch_base_exceptions(self):
        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import (
            CapabilityReport,
            PauseResult,
            TaskClassification,
        )

        class AbortingIterable:
            def __iter__(self):
                raise KeyboardInterrupt("CONTROL-FLOW")
                yield None

        class AbortingMapping(dict):
            def items(self):
                raise KeyboardInterrupt("CONTROL-FLOW")

        cases = (
            lambda: TaskClassification("C0", "R0", AbortingIterable()),
            lambda: PauseResult(AbortingIterable(), (), (), ()),
            lambda: PauseResult((), [AbortingIterable()], (), ()),
            lambda: PauseResult((), AbortingMapping(), (), ()),
            lambda: CapabilityReport(AbortingIterable()),
            lambda: check_capabilities(
                AbortingIterable(),
                CapabilityReport({}),
            ),
            lambda: check_capabilities(
                [],
                CapabilityReport({}),
                purposes=AbortingMapping(),
            ),
        )

        for index, call in enumerate(cases):
            with self.subTest(boundary=index):
                with self.assertRaises(KeyboardInterrupt) as raised:
                    call()
                self.assertEqual(str(raised.exception), "CONTROL-FLOW")

    def test_pause_result_copies_external_collections_to_nested_tuples(self):
        from selfworkflow.model import PauseResult

        missing = ["filesystem-write"]
        purposes = {"filesystem-write": "persist workflow files"}
        reasons = [["filesystem-write", "capability is unsupported"]]
        recommendations = [
            ["filesystem-write", "provide supported capability: filesystem-write"]
        ]

        pause = PauseResult(missing, purposes, reasons, recommendations)
        missing.append("test-execution")
        purposes["filesystem-write"] = "changed"
        reasons[0][1] = "changed"
        recommendations[0][1] = "changed"

        self.assertEqual(pause.missing_capabilities, ("filesystem-write",))
        self.assertEqual(
            pause.purposes,
            (("filesystem-write", "persist workflow files"),),
        )
        self.assertEqual(
            pause.reasons,
            (("filesystem-write", "capability is unsupported"),),
        )
        self.assertEqual(
            pause.recommendations,
            (
                (
                    "filesystem-write",
                    "provide supported capability: filesystem-write",
                ),
            ),
        )

    def test_pause_result_rejects_invalid_nested_values_with_fixed_error(self):
        from selfworkflow.model import PauseResult

        invalid_arguments = (
            (["filesystem-write", ["hidden-input"]], (), (), ()),
            (
                ["filesystem-write"],
                [["filesystem-write", ["hidden-input"]]],
                (),
                (),
            ),
            (
                ["filesystem-write"],
                (),
                [["filesystem-write"]],
                (),
            ),
            (
                ["filesystem-write"],
                (),
                (),
                [["filesystem-write", 7]],
            ),
        )

        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                try:
                    PauseResult(*arguments)
                except Exception as error:
                    self.assertIsInstance(error, ValueError)
                    self.assertEqual(str(error), "pause-result-invalid")
                    self.assertNotIn("hidden-input", str(error))
                else:
                    self.fail("invalid nested pause value was accepted")

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

    def test_capability_report_rejects_invalid_inputs_with_fixed_error(self):
        from selfworkflow.model import CapabilityReport

        invalid_states = (
            {"filesystem-read": "hidden-state"},
            {"": "supported"},
            {7: "supported"},
            (
                ("filesystem-read", "supported"),
                ("filesystem-read", "unsupported"),
            ),
        )

        for states in invalid_states:
            with self.subTest(states=states):
                try:
                    CapabilityReport(states)
                except Exception as error:
                    self.assertIsInstance(error, ValueError)
                    self.assertEqual(str(error), "capability-report-invalid")
                    self.assertNotIn("hidden-state", str(error))
                    self.assertNotIn("filesystem-read", str(error))
                else:
                    self.fail("invalid capability report was accepted")

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

    def test_capability_gate_rejects_invalid_inputs_before_sorting(self):
        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import CapabilityReport

        report = CapabilityReport({"filesystem-read": "unsupported"})
        invalid_calls = (
            lambda: check_capabilities(["filesystem-read", 7], report),
            lambda: check_capabilities("filesystem-read", report),
            lambda: check_capabilities(None, report),
            lambda: check_capabilities(
                ["filesystem-read"],
                report,
                purposes={"filesystem-read": 7},
            ),
            lambda: check_capabilities(
                ["filesystem-read"],
                report,
                purposes={7: "hidden-purpose"},
            ),
            lambda: check_capabilities(
                ["filesystem-read"],
                report,
                purposes=[("filesystem-read", "hidden-purpose")],
            ),
        )

        for invalid_call in invalid_calls:
            with self.subTest(call=invalid_call):
                try:
                    invalid_call()
                except Exception as error:
                    self.assertIsInstance(error, ValueError)
                    self.assertEqual(str(error), "capability-gate-input-invalid")
                    self.assertNotIn("hidden-purpose", str(error))
                    self.assertNotIn("filesystem-read", str(error))
                else:
                    self.fail("invalid capability gate input was accepted")

    def test_gap_recommendations_are_exact_actionable_and_capability_bound(self):
        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import CapabilityReport

        pause = check_capabilities(
            ("test-execution", "command-execution", "filesystem-write"),
            CapabilityReport(
                {
                    "filesystem-write": "unsupported",
                    "test-execution": "unverified",
                }
            ),
        )

        self.assertEqual(
            pause.recommendations,
            (
                (
                    "command-execution",
                    "report and verify capability support: command-execution",
                ),
                (
                    "filesystem-write",
                    "provide supported capability: filesystem-write",
                ),
                (
                    "test-execution",
                    "manually verify support or provide capability: test-execution",
                ),
            ),
        )


if __name__ == "__main__":
    unittest.main()
