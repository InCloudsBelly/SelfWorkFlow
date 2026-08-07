from dataclasses import FrozenInstanceError
import inspect
import itertools
import unittest


class ClassificationTests(unittest.TestCase):
    def test_classification_domain_strings_require_exact_str(self):
        from selfworkflow.classifier import classify_task
        from selfworkflow.model import Complexity, Risk, TaskClassification

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

        accepted = classify_task(Complexity.C1, Risk.R1)
        self.assertEqual(
            (accepted.complexity, accepted.risk),
            (Complexity.C1, Risk.R1),
        )

        cases = (
            lambda: classify_task(HostileString("C1"), "R1"),
            lambda: classify_task("C1", HostileString("R1")),
            lambda: classify_task(
                "C1",
                "R1",
                global_minimum_complexity=HostileString("C0"),
            ),
            lambda: TaskClassification(
                "C1",
                "R1",
                [HostileString("TOP-SECRET-REASON")],
            ),
        )
        for index, call in enumerate(cases):
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
                self.assertEqual(str(caught_error), "classification-input-invalid")
                self.assertEqual(HostileString.calls, 0)
                self.assertNotIn("TOP-SECRET", str(caught_error))

    def test_classification_domain_accepts_c0_r0_through_c3_r3_only(self):
        try:
            from selfworkflow.classifier import classify_task
            from selfworkflow.model import Complexity, Risk
        except ImportError:
            self.fail("classification domain behavior is not implemented")

        for complexity, risk in itertools.product(
            ("C0", "C1", "C2", "C3"),
            ("R0", "R1", "R2", "R3"),
        ):
            with self.subTest(complexity=complexity, risk=risk):
                classification = classify_task(complexity, risk)
                self.assertEqual(classification.complexity, Complexity(complexity))
                self.assertEqual(classification.risk, Risk(risk))

        with self.assertRaises(ValueError):
            classify_task("C4", "R0")
        with self.assertRaises(ValueError):
            classify_task("C0", "R-low")
        with self.assertRaises(FrozenInstanceError):
            classification.complexity = Complexity.C0

    def test_requires_full_design_when_either_dimension_is_at_least_two(self):
        from selfworkflow.classifier import classify_task

        for complexity_index, risk_index in itertools.product(range(4), repeat=2):
            with self.subTest(
                complexity=complexity_index,
                risk=risk_index,
            ):
                classification = classify_task(
                    f"C{complexity_index}",
                    f"R{risk_index}",
                )
                self.assertEqual(
                    getattr(classification, "requires_full_design", None),
                    complexity_index >= 2 or risk_index >= 2,
                )

    def test_suggests_grill_me_only_for_level_three_or_c2_r2(self):
        from selfworkflow.classifier import classify_task

        for complexity_index, risk_index in itertools.product(range(4), repeat=2):
            with self.subTest(
                complexity=complexity_index,
                risk=risk_index,
            ):
                classification = classify_task(
                    f"C{complexity_index}",
                    f"R{risk_index}",
                )
                expected = (
                    complexity_index >= 3
                    or risk_index >= 3
                    or (complexity_index == 2 and risk_index == 2)
                )
                self.assertEqual(
                    getattr(classification, "suggest_grill_me", None),
                    expected,
                )

    def test_ambiguity_upgrades_both_dimensions_and_records_capped_reasons(self):
        from selfworkflow.classifier import classify_task
        from selfworkflow.model import Complexity, Risk

        self.assertIn("ambiguity", inspect.signature(classify_task).parameters)

        upgraded = classify_task("C1", "R2", ambiguity=True)
        self.assertEqual((upgraded.complexity, upgraded.risk), (Complexity.C2, Risk.R3))
        self.assertEqual(
            upgraded.reasons,
            (
                "ambiguity upgraded complexity from C1 to C2",
                "ambiguity upgraded risk from R2 to R3",
            ),
        )

        capped = classify_task("C3", "R3", ambiguity=True)
        self.assertEqual((capped.complexity, capped.risk), (Complexity.C3, Risk.R3))
        self.assertEqual(
            capped.reasons,
            (
                "ambiguity kept complexity at C3 (maximum)",
                "ambiguity kept risk at R3 (maximum)",
            ),
        )

    def test_project_minimum_can_raise_but_not_lower_global_minimums(self):
        from selfworkflow.classifier import classify_task
        from selfworkflow.model import Complexity, Risk

        parameters = inspect.signature(classify_task).parameters
        self.assertIn("project_minimum_complexity", parameters)

        classification = classify_task(
            "C1",
            "R1",
            global_minimum_complexity="C2",
            global_minimum_risk="R2",
            project_minimum_complexity="C0",
            project_minimum_risk="R3",
        )

        self.assertEqual(
            (classification.complexity, classification.risk),
            (Complexity.C2, Risk.R3),
        )
        self.assertEqual(
            classification.reasons,
            (
                "project minimum complexity C0 rejected below global minimum C2",
                "project minimum risk raised global minimum from R2 to R3",
                "minimum upgraded complexity from C1 to C2",
                "minimum upgraded risk from R1 to R3",
            ),
        )

    def test_user_override_can_upgrade_but_not_cross_global_minimums(self):
        from selfworkflow.classifier import classify_task
        from selfworkflow.model import Complexity, Risk

        parameters = inspect.signature(classify_task).parameters
        self.assertIn("user_complexity", parameters)

        classification = classify_task(
            "C2",
            "R1",
            global_minimum_complexity="C1",
            global_minimum_risk="R2",
            user_complexity="C0",
            user_risk="R3",
        )

        self.assertEqual(
            (classification.complexity, classification.risk),
            (Complexity.C2, Risk.R3),
        )
        self.assertEqual(
            classification.reasons,
            (
                "minimum upgraded risk from R1 to R2",
                "user complexity C0 rejected below minimum C1",
                "user upgraded risk from R2 to R3",
            ),
        )

    def test_classification_exposes_contract_threshold_names(self):
        from selfworkflow.classifier import classify_task

        classification = classify_task("C2", "R2")

        self.assertIs(getattr(classification, "requiresFullDesign", None), True)
        self.assertIs(getattr(classification, "suggestGrillMe", None), True)

    def test_task_classification_normalizes_direct_construction_immutably(self):
        from selfworkflow.model import Complexity, Risk, TaskClassification

        try:
            classification = TaskClassification("C1", "R2", ["explicit reason"])
        except Exception as error:
            self.fail(f"direct classification normalization is missing: {type(error).__name__}")

        self.assertEqual(classification.complexity, Complexity.C1)
        self.assertEqual(classification.risk, Risk.R2)
        self.assertEqual(classification.reasons, ("explicit reason",))
        with self.assertRaises(ValueError):
            TaskClassification("C9", "R0")

    def test_task_classification_copies_string_reasons_and_rejects_nested_values(self):
        from selfworkflow.model import TaskClassification

        source_reasons = ["explicit reason"]
        classification = TaskClassification("C1", "R1", source_reasons)
        source_reasons.append("changed")
        self.assertEqual(classification.reasons, ("explicit reason",))

        for invalid_reasons in (["valid", ["hidden-input"]], "hidden-input", [7]):
            with self.subTest(invalid_reasons=invalid_reasons):
                try:
                    TaskClassification("C1", "R1", invalid_reasons)
                except Exception as error:
                    self.assertIsInstance(error, ValueError)
                    self.assertEqual(str(error), "classification-input-invalid")
                    self.assertNotIn("hidden-input", str(error))
                else:
                    self.fail("invalid classification reasons were accepted")

    def test_ambiguity_rejects_non_boolean_values_with_fixed_error(self):
        from selfworkflow.classifier import classify_task

        for invalid_ambiguity in ("false", 0, None):
            with self.subTest(invalid_ambiguity=invalid_ambiguity):
                try:
                    classify_task("C0", "R0", ambiguity=invalid_ambiguity)
                except Exception as error:
                    self.assertIsInstance(error, ValueError)
                    self.assertEqual(str(error), "classification-input-invalid")
                    self.assertNotIn("false", str(error).lower())
                else:
                    self.fail("non-boolean ambiguity was accepted")

    def test_all_classification_enums_reject_invalid_values_without_echo(self):
        from selfworkflow.classifier import classify_task
        from selfworkflow.model import TaskClassification

        hidden_input = "hidden-classification-input"
        invalid_calls = (
            lambda: classify_task(hidden_input, "R0"),
            lambda: classify_task("C0", hidden_input),
            lambda: classify_task(
                "C0", "R0", global_minimum_complexity=hidden_input
            ),
            lambda: classify_task("C0", "R0", global_minimum_risk=hidden_input),
            lambda: classify_task(
                "C0", "R0", project_minimum_complexity=hidden_input
            ),
            lambda: classify_task("C0", "R0", project_minimum_risk=hidden_input),
            lambda: classify_task("C0", "R0", user_complexity=hidden_input),
            lambda: classify_task("C0", "R0", user_risk=hidden_input),
            lambda: TaskClassification(hidden_input, "R0"),
        )

        for invalid_call in invalid_calls:
            with self.subTest(invalid_call=invalid_call):
                try:
                    invalid_call()
                except Exception as error:
                    self.assertIsInstance(error, ValueError)
                    self.assertEqual(str(error), "classification-input-invalid")
                    self.assertNotIn(hidden_input, str(error))
                else:
                    self.fail("invalid classification enum was accepted")

    def test_user_override_cannot_lower_result_above_global_minimum(self):
        from selfworkflow.classifier import classify_task

        classification = classify_task(
            "C3",
            "R3",
            global_minimum_complexity="C1",
            global_minimum_risk="R1",
            user_complexity="C2",
            user_risk="R2",
        )

        self.assertEqual(classification.complexity.value, "C3")
        self.assertEqual(classification.risk.value, "R3")
        self.assertEqual(
            classification.reasons,
            (
                "user complexity C2 rejected downgrade from C3",
                "user risk R2 rejected downgrade from R3",
            ),
        )


if __name__ == "__main__":
    unittest.main()
