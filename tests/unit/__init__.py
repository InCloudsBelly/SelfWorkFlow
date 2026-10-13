"""Deterministic aggregate entry for all SelfWorkFlow unit tests."""

import unittest
from pathlib import Path


UNIT_TEST_MODULES = tuple(
    "tests.unit." + ".".join(path.relative_to(Path(__file__).parent).with_suffix("").parts)
    for path in sorted(Path(__file__).parent.rglob("test_*.py"))
)


def _cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _cases(item)
        else:
            yield item


def load_tests(
    loader: unittest.TestLoader,
    tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    """Load each registered unit module exactly once in fixed order."""

    del tests, pattern
    suite = unittest.TestSuite()
    seen = set()
    for module_name in UNIT_TEST_MODULES:
        for case in _cases(loader.loadTestsFromName(module_name)):
            if case.id() not in seen:
                seen.add(case.id())
                suite.addTest(case)
    return suite
