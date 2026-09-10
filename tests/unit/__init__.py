"""Deterministic aggregate entry for all SelfWorkFlow unit tests."""

import unittest


UNIT_TEST_MODULES = (
    "tests.unit.test_capability_gate",
    "tests.unit.test_catalog",
    "tests.unit.test_classifier",
    "tests.unit.test_config",
    "tests.unit.test_contract_schemas",
    "tests.unit.test_evidence",
    "tests.unit.test_git_policy",
    "tests.unit.test_imports",
    "tests.unit.test_knowledge_contract",
    "tests.unit.test_ledger",
    "tests.unit.test_pipeline",
    "tests.unit.test_project_review_profile",
    "tests.unit.test_protected_rules",
    "tests.unit.test_quality_gate",
    "tests.unit.test_resolver",
    "tests.unit.test_review_models",
    "tests.unit.test_router",
    "tests.unit.test_sources",
    "tests.unit.test_superpowers_overlay",
)


def load_tests(
    loader: unittest.TestLoader,
    tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    """Load each registered unit module exactly once in fixed order."""

    del tests, pattern
    suite = unittest.TestSuite()
    for module_name in UNIT_TEST_MODULES:
        suite.addTests(loader.loadTestsFromName(module_name))
    return suite
