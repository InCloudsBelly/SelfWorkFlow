"""Deterministic release eligibility checks over structured evidence."""

from __future__ import annotations


_REQUIRED_SUITES = ("unit", "conformance", "installer", "behavioral")
_REVIEW_LEVELS = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


def evaluate_release(manifest: dict[str, object]) -> dict[str, object]:
    issues: set[str] = set()
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        return {"eligible": False, "issues": ("manifest-invalid",)}
    if manifest.get("runtimeProfile") not in {"core", "knowledge", "maintainer"}:
        issues.add("runtime-profile-invalid")
    source = manifest.get("source")
    if not isinstance(source, dict) or source.get("dirty") is not False:
        issues.add("source-dirty")
    tests = manifest.get("tests")
    by_suite = {
        item.get("suite"): item
        for item in tests
        if isinstance(item, dict) and isinstance(item.get("suite"), str)
    } if isinstance(tests, list) else {}
    for suite in _REQUIRED_SUITES:
        if suite not in by_suite:
            issues.add(f"test-missing:{suite}")
        elif by_suite[suite].get("status") != "passed":
            issues.add(f"test-not-passed:{suite}")
    review = manifest.get("review")
    if not isinstance(review, dict) or review.get("decision") != "passed":
        issues.add("review-not-passed")
    else:
        if _REVIEW_LEVELS.get(review.get("level"), -1) < 2:
            issues.add("review-level-insufficient")
        if review.get("implementationContextId") == review.get("reviewContextId"):
            issues.add("review-not-independent")
    hosts = manifest.get("hostEvidence")
    if not isinstance(hosts, dict):
        issues.add("host-evidence-invalid")
    else:
        for host in ("codex-cli", "codex-desktop"):
            if hosts.get(host) != "supported":
                issues.add(f"host-evidence-missing:{host}")
    return {"eligible": not issues, "issues": tuple(sorted(issues))}
