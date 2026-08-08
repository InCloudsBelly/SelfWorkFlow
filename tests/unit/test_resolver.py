from copy import deepcopy
import json
from pathlib import Path
import unittest

from selfworkflow.catalog import compile_catalog


class TaskResolverV2Tests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    @classmethod
    def setUpClass(cls):
        cls.catalog = compile_catalog(cls.ROOT / "catalog").content

    @staticmethod
    def _evidence(name, state="supported", suffix="1"):
        return {
            "name": name, "provider": "test-host",
            "subject": {"kind": "host", "id": "fixture", "version": "1", "build": "1", "sourceLock": "sha256:" + suffix * 64},
            "state": state, "observedAt": "2020-01-01T00:00:00Z", "validUntil": "2099-01-01T00:00:00Z",
            "evidenceRef": "fixture:" + name, "evidenceHash": "sha256:" + suffix * 64,
        }

    @classmethod
    def _request(cls, **overrides):
        names = (
            "filesystem-read", "filesystem-write", "skill-discovery",
            "test-execution", "independent-context", "user-confirmation",
        )
        request = {
            "schemaVersion": 2, "operationType": "implement", "complexity": "C1", "risk": "R1",
            "writeTask": True, "ambiguity": False, "explicitModuleIds": [], "projectDefaultModuleIds": [],
            "projectMinimums": {"strength": "Light"},
            "capabilityEvidenceSnapshot": {
                "schemaVersion": 1, "capturedAt": "2020-01-01T00:00:00Z",
                "evidence": [cls._evidence(name) for name in names],
            },
        }
        request.update(overrides)
        return request

    def test_all_32_strength_cells_and_read_only_static_na(self):
        from selfworkflow.resolver import resolve_task

        for write_task in (False, True):
            for c in range(4):
                for r in range(4):
                    expected = "Deep" if c == 3 or r == 3 or (c == 2 and r == 2) else "Full" if c == 2 or r == 2 else "Light"
                    with self.subTest(write=write_task, complexity=c, risk=r):
                        result = resolve_task(
                            self.catalog,
                            self._request(
                                operationType="implement" if write_task else "analyze",
                                complexity=f"C{c}", risk=f"R{r}", writeTask=write_task,
                            ),
                        )
                        self.assertEqual(result["status"], "active")
                        self.assertEqual(result["planGraph"]["strength"], expected)
                        implemented = next(stage for stage in result["planGraph"]["stages"] if stage["stageId"] == "implemented")
                        method = next(slot for slot in implemented["slots"] if slot["slotId"] == "implement.method")
                        self.assertEqual(method["applicability"], "applicable" if write_task else "not-applicable")

    def test_read_only_plan_initial_ledger_accepts_static_skips(self):
        from selfworkflow.ledger import new_ledger, validate_ledger
        from selfworkflow.resolver import resolve_task

        request = self._request(operationType="analyze", writeTask=False)
        result = resolve_task(self.catalog, request)
        plan = result["planGraph"]
        ledger = new_ledger(plan)

        self.assertEqual(result["status"], "active")
        self.assertTrue(validate_ledger(
            ledger, plan, request["capabilityEvidenceSnapshot"]
        )["valid"])

    def test_document_write_routes_implementation_review_and_verify(self):
        from selfworkflow.resolver import resolve_task

        result = resolve_task(
            self.catalog,
            self._request(operationType="document", writeTask=True),
        )
        selected = [
            module_id
            for stage in result["planGraph"]["stages"]
            for slot in stage["slots"]
            for module_id in slot["selectedModules"]
        ]

        self.assertEqual(result["status"], "active")
        for module_id in (
            "implement-documentation", "implement-result-gate",
            "review-self", "verify-execution",
        ):
            self.assertIn(module_id, selected)

    def test_document_operation_cannot_claim_read_only_execution(self):
        from selfworkflow.resolver import ResolveError, resolve_task

        with self.assertRaises(ResolveError):
            resolve_task(
                self.catalog,
                self._request(operationType="document", writeTask=False),
            )

    def test_plan_hash_is_stable_and_binds_capability_identity(self):
        from selfworkflow.resolver import resolve_task

        request = self._request()
        first = resolve_task(self.catalog, request)
        repeat = resolve_task(self.catalog, deepcopy(request))
        changed_request = deepcopy(request)
        changed_request["capabilityEvidenceSnapshot"]["evidence"][0]["subject"]["build"] = "2"
        changed_request["capabilityEvidenceSnapshot"]["evidence"][0]["evidenceHash"] = "sha256:" + "2" * 64
        changed = resolve_task(self.catalog, changed_request)

        self.assertEqual(first["planGraph"]["planHash"], repeat["planGraph"]["planHash"])
        self.assertNotEqual(first["planGraph"]["requestHash"], changed["planGraph"]["requestHash"])
        self.assertNotEqual(first["planGraph"]["planHash"], changed["planGraph"]["planHash"])

    def test_explicit_grill_precedes_independent_brainstorming_cross_review(self):
        from selfworkflow.resolver import resolve_task

        result = resolve_task(
            self.catalog,
            self._request(complexity="C3", risk="R2", explicitModuleIds=["design-grill-me"]),
        )
        design = next(stage for stage in result["planGraph"]["stages"] if stage["stageId"] == "designed")
        selected = [module for slot in design["slots"] for module in slot["selectedModules"]]
        self.assertLess(selected.index("design-grill-me"), selected.index("design-cross-review"))

    def test_missing_required_capability_returns_paused_reason_without_downgrade(self):
        from selfworkflow.resolver import resolve_task

        request = self._request(complexity="C2", risk="R1")
        request["capabilityEvidenceSnapshot"]["evidence"] = [
            item for item in request["capabilityEvidenceSnapshot"]["evidence"]
            if item["name"] != "skill-discovery"
        ]
        result = resolve_task(self.catalog, request)
        self.assertEqual(result["status"], "paused")
        self.assertIn("required-capability-unavailable", result["reasonCodes"])

    def test_stale_evidence_invalidates_plan(self):
        from selfworkflow.resolver import resolve_task

        request = self._request()
        request["capabilityEvidenceSnapshot"]["capturedAt"] = "2024-08-08T12:00:00Z"
        for item in request["capabilityEvidenceSnapshot"]["evidence"]:
            item["observedAt"] = "2024-01-01T00:00:00Z"
            item["validUntil"] = "2025-01-01T00:00:00Z"
        result = resolve_task(self.catalog, request)
        self.assertEqual(result["status"], "paused")
        self.assertIn("source-evidence-stale", result["reasonCodes"])

    def test_future_snapshot_timestamp_cannot_extend_freshness(self):
        from selfworkflow.resolver import resolve_task

        request = self._request()
        request["capabilityEvidenceSnapshot"]["capturedAt"] = "2090-01-01T00:00:00Z"

        result = resolve_task(self.catalog, request)

        self.assertEqual(result["status"], "paused")
        self.assertIn("source-evidence-stale", result["reasonCodes"])

    def test_cross_slot_dependency_is_fail_closed(self):
        from selfworkflow.pipeline import canonical_hash
        from selfworkflow.resolver import resolve_task

        envelope = json.loads(self.catalog)
        update = next(
            module for module in envelope["catalog"]["modules"]
            if module["id"] == "knowledge-update"
        )
        update["supportEvidence"]["adapterSupport"] = "supported"
        update["supportEvidence"]["behaviorEvidence"] = "supported"
        envelope["catalogHash"] = canonical_hash(envelope["catalog"])
        request = self._request(
            operationType="knowledge-write",
            writeTask=False,
            explicitModuleIds=["knowledge-update"],
        )
        request["capabilityEvidenceSnapshot"]["evidence"].append(
            self._evidence("knowledge-write", suffix="2")
        )

        result = resolve_task(envelope, request)

        self.assertEqual(result["status"], "paused")
        self.assertIn("module-dependency-unavailable", result["reasonCodes"])
        completed = next(
            stage for stage in result["planGraph"]["stages"]
            if stage["stageId"] == "completed"
        )
        self.assertEqual(completed["applicability"], "blocked")

    def test_cross_slot_conflict_is_fail_closed(self):
        from selfworkflow.pipeline import canonical_hash
        from selfworkflow.resolver import resolve_task

        envelope = json.loads(self.catalog)
        grill = next(
            module for module in envelope["catalog"]["modules"]
            if module["id"] == "design-grill-me"
        )
        grill["conflicts"] = ["design-brainstorming"]
        envelope["catalogHash"] = canonical_hash(envelope["catalog"])

        result = resolve_task(
            envelope,
            self._request(
                complexity="C3", risk="R2",
                explicitModuleIds=["design-grill-me"],
            ),
        )

        self.assertEqual(result["status"], "paused")
        self.assertIn("module-conflict", result["reasonCodes"])
        designed = next(
            stage for stage in result["planGraph"]["stages"]
            if stage["stageId"] == "designed"
        )
        self.assertEqual(designed["applicability"], "blocked")

    def test_v1_migration_is_explicit_and_never_invents_verified_capabilities(self):
        from selfworkflow.resolver import resolve_task

        legacy = {
            "schemaVersion": 1, "stage": "implemented", "operationType": "implement",
            "complexity": "C1", "risk": "R1", "writeTask": True,
            "superpowersSourceStatus": "supported",
            "capabilityStates": {"filesystem-read": "supported", "filesystem-write": "supported"},
        }
        result = resolve_task(self.catalog, legacy)
        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["diagnostics"], [{"code": "legacy-capability-evidence-unverified", "severity": "warning"}])

    def test_invalid_request_is_redacted(self):
        from selfworkflow.resolver import ResolveError, resolve_task

        request = self._request()
        request["must-not-appear"] = "secret"
        with self.assertRaises(ResolveError) as raised:
            resolve_task(self.catalog, request)
        self.assertEqual(str(raised.exception), "resolve-failed")
        self.assertNotIn("secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
