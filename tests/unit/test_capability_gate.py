from dataclasses import FrozenInstanceError
import traceback
import unittest


def _assert_redacted_workflow_error(
    test_case,
    call,
    expected_code,
    *sensitive_fragments,
):
    try:
        call()
    except Exception as error:
        test_case.assertIsInstance(error, ValueError)
        test_case.assertEqual(str(error), expected_code)
        test_case.assertIsNone(error.__cause__)
        test_case.assertIs(error.__suppress_context__, True)
        formatted = "".join(traceback.format_exception(error))
        for fragment in sensitive_fragments:
            test_case.assertNotIn(fragment, formatted)
    else:
        test_case.fail("materialization failure was accepted")


class CapabilityGateTests(unittest.TestCase):
    def test_one_time_alternative_has_non_overrideable_typed_policy(self):
        import selfworkflow.model as model

        self.assertTrue(
            hasattr(model, "OneTimeAlternative")
            and hasattr(model, "OneTimeAlternativeAction"),
            "typed one-time alternative policy is not implemented",
        )
        alternative = model.OneTimeAlternative(
            "filesystem-write",
            model.OneTimeAlternativeAction.MANUAL_ALTERNATIVE,
        )

        self.assertEqual(alternative.capability, "filesystem-write")
        self.assertIs(
            alternative.action,
            model.OneTimeAlternativeAction.MANUAL_ALTERNATIVE,
        )
        self.assertIs(alternative.requires_explicit_user_authorization, True)
        self.assertIs(alternative.allows_automatic_downgrade, False)
        for field_name, forged_value in (
            ("requires_explicit_user_authorization", False),
            ("allows_automatic_downgrade", True),
        ):
            with self.subTest(field=field_name, operation="construct"):
                with self.assertRaises(TypeError):
                    model.OneTimeAlternative(
                        "filesystem-write",
                        model.OneTimeAlternativeAction.MANUAL_ALTERNATIVE,
                        **{field_name: forged_value},
                    )
            with self.subTest(field=field_name, operation="mutate"):
                with self.assertRaises(FrozenInstanceError):
                    setattr(alternative, field_name, forged_value)

    def test_one_time_alternative_rejects_arbitrary_actions(self):
        from selfworkflow.model import OneTimeAlternative

        for action in ("manual-alternative", "automatic downgrade is fine"):
            with self.subTest(action=action):
                _assert_redacted_workflow_error(
                    self,
                    lambda: OneTimeAlternative("filesystem-write", action),
                    "one-time-alternative-invalid",
                    "automatic downgrade",
                )

    def test_one_time_alternative_requires_nonempty_exact_capability_name(self):
        from selfworkflow.model import OneTimeAlternative, OneTimeAlternativeAction

        class HostileString(str):
            pass

        for capability in ("", 7, HostileString("TOP-SECRET-CAPABILITY")):
            with self.subTest(capability_type=type(capability).__name__):
                _assert_redacted_workflow_error(
                    self,
                    lambda: OneTimeAlternative(
                        capability,
                        OneTimeAlternativeAction.MANUAL_VERIFY,
                    ),
                    "one-time-alternative-invalid",
                    "TOP-SECRET-CAPABILITY",
                )

    def test_one_time_alternative_derives_instruction_from_typed_action(self):
        from selfworkflow.model import OneTimeAlternative, OneTimeAlternativeAction

        expected = {
            OneTimeAlternativeAction.MANUAL_ALTERNATIVE: (
                "request explicit user authorization for a one-time manual "
                "alternative: filesystem-write"
            ),
            OneTimeAlternativeAction.MANUAL_VERIFY: (
                "request explicit user authorization to manually verify "
                "capability support: filesystem-write"
            ),
            OneTimeAlternativeAction.MANUAL_REPORT_AND_VERIFY: (
                "request explicit user authorization to manually report and verify "
                "capability support: filesystem-write"
            ),
        }

        for action, instruction in expected.items():
            with self.subTest(action=action.value):
                alternative = OneTimeAlternative("filesystem-write", action)
                self.assertEqual(
                    getattr(alternative, "instruction", None),
                    instruction,
                )

    def test_model_centralizes_both_non_waivable_capability_boundaries(self):
        import selfworkflow.model as model

        self.assertTrue(
            hasattr(model, "ONE_TIME_ALTERNATIVE_AUTHORIZATION_BOUNDARY")
            and hasattr(model, "MANDATORY_CAPABILITY_BOUNDARIES"),
            "mandatory capability boundaries are not centralized",
        )
        self.assertEqual(
            model.MANDATORY_CAPABILITY_BOUNDARIES,
            (
                "one-time alternatives require explicit user authorization",
                "required capability cannot be treated as supported without evidence",
            ),
        )

    def test_pause_result_requires_both_mandatory_capability_boundaries(self):
        from selfworkflow.model import (
            MANDATORY_CAPABILITY_BOUNDARIES,
            OneTimeAlternative,
            OneTimeAlternativeAction,
            PauseResult,
        )

        for omitted in MANDATORY_CAPABILITY_BOUNDARIES:
            with self.subTest(omitted=omitted):
                with self.assertRaises(ValueError) as raised:
                    PauseResult(
                        ("filesystem-write",),
                        (("filesystem-write", "persist workflow files"),),
                        (("filesystem-write", "capability is unsupported"),),
                        (("filesystem-write", "provide the capability"),),
                        (
                            OneTimeAlternative(
                                "filesystem-write",
                                OneTimeAlternativeAction.MANUAL_ALTERNATIVE,
                            ),
                        ),
                        tuple(
                            boundary
                            for boundary in MANDATORY_CAPABILITY_BOUNDARIES
                            if boundary != omitted
                        ),
                    )
                self.assertEqual(str(raised.exception), "pause-result-invalid")

    def test_pause_result_rejects_noncanonical_complete_contract(self):
        from selfworkflow.model import (
            MANDATORY_CAPABILITY_BOUNDARIES,
            OneTimeAlternative,
            OneTimeAlternativeAction,
            PauseResult,
        )

        missing = ("filesystem-read", "test-execution")
        valid = {
            "missing_capabilities": missing,
            "purposes": (
                ("filesystem-read", "read task inputs"),
                ("test-execution", "run required tests"),
            ),
            "reasons": (
                ("filesystem-read", "capability is unsupported"),
                ("test-execution", "capability support is unverified"),
            ),
            "recommendations": (
                ("filesystem-read", "provide the capability"),
                ("test-execution", "verify the capability"),
            ),
            "one_time_alternatives": (
                OneTimeAlternative(
                    "filesystem-read",
                    OneTimeAlternativeAction.MANUAL_ALTERNATIVE,
                ),
                OneTimeAlternative(
                    "test-execution",
                    OneTimeAlternativeAction.MANUAL_VERIFY,
                ),
            ),
            "non_waivable_boundaries": MANDATORY_CAPABILITY_BOUNDARIES,
        }
        self.assertEqual(
            PauseResult(**valid).one_time_alternatives,
            valid["one_time_alternatives"],
        )

        invalid_cases = [
            (
                "empty missing collection",
                {
                    "missing_capabilities": (),
                    "purposes": (),
                    "reasons": (),
                    "recommendations": (),
                    "one_time_alternatives": (),
                },
            ),
            (
                "empty missing value",
                {
                    "missing_capabilities": ("",),
                    "purposes": (("", "purpose"),),
                    "reasons": (("", "reason"),),
                    "recommendations": (("", "recommendation"),),
                    "one_time_alternatives": (),
                },
            ),
            (
                "duplicate missing value",
                {"missing_capabilities": ("filesystem-read", "filesystem-read")},
            ),
            (
                "unsorted missing values",
                {
                    "missing_capabilities": tuple(reversed(missing)),
                    "purposes": tuple(reversed(valid["purposes"])),
                    "reasons": tuple(reversed(valid["reasons"])),
                    "recommendations": tuple(reversed(valid["recommendations"])),
                    "one_time_alternatives": tuple(
                        reversed(valid["one_time_alternatives"])
                    ),
                },
            ),
        ]
        for field_name in (
            "purposes",
            "reasons",
            "recommendations",
        ):
            pairs = valid[field_name]
            invalid_cases.extend(
                (
                    (f"{field_name} missing key", {field_name: pairs[:-1]}),
                    (
                        f"{field_name} extra key",
                        {field_name: pairs + (("user-confirmation", "extra"),)},
                    ),
                    (
                        f"{field_name} duplicate key",
                        {field_name: pairs + (pairs[0],)},
                    ),
                    (
                        f"{field_name} unsorted",
                        {field_name: tuple(reversed(pairs))},
                    ),
                    (
                        f"{field_name} empty value",
                        {field_name: ((pairs[0][0], ""), pairs[1])},
                    ),
                )
            )
        alternatives = valid["one_time_alternatives"]
        invalid_cases.extend(
            (
                (
                    "one_time_alternatives missing capability",
                    {"one_time_alternatives": alternatives[:-1]},
                ),
                (
                    "one_time_alternatives extra capability",
                    {
                        "one_time_alternatives": alternatives
                        + (
                            OneTimeAlternative(
                                "user-confirmation",
                                OneTimeAlternativeAction.MANUAL_VERIFY,
                            ),
                        )
                    },
                ),
                (
                    "one_time_alternatives duplicate capability",
                    {"one_time_alternatives": alternatives + (alternatives[0],)},
                ),
                (
                    "one_time_alternatives unsorted",
                    {"one_time_alternatives": tuple(reversed(alternatives))},
                ),
            )
        )
        invalid_cases.extend(
            (
                ("empty boundaries", {"non_waivable_boundaries": ()}),
                ("empty boundary", {"non_waivable_boundaries": ("",)}),
                (
                    "duplicate boundary",
                    {
                        "non_waivable_boundaries": (
                            valid["non_waivable_boundaries"][0],
                            valid["non_waivable_boundaries"][0],
                        )
                    },
                ),
                (
                    "unsorted boundaries",
                    {
                        "non_waivable_boundaries": tuple(
                            reversed(valid["non_waivable_boundaries"])
                        )
                    },
                ),
                (
                    "missing evidence boundary",
                    {
                        "non_waivable_boundaries": (
                            MANDATORY_CAPABILITY_BOUNDARIES[0],
                        )
                    },
                ),
            )
        )

        for label, updates in invalid_cases:
            with self.subTest(case=label):
                arguments = dict(valid)
                arguments.update(updates)
                with self.assertRaises(ValueError) as raised:
                    PauseResult(**arguments)
                self.assertEqual(str(raised.exception), "pause-result-invalid")

    def test_capability_domain_strings_require_exact_str(self):
        from collections.abc import Mapping

        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import CapabilityReport, CapabilityState, PauseResult

        class HostileString(str):
            calls = 0

            def _explode(self):
                type(self).calls += 1
                raise ValueError("TOP-SECRET-STRING-METHOD")

            def __hash__(self):
                return self._explode()

            def __eq__(self, other):
                return self._explode()

            def __iter__(self):
                return self._explode()

            def __lt__(self, other):
                return self._explode()

            def __len__(self):
                return self._explode()

        class SinglePairMapping(Mapping):
            def __init__(self, key, value):
                self.key = key
                self.value = value

            def __getitem__(self, key):
                return self.value

            def __iter__(self):
                return iter(("filesystem-read",))

            def __len__(self):
                return 1

            def items(self):
                return ((self.key, self.value),)

        valid_report = CapabilityReport(
            [("filesystem-read", CapabilityState.SUPPORTED)]
        )
        cases = (
            (
                "pause-result-invalid",
                lambda: PauseResult(
                    [HostileString("filesystem-read")], (), (), ()
                ),
            ),
            (
                "pause-result-invalid",
                lambda: PauseResult(
                    (), [(HostileString("filesystem-read"), "purpose")], (), ()
                ),
            ),
            (
                "pause-result-invalid",
                lambda: PauseResult(
                    (), [("filesystem-read", HostileString("purpose"))], (), ()
                ),
            ),
            (
                "pause-result-invalid",
                lambda: PauseResult(
                    (), (), [(HostileString("filesystem-read"), "reason")], ()
                ),
            ),
            (
                "pause-result-invalid",
                lambda: PauseResult(
                    (), (), [("filesystem-read", HostileString("reason"))], ()
                ),
            ),
            (
                "pause-result-invalid",
                lambda: PauseResult(
                    (), (), (), [(HostileString("filesystem-read"), "action")]
                ),
            ),
            (
                "pause-result-invalid",
                lambda: PauseResult(
                    (), (), (), [("filesystem-read", HostileString("action"))]
                ),
            ),
            (
                "pause-result-invalid",
                lambda: PauseResult(
                    ("filesystem-read",),
                    (("filesystem-read", "purpose"),),
                    (("filesystem-read", "reason"),),
                    (("filesystem-read", "recommendation"),),
                    (("filesystem-read", HostileString("alternative")),),
                    (
                        "one-time alternatives require explicit user authorization",
                        "required capability cannot be treated as supported without evidence",
                    ),
                ),
            ),
            (
                "pause-result-invalid",
                lambda: PauseResult(
                    ("filesystem-read",),
                    (("filesystem-read", "purpose"),),
                    (("filesystem-read", "reason"),),
                    (("filesystem-read", "recommendation"),),
                    (("filesystem-read", "alternative"),),
                    (
                        HostileString(
                            "required capability cannot be treated as supported "
                            "without evidence"
                        ),
                    ),
                ),
            ),
            (
                "capability-report-invalid",
                lambda: CapabilityReport(
                    [(HostileString("filesystem-read"), "supported")]
                ),
            ),
            (
                "capability-report-invalid",
                lambda: CapabilityReport(
                    [("filesystem-read", HostileString("supported"))]
                ),
            ),
            (
                "capability-report-invalid",
                lambda: valid_report.state_for(
                    HostileString("filesystem-read")
                ),
            ),
            (
                "capability-gate-input-invalid",
                lambda: check_capabilities(
                    [HostileString("filesystem-read")], valid_report
                ),
            ),
            (
                "capability-gate-input-invalid",
                lambda: check_capabilities(
                    ["filesystem-read"],
                    valid_report,
                    purposes=SinglePairMapping(
                        HostileString("filesystem-read"),
                        "purpose",
                    ),
                ),
            ),
            (
                "capability-gate-input-invalid",
                lambda: check_capabilities(
                    ["filesystem-read"],
                    valid_report,
                    purposes=SinglePairMapping(
                        "filesystem-read",
                        HostileString("purpose"),
                    ),
                ),
            ),
        )

        for index, (expected_code, call) in enumerate(cases):
            with self.subTest(boundary=index):
                HostileString.calls = 0
                caught_error = None
                try:
                    call()
                except Exception as error:
                    caught_error = error
                else:
                    self.fail("str subclass was accepted")

                self.assertIsInstance(caught_error, ValueError)
                self.assertEqual(str(caught_error), expected_code)
                self.assertEqual(HostileString.calls, 0)
                self.assertNotIn("TOP-SECRET", str(caught_error))

    def test_public_ordered_inputs_reject_set_and_frozenset(self):
        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import (
            CapabilityReport,
            MANDATORY_CAPABILITY_BOUNDARIES,
            OneTimeAlternative,
            OneTimeAlternativeAction,
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
                    "pause one-time alternatives",
                    "pause-result-invalid",
                    lambda: PauseResult(
                        ("filesystem-read",),
                        (("filesystem-read", "read task inputs"),),
                        (("filesystem-read", "capability is unsupported"),),
                        (("filesystem-read", "provide the capability"),),
                        unordered_type(
                            [
                                OneTimeAlternative(
                                    "filesystem-read",
                                    OneTimeAlternativeAction.MANUAL_ALTERNATIVE,
                                )
                            ]
                        ),
                        MANDATORY_CAPABILITY_BOUNDARIES,
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
                    _assert_redacted_workflow_error(
                        self,
                        call,
                        expected_code,
                        "TOP-SECRET",
                    )

    def test_pause_result_redacts_iteration_failures_for_all_collections(self):
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
            lambda: PauseResult(
                (),
                (),
                (),
                (),
                ExplodingIterable(
                    ("filesystem-read", "request explicit authorization")
                ),
            ),
            lambda: PauseResult(
                (),
                (),
                (),
                (),
                (),
                ExplodingIterable(
                    "required capability cannot be treated as supported "
                    "without evidence"
                ),
            ),
        )

        for index, call in enumerate(cases):
            with self.subTest(field_index=index):
                _assert_redacted_workflow_error(
                    self,
                    call,
                    "pause-result-invalid",
                    "TOP-SECRET",
                )

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
                _assert_redacted_workflow_error(
                    self,
                    call,
                    expected_code,
                    "TOP-SECRET",
                )

    def test_pause_pair_mappings_are_normalized_in_lexical_key_order(self):
        from selfworkflow.model import (
            MANDATORY_CAPABILITY_BOUNDARIES,
            OneTimeAlternative,
            OneTimeAlternativeAction,
            PauseResult,
        )

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
        missing = ("filesystem-read", "test-execution")
        alternatives = (
            OneTimeAlternative(
                "filesystem-read",
                OneTimeAlternativeAction.MANUAL_ALTERNATIVE,
            ),
            OneTimeAlternative(
                "test-execution",
                OneTimeAlternativeAction.MANUAL_VERIFY,
            ),
        )

        for field_index in (1, 2, 3):
            descending_arguments = [
                missing,
                ascending,
                ascending,
                ascending,
                alternatives,
                MANDATORY_CAPABILITY_BOUNDARIES,
            ]
            ascending_arguments = list(descending_arguments)
            descending_arguments[field_index] = descending
            ascending_arguments[field_index] = ascending

            with self.subTest(field_index=field_index):
                descending_pause = PauseResult(*descending_arguments)
                ascending_pause = PauseResult(*ascending_arguments)
                field_name = (
                    "purposes",
                    "reasons",
                    "recommendations",
                )[
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
                _assert_redacted_workflow_error(
                    self,
                    call,
                    expected_code,
                    "TOP-SECRET",
                )

    def test_mapping_items_call_failures_are_redacted(self):
        from collections.abc import Mapping

        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import CapabilityReport, PauseResult

        class ExplodingItemsCallMapping(Mapping):
            def __getitem__(self, key):
                raise KeyError(key)

            def __iter__(self):
                return iter(())

            def __len__(self):
                return 0

            def items(self):
                raise ValueError("TOP-SECRET-MAPPING-CALL")

        cases = (
            (
                "pause pairs",
                "pause-result-invalid",
                lambda: PauseResult(
                    (), ExplodingItemsCallMapping(), (), ()
                ),
            ),
            (
                "capability report entries",
                "capability-report-invalid",
                lambda: CapabilityReport(ExplodingItemsCallMapping()),
            ),
            (
                "capability gate purposes",
                "capability-gate-input-invalid",
                lambda: check_capabilities(
                    [],
                    CapabilityReport({}),
                    purposes=ExplodingItemsCallMapping(),
                ),
            ),
        )

        for boundary, expected_code, call in cases:
            with self.subTest(boundary=boundary):
                _assert_redacted_workflow_error(
                    self,
                    call,
                    expected_code,
                    "TOP-SECRET-MAPPING-CALL",
                )

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
            lambda: PauseResult((), (), (), (), AbortingIterable(), ()),
            lambda: PauseResult((), (), (), (), (), AbortingIterable()),
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
        from selfworkflow.model import (
            OneTimeAlternative,
            OneTimeAlternativeAction,
            PauseResult,
        )

        missing = ["filesystem-write"]
        purposes = {"filesystem-write": "persist workflow files"}
        reasons = [["filesystem-write", "capability is unsupported"]]
        recommendations = [
            ["filesystem-write", "provide supported capability: filesystem-write"]
        ]
        one_time_alternatives = [
            OneTimeAlternative(
                "filesystem-write",
                OneTimeAlternativeAction.MANUAL_ALTERNATIVE,
            )
        ]
        non_waivable_boundaries = [
            "one-time alternatives require explicit user authorization",
            "required capability cannot be treated as supported without evidence",
        ]

        pause = PauseResult(
            missing,
            purposes,
            reasons,
            recommendations,
            one_time_alternatives,
            non_waivable_boundaries,
        )
        missing.append("test-execution")
        purposes["filesystem-write"] = "changed"
        reasons[0][1] = "changed"
        recommendations[0][1] = "changed"
        one_time_alternatives.append(
            OneTimeAlternative(
                "test-execution",
                OneTimeAlternativeAction.MANUAL_VERIFY,
            )
        )
        non_waivable_boundaries.append("changed")

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
        self.assertEqual(
            pause.one_time_alternatives,
            (
                OneTimeAlternative(
                    "filesystem-write",
                    OneTimeAlternativeAction.MANUAL_ALTERNATIVE,
                ),
            ),
        )
        self.assertEqual(
            pause.one_time_alternatives[0].instruction,
            "request explicit user authorization for a one-time manual "
            "alternative: filesystem-write",
        )
        self.assertEqual(
            pause.non_waivable_boundaries,
            (
                "one-time alternatives require explicit user authorization",
                "required capability cannot be treated as supported without evidence",
            ),
        )

    def test_pause_result_rejects_untyped_one_time_alternatives(self):
        from selfworkflow.model import PauseResult

        _assert_redacted_workflow_error(
            self,
            lambda: PauseResult(
                ("filesystem-write",),
                (("filesystem-write", "persist workflow files"),),
                (("filesystem-write", "capability is unsupported"),),
                (("filesystem-write", "provide the capability"),),
                (("filesystem-write", "automatic downgrade is fine"),),
                (
                    "one-time alternatives require explicit user authorization",
                    "required capability cannot be treated as supported without evidence",
                ),
            ),
            "pause-result-invalid",
            "automatic downgrade",
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
        self.assertEqual(
            pause.one_time_alternatives,
            (
                model.OneTimeAlternative(
                    "filesystem-write",
                    model.OneTimeAlternativeAction.MANUAL_ALTERNATIVE,
                ),
            ),
        )
        self.assertEqual(
            pause.one_time_alternatives[0].instruction,
            "request explicit user authorization for a one-time manual "
            "alternative: filesystem-write",
        )
        self.assertIs(
            pause.one_time_alternatives[0].requires_explicit_user_authorization,
            True,
        )
        self.assertIs(
            pause.one_time_alternatives[0].allows_automatic_downgrade,
            False,
        )
        self.assertEqual(
            pause.non_waivable_boundaries,
            model.MANDATORY_CAPABILITY_BOUNDARIES,
        )
        generated_cases = (
            (
                model.CapabilityReport({"filesystem-write": "unsupported"}),
                model.OneTimeAlternativeAction.MANUAL_ALTERNATIVE,
                "request explicit user authorization for a one-time manual "
                "alternative: filesystem-write",
            ),
            (
                model.CapabilityReport({"filesystem-write": "unverified"}),
                model.OneTimeAlternativeAction.MANUAL_VERIFY,
                "request explicit user authorization to manually verify "
                "capability support: filesystem-write",
            ),
            (
                model.CapabilityReport({}),
                model.OneTimeAlternativeAction.MANUAL_REPORT_AND_VERIFY,
                "request explicit user authorization to manually report and verify "
                "capability support: filesystem-write",
            ),
        )
        for gap_report, expected_action, expected_instruction in generated_cases:
            with self.subTest(action=expected_action.value):
                generated = classifier.check_capabilities(
                    ["filesystem-write"],
                    gap_report,
                )
                alternative = generated.one_time_alternatives[0]
                self.assertIs(alternative.action, expected_action)
                self.assertEqual(alternative.instruction, expected_instruction)
                self.assertIs(
                    alternative.requires_explicit_user_authorization,
                    True,
                )
                self.assertIs(alternative.allows_automatic_downgrade, False)
        self.assertTrue(pause.recommendations)
        with self.assertRaises(FrozenInstanceError):
            pause.status = model.ExecutionStatus.ACTIVE

    def test_only_supported_required_capability_passes_the_gate(self):
        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import (
            CapabilityReport,
            MANDATORY_CAPABILITY_BOUNDARIES,
            OneTimeAlternative,
            OneTimeAlternativeAction,
        )

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
        self.assertEqual(
            unverified_pause.one_time_alternatives,
            (
                OneTimeAlternative(
                    "test-execution",
                    OneTimeAlternativeAction.MANUAL_VERIFY,
                ),
            ),
        )
        self.assertEqual(
            unverified_pause.one_time_alternatives[0].instruction,
            "request explicit user authorization to manually verify "
            "capability support: test-execution",
        )
        self.assertEqual(
            unverified_pause.non_waivable_boundaries,
            MANDATORY_CAPABILITY_BOUNDARIES,
        )
        self.assertIn("manually verify", unverified_pause.recommendations[0][1])

        supported_result = check_capabilities(
            ["test-execution"],
            CapabilityReport({"test-execution": "supported"}),
        )
        self.assertIsNone(supported_result)

    def test_unreported_required_capability_pauses_instead_of_degrading(self):
        from selfworkflow.classifier import check_capabilities
        from selfworkflow.model import (
            CapabilityReport,
            MANDATORY_CAPABILITY_BOUNDARIES,
            OneTimeAlternative,
            OneTimeAlternativeAction,
        )

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
        self.assertEqual(
            pause.one_time_alternatives,
            (
                OneTimeAlternative(
                    "filesystem-write",
                    OneTimeAlternativeAction.MANUAL_REPORT_AND_VERIFY,
                ),
            ),
        )
        self.assertEqual(
            pause.one_time_alternatives[0].instruction,
            "request explicit user authorization to manually report and verify "
            "capability support: filesystem-write",
        )
        self.assertEqual(
            pause.non_waivable_boundaries,
            MANDATORY_CAPABILITY_BOUNDARIES,
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
