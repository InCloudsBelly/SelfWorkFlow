"""Deterministic aggregate entry for all SelfWorkFlow unit tests."""

import unittest


UNIT_TEST_MODULES = (
    "tests.unit.test_capability_gate",
    "tests.unit.test_catalog",
    "tests.unit.test_classifier",
    "tests.unit.test_config",
    "tests.unit.test_evidence",
    "tests.unit.test_protected_rules",
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
