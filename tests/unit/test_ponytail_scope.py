import unittest

from selfworkflow.ponytail_scope import select_ponytail_route


class PonytailScopeTests(unittest.TestCase):
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
