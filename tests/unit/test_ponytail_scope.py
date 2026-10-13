import unittest

from selfworkflow.ponytail_scope import select_ponytail_route


class PonytailScopeTests(unittest.TestCase):
    def test_explicit_debt_is_one_shot_without_coding_skill(self):
        for operation in ("analyze", "review", "implement", "debug"):
            for mode in ("lite", "full", "ultra"):
                with self.subTest(operation=operation, mode=mode):
                    route = select_ponytail_route(
                        operation, explicit_skill="ponytail-debt", mode=mode,
                    )
                    self.assertTrue(route.enabled)
                    self.assertEqual(route.skill_ids, ("ponytail-debt",))
                    self.assertEqual(route.module_ids, ("ponytail-debt",))
                    self.assertEqual(route.reason, "explicit-debt")
                    self.assertEqual(route.as_dict()["selectedModuleIds"], ["ponytail-debt"])
        self.assertFalse(select_ponytail_route("analyze").enabled)
        self.assertEqual(select_ponytail_route("implement").skill_ids, ("ponytail",))

    def test_debt_is_never_implicit_and_preserves_route_guards(self):
        for operation in ("analyze", "implement", "review"):
            route = select_ponytail_route(
                operation, semantic_terms=("code", "ponytail-debt", "shortcut", "debt"),
            )
            self.assertNotIn("ponytail-debt", route.skill_ids)
        off = select_ponytail_route("analyze", explicit_skill="ponytail-debt", mode="off")
        self.assertFalse(off.enabled)
        self.assertEqual(off.skill_ids, ())
        self.assertEqual(off.reason, "explicitly-off")
        with self.assertRaisesRegex(ValueError, "ponytail-explicit-operation-invalid"):
            select_ponytail_route("document", explicit_skill="ponytail-debt")
        for operation in ("design", "plan", "verify"):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError, "ponytail-explicit-operation-invalid"):
                    select_ponytail_route(operation, explicit_skill="ponytail-debt")
        with self.assertRaisesRegex(ValueError, "ponytail-skill-invalid"):
            select_ponytail_route("analyze", explicit_skill="ponytail-gain")

    def test_implementation_and_debug_are_code_scoped_by_operation(self):
        for operation in ("implement", "debug"):
            with self.subTest(operation=operation):
                route = select_ponytail_route(operation)
                self.assertEqual(route.skill_ids, ("ponytail",))
                self.assertEqual(route.reason, "code-task")

    def test_design_review_and_plan_need_code_signal(self):
        self.assertFalse(select_ponytail_route("design").enabled)
        self.assertFalse(select_ponytail_route("review").enabled)
        self.assertTrue(
            select_ponytail_route("plan", file_extensions=(".cpp",)).enabled
        )
        self.assertTrue(
            select_ponytail_route("review", semantic_terms=("ABI",)).enabled
        )

    def test_non_code_operation_is_not_auto_routed(self):
        route = select_ponytail_route("document", semantic_terms=("code",))
        self.assertEqual(route, route.__class__(False, (), "full", "non-code-operation"))

    def test_ambiguous_terms_do_not_enable_signal_only_operations(self):
        for term in ("source", "test", "interface", "module", "build"):
            with self.subTest(term=term):
                self.assertFalse(
                    select_ponytail_route("design", semantic_terms=(term,)).enabled
                )

    def test_explicit_review_and_audit_are_additive_and_session_scoped(self):
        review = select_ponytail_route(
            "review", explicit_skill="ponytail-review", semantic_terms=("code",)
        )
        audit = select_ponytail_route(
            "review", explicit_skill="ponytail-audit", mode="ultra",
            semantic_terms=("code",),
        )
        self.assertEqual(review.skill_ids, ("ponytail", "ponytail-review"))
        self.assertEqual(audit.skill_ids, ("ponytail", "ponytail-audit"))
        self.assertEqual(audit.mode, "ultra")

    def test_explicit_review_and_audit_do_not_bypass_code_scope(self):
        for skill in ("ponytail-review", "ponytail-audit"):
            with self.subTest(skill=skill):
                route = select_ponytail_route("review", explicit_skill=skill)
                self.assertFalse(route.enabled)
                self.assertEqual(route.reason, "no-code-signal")

    def test_modes_match_ponytail_contract_and_off_disables(self):
        for mode in ("lite", "full", "ultra"):
            with self.subTest(mode=mode):
                self.assertTrue(select_ponytail_route("implement", mode=mode).enabled)
        off = select_ponytail_route("implement", mode="off")
        self.assertFalse(off.enabled)
        self.assertEqual(off.reason, "explicitly-off")

    def test_invalid_route_input_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "ponytail-mode-invalid"):
            select_ponytail_route("implement", mode="deep")
        help_route = select_ponytail_route("analyze", explicit_skill="ponytail-help")
        self.assertEqual(help_route.skill_ids, ("ponytail-help",))
        self.assertEqual(help_route.reason, "explicit-help")


if __name__ == "__main__":
    unittest.main()
