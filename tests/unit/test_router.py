import copy
import hashlib
import json
from pathlib import Path
import unittest

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _entry(
    skill_id,
    *,
    dependencies=(),
    conflicts=(),
    mandatory=False,
    scopes=(),
    extensions=(),
    operations=(),
    semantic=(),
    capabilities=("filesystem-read",),
    priority=100,
    cost=50,
    support="supported",
):
    return {
        "domain": "fixture",
        "id": skill_id,
        "displayName": skill_id,
        "source": {
            "kind": "workflow",
            "path": "WORKFLOW.md",
            "revision": "git:" + "1" * 40,
            "contentHash": "sha256:" + "2" * 64,
        },
        "aliases": [],
        "triggers": list(semantic),
        "exclusions": [],
        "selectors": {
            "fileExtensions": list(extensions),
            "operationTypes": list(operations),
            "semanticTerms": list(semantic),
        },
        "stages": ["discovered", "designed", "implemented", "reviewed", "verified"],
        "requiredCapabilities": list(capabilities),
        "dependencies": list(dependencies),
        "conflicts": list(conflicts),
        "composition": "augment",
        "mandatory": mandatory,
        "mandatoryWhen": {
            "match": "any",
            "scopes": list(scopes),
            "fileExtensions": [],
            "operationTypes": [],
        },
        "priority": priority,
        "contextCost": cost,
        "supportStatus": support,
        "protectedRuleOperations": [],
    }


def _catalog(*entries, aliases=()):
    catalog = {
        "domains": ["fixture"],
        "entries": list(entries),
        "standardCapabilities": ["filesystem-read", "filesystem-write", "test-execution"],
    }
    payload = json.dumps(
        catalog,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    envelope = {
        "schemaVersion": 1,
        "catalog": catalog,
        "catalogHash": "sha256:" + hashlib.sha256(payload).hexdigest(),
    }
    for alias, target in aliases:
        next(entry for entry in entries if entry["id"] == target)["aliases"].append(
            {"name": alias, "target": target}
        )
    if aliases:
        return _catalog(*entries)
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode() + b"\n"


class RouterTests(unittest.TestCase):
    def _request(self, **overrides):
        from selfworkflow.router import RouteRequest

        values = {
            "stage": "implemented",
            "operation_type": "implement",
            "file_extensions": (".cpp",),
            "semantic_terms": (),
            "explicit_skills": (),
            "mandatory_scopes": ("global", "safety", "project"),
            "capability_states": {
                "filesystem-read": "supported",
                "filesystem-write": "supported",
                "test-execution": "supported",
            },
            "context_budget": 1000,
            "max_semantic_candidates": 4,
        }
        values.update(overrides)
        return RouteRequest(**values)

    def test_explicit_alias_has_priority_and_duplicates_are_removed(self):
        from selfworkflow.router import route_skills

        core = _entry("core", mandatory=True, scopes=("global",), priority=1000)
        explicit = _entry("explicit", dependencies=("core",), priority=1)
        result = route_skills(
            _catalog(core, explicit, aliases=(("chosen", "explicit"),)),
            self._request(explicit_skills=("chosen", "explicit", "chosen")),
        )
        self.assertEqual(result.status, "routed")
        self.assertEqual(result.selected, ("core", "explicit"))
        self.assertEqual(len(result.selected), len(set(result.selected)))
        candidate = next(item for item in result.candidates if item.skill_id == "explicit")
        self.assertIn("explicit", candidate.reasons)

    def test_safety_and_project_mandatory_cannot_be_removed_by_semantic_score(self):
        from selfworkflow.router import route_skills

        hard = _entry(
            "hard",
            scopes=("safety",),
            conflicts=("semantic",),
            priority=1,
        )
        semantic = _entry("semantic", semantic=("fix",), priority=999)
        result = route_skills(
            _catalog(hard, semantic),
            self._request(semantic_terms=("fix",)),
        )
        self.assertIn("hard", result.selected)
        self.assertNotIn("semantic", result.selected)
        self.assertEqual(
            next(item.reason for item in result.exclusions if item.skill_id == "semantic"),
            "conflict:hard",
        )

    def test_file_stage_and_operation_selectors_match_deterministically(self):
        from selfworkflow.router import route_skills

        code = _entry("code", extensions=(".cpp",), operations=("implement",))
        docs = _entry("docs", extensions=(".md",), operations=("document",))
        result = route_skills(_catalog(code, docs), self._request())
        self.assertEqual(result.selected, ("code",))
        self.assertIn(
            "deterministic:file-extension",
            next(item for item in result.candidates if item.skill_id == "code").reasons,
        )
        self.assertEqual(
            next(item.reason for item in result.exclusions if item.skill_id == "docs"),
            "not-matched",
        )

    def test_semantic_candidates_are_bounded_exact_and_cannot_enable_unverified_skill(self):
        from selfworkflow.router import route_skills

        entries = [
            _entry(f"s{index}", semantic=("quality",), priority=100 - index)
            for index in range(6)
        ]
        entries.append(_entry("false-positive", semantic=("quality gate",)))
        entries.append(_entry("planned", semantic=("quality",), support="unverified"))
        result = route_skills(
            _catalog(*entries),
            self._request(
                semantic_terms=("quality",),
                max_semantic_candidates=3,
            ),
        )
        semantic_candidates = [
            item for item in result.candidates if "semantic" in item.reasons
        ]
        self.assertEqual(len(semantic_candidates), 3)
        self.assertNotIn("false-positive", result.selected)
        self.assertNotIn("planned", result.selected)

    def test_dependency_closure_and_conflict_resolution_are_deterministic(self):
        from selfworkflow.router import route_skills

        dependency = _entry("dependency")
        winner = _entry(
            "winner",
            dependencies=("dependency",),
            conflicts=("loser",),
            extensions=(".cpp",),
            priority=50,
        )
        loser = _entry("loser", extensions=(".cpp",), priority=10)
        result = route_skills(_catalog(dependency, winner, loser), self._request())
        self.assertEqual(result.selected, ("dependency", "winner"))
        self.assertEqual(
            next(item.reason for item in result.exclusions if item.skill_id == "loser"),
            "conflict:winner",
        )

    def test_missing_capability_pauses_without_silent_degradation(self):
        from selfworkflow.router import route_skills

        writer = _entry(
            "writer",
            extensions=(".cpp",),
            capabilities=("filesystem-read", "filesystem-write"),
        )
        result = route_skills(
            _catalog(writer),
            self._request(capability_states={"filesystem-read": "supported"}),
        )
        self.assertEqual(result.status, "paused")
        self.assertEqual(result.missing_capabilities, ("filesystem-write",))
        self.assertIn("writer", result.selected)

    def test_context_over_budget_splits_stages_without_dropping_mandatory(self):
        from selfworkflow.router import route_skills

        mandatory = _entry("mandatory", mandatory=True, cost=70, priority=1000)
        first = _entry("first", extensions=(".cpp",), cost=60, priority=20)
        second = _entry("second", extensions=(".cpp",), cost=50, priority=10)
        result = route_skills(
            _catalog(mandatory, first, second),
            self._request(context_budget=100),
        )
        self.assertEqual(result.selected, ("mandatory", "first", "second"))
        self.assertGreater(len(result.stages), 1)
        self.assertIn("mandatory", tuple(skill for stage in result.stages for skill in stage.skill_ids))
        self.assertTrue(all(stage.context_cost <= 100 for stage in result.stages))

    def test_fixture_requests_are_closed_and_catalog_hash_is_verified(self):
        from selfworkflow.router import RouteError, route_skills

        fixture = yaml.safe_load(
            (REPOSITORY_ROOT / "tests" / "fixtures" / "router" / "requests.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(set(fixture), {"schemaVersion", "requests"})
        content = _catalog(_entry("code", extensions=(".cpp",)))
        tampered = bytearray(content)
        tampered[tampered.index(b"fixture")] = ord("x")
        with self.assertRaises(RouteError):
            route_skills(bytes(tampered), self._request())

    def test_checked_in_catalog_routes_only_verified_engineering_entries(self):
        from selfworkflow.catalog import compile_catalog
        from selfworkflow.router import route_skills

        compiled = compile_catalog(REPOSITORY_ROOT / "catalog")
        result = route_skills(
            compiled.content,
            self._request(
                capability_states={
                    "filesystem-read": "supported",
                    "filesystem-write": "supported",
                    "test-execution": "supported",
                    "skill-discovery": "supported",
                }
            ),
        )
        self.assertEqual(result.status, "routed")
        self.assertEqual(
            result.selected,
            (
                "workflow-core",
                "testing-review-quality",
                "tea-quality-foundation",
                "matt-skills-foundation",
            ),
        )
        self.assertEqual(result.catalog_hash, compiled.catalog_hash)
        self.assertEqual(
            next(
                item.reason
                for item in result.exclusions
                if item.skill_id == "code-quality-verification-contract"
            ),
            "support-unverified",
        )

    def test_checked_in_catalog_skips_core_for_read_only_and_loads_governance_explicitly(self):
        from selfworkflow.catalog import compile_catalog
        from selfworkflow.router import route_skills

        compiled = compile_catalog(REPOSITORY_ROOT / "catalog")
        read_only = route_skills(
            compiled.content,
            self._request(
                stage="discovered",
                operation_type="read-only",
                file_extensions=(),
                semantic_terms=("workflow execution",),
            ),
        )
        self.assertEqual(read_only.status, "routed")
        self.assertEqual(read_only.selected, ())

        install = route_skills(
            compiled.content,
            self._request(
                stage="reviewed",
                operation_type="install",
                file_extensions=(),
            ),
        )
        self.assertEqual(
            install.selected,
            ("workflow-core", "workflow-protected-rules"),
        )

        document = route_skills(
            compiled.content,
            self._request(
                stage="implemented",
                operation_type="document",
                file_extensions=(".md",),
            ),
        )
        self.assertIn("workflow-core", document.selected)

    def test_v2_routes_strength_defaults_without_duplicate_grill_loading(self):
        from selfworkflow.catalog import compile_catalog
        from selfworkflow.router import ModuleRouteRequest, route_modules

        compiled = compile_catalog(REPOSITORY_ROOT / "catalog")
        design = route_modules(
            compiled.content,
            ModuleRouteRequest(
                slot_id="design.primary",
                cardinality="exactly-one",
                operation_type="implement",
                strength="Full",
                write_task=True,
                capability_states={"skill-discovery": "supported"},
            ),
        )
        self.assertEqual(design.status, "routed")
        self.assertEqual(design.selected_modules, ("design-core",))

        light_design = route_modules(
            compiled.content,
            ModuleRouteRequest(
                slot_id="design.primary",
                cardinality="exactly-one",
                operation_type="implement",
                strength="Light",
                write_task=True,
                capability_states={"skill-discovery": "supported"},
            ),
        )
        self.assertEqual(light_design.selected_modules, ("design-core",))

        light_grill = route_modules(
            compiled.content,
            ModuleRouteRequest(
                slot_id="design.specialists", cardinality="zero-or-many",
                operation_type="implement", strength="Light", write_task=True,
                capability_states={"skill-discovery": "supported"},
            ),
        )
        self.assertEqual(light_grill.selected_modules, ())

        full_grill = route_modules(
            compiled.content,
            ModuleRouteRequest(
                slot_id="design.specialists", cardinality="zero-or-many",
                operation_type="implement", strength="Full", write_task=True,
                capability_states={"skill-discovery": "supported"},
            ),
        )
        self.assertEqual(full_grill.selected_modules, ("design-grilling",))

        deep_grill = route_modules(
            compiled.content,
            ModuleRouteRequest(
                slot_id="design.specialists", cardinality="zero-or-many",
                operation_type="implement", strength="Deep", write_task=True,
                capability_states={
                    "skill-discovery": "supported",
                    "user-confirmation": "supported",
                },
            ),
        )
        self.assertEqual(deep_grill.selected_modules, ("design-grill-me",))

        deep_without_confirmation = route_modules(
            compiled.content,
            ModuleRouteRequest(
                slot_id="design.specialists", cardinality="zero-or-many",
                operation_type="implement", strength="Deep", write_task=True,
                capability_states={"skill-discovery": "supported"},
            ),
        )
        self.assertEqual(deep_without_confirmation.status, "paused")
        self.assertEqual(
            deep_without_confirmation.missing_capabilities,
            ("user-confirmation",),
        )
        self.assertEqual(
            deep_without_confirmation.selected_modules,
            ("design-grill-me",),
        )

        knowledge = route_modules(
            compiled.content,
            ModuleRouteRequest(
                slot_id="knowledge.update",
                cardinality="zero-or-one",
                operation_type="knowledge-write",
                strength="Full",
                write_task=False,
                explicit_module_ids=(),
                capability_states={"knowledge-write": "supported", "user-confirmation": "supported"},
            ),
        )
        self.assertEqual(knowledge.status, "routed")
        self.assertEqual(knowledge.selected_modules, ())

    def test_explicit_grill_does_not_invent_a_hidden_cross_review_module(self):
        from selfworkflow.catalog import compile_catalog
        from selfworkflow.router import ModuleRouteRequest, route_modules

        compiled = compile_catalog(REPOSITORY_ROOT / "catalog")
        common = dict(
            operation_type="design",
            strength="Deep",
            write_task=False,
            explicit_module_ids=("design-grill-me",),
            capability_states={
                "skill-discovery": "supported",
                "independent-context": "supported",
                "user-confirmation": "supported",
            },
        )
        grill = route_modules(
            compiled.content,
            ModuleRouteRequest(slot_id="design.specialists", cardinality="zero-or-many", **common),
        )
        cross_review = route_modules(
            compiled.content,
            ModuleRouteRequest(slot_id="design.cross-review", cardinality="zero-or-one", **common),
        )
        self.assertEqual(grill.selected_modules, ("design-grill-me",))
        self.assertEqual(cross_review.selected_modules, ())

    def test_strength_defaults_do_not_depend_on_project_default_lists(self):
        from selfworkflow.catalog import compile_catalog
        from selfworkflow.router import ModuleRouteRequest, route_modules

        catalog = compile_catalog(REPOSITORY_ROOT / "catalog").content
        full = route_modules(
            catalog,
            ModuleRouteRequest(
                slot_id="design.specialists", cardinality="zero-or-many",
                operation_type="implement", strength="Full", write_task=True,
                project_default_module_ids=("design-grill-me",),
                capability_states={"skill-discovery": "supported"},
            ),
        )
        self.assertEqual(full.selected_modules, ("design-grilling",))

        deep = route_modules(
            catalog,
            ModuleRouteRequest(
                slot_id="design.specialists", cardinality="zero-or-many",
                operation_type="implement", strength="Deep", write_task=True,
                project_default_module_ids=("design-grilling",),
                capability_states={
                    "skill-discovery": "supported",
                    "user-confirmation": "supported",
                },
            ),
        )
        self.assertEqual(deep.selected_modules, ("design-grill-me",))


if __name__ == "__main__":
    unittest.main()
