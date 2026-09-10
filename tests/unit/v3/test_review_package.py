import unittest

from selfworkflow.v3.hashing import content_hash
from selfworkflow.v3.review_package import (
    ReviewPackageError,
    normalize_review_package,
    ordered_skill_manifest,
    skill_manifest_hash,
)


PLAN_HASH = "sha256:" + "f" * 64


def _package(kind="code", stage="implemented", attempt="attempt-1"):
    value = {
        "schemaVersion": 1,
        "reviewKind": kind,
        "planHash": PLAN_HASH,
        "stageId": stage,
        "attemptRef": attempt,
        "content": {
            "changes": [{"path": "src/example.cpp", "status": "modified"}],
            "baseline": {"baseHead": "HEAD"},
            "specification": {"objective": "review"},
            "verificationPlans": [{"command": "unit-tests"}],
            "plan": {"objective": "review"},
            "acceptanceCriteria": ["review package is complete"],
            "testDesign": {"cases": ["direct", "failure"]},
        },
    }
    return {**value, "packageHash": content_hash(value)}


class ReviewPackageTests(unittest.TestCase):
    def test_package_is_bound_to_kind_plan_stage_and_attempt(self):
        result = normalize_review_package(
            _package(), expected_kind="code", plan_hash=PLAN_HASH,
            stage_id="implemented", attempt_ref="attempt-1",
        )
        self.assertEqual(result["packageHash"], _package()["packageHash"])

        with self.assertRaisesRegex(ReviewPackageError, "review-package-binding-invalid"):
            normalize_review_package(
                _package(), expected_kind="plan", plan_hash=PLAN_HASH,
                stage_id="implemented", attempt_ref="attempt-1",
            )

    def test_package_hash_and_attempt_drift_fail_closed(self):
        value = _package()
        value["content"]["changes"].append({"path": "src/other.cpp", "status": "added"})
        with self.assertRaisesRegex(ReviewPackageError, "review-package-hash-invalid"):
            normalize_review_package(
                value, expected_kind="code", plan_hash=PLAN_HASH,
                stage_id="implemented", attempt_ref="attempt-1",
            )

    def test_code_and_plan_packages_require_complete_review_material(self):
        code = _package()
        code["content"].pop("baseline")
        code["packageHash"] = content_hash({
            key: value for key, value in code.items() if key != "packageHash"
        })
        with self.assertRaisesRegex(ReviewPackageError, "review-code-package-incomplete"):
            normalize_review_package(
                code, expected_kind="code", plan_hash=PLAN_HASH,
                stage_id="implemented", attempt_ref="attempt-1",
            )

    def test_project_skill_manifest_precedes_pinned_generic_skill(self):
        context = {
            "status": "loaded",
            "reviewers": {
                "standards": {"manifest": ({
                    "id": "project.review", "path": "review.md",
                    "contentHash": "sha256:" + "a" * 64, "required": True,
                },)},
            },
        }
        manifest = ordered_skill_manifest(context)
        self.assertEqual([item["layer"] for item in manifest], ["project", "generic"])
        self.assertEqual(
            [item["role"] for item in manifest], ["primary", "supplementary"]
        )
        self.assertEqual(skill_manifest_hash(manifest), skill_manifest_hash(manifest))

    def test_generic_skill_is_primary_without_a_verified_project_skill(self):
        manifest = ordered_skill_manifest({"status": "absent", "reviewers": {}})
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["layer"], "generic")
        self.assertEqual(manifest[0]["role"], "primary")

    def test_verified_project_skills_stay_primary_with_optional_drift(self):
        context = {
            "status": "unverified",
            "reviewers": {
                "standards": {"manifest": ({
                    "id": "project.review", "path": "review.md",
                    "contentHash": "sha256:" + "a" * 64, "required": True,
                },)},
            },
        }
        manifest = ordered_skill_manifest(context)
        self.assertEqual(
            [(item["id"], item["role"]) for item in manifest],
            [
                ("project.review", "primary"),
                ("matt-pocock.code-review", "supplementary"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
