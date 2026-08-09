import json
from pathlib import Path
import subprocess
import tempfile
import unittest


def _git(root, *args, input_bytes=None):
    return subprocess.run(["git", *args], cwd=root, input=input_bytes, capture_output=True, check=True)


def _init(root):
    _git(root, "init", "-q")
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "-c", "user.name=Tests", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "base")


class GitPolicyTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_forbidden_runtime_sensitive_database_and_size_rules(self):
        from selfworkflow.git_policy import check_repository

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            _init(root)
            files = {
                ".env.example": b"TOKEN=redacted\n",
                ".env.local": b"TOKEN=not-a-real-secret\n",
                "runtime/cache.txt": b"generated\n",
                "data/state.sqlite": b"SQLite format 3\x00",
                "large.bin": b"x" * (1024 * 1024 + 1),
            }
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            _git(root, "add", "-f", *files)
            report = check_repository(root, self.ROOT / "workflow/git-policy.yaml")
            by_path = {(item["path"], item["code"]) for item in report["findings"]}
            self.assertNotIn((".env.example", "sensitive-path"), by_path)
            self.assertIn((".env.local", "sensitive-path"), by_path)
            self.assertIn(("runtime/cache.txt", "runtime-root"), by_path)
            self.assertIn(("data/state.sqlite", "database-file"), by_path)
            self.assertIn(("large.bin", "large-file-warning"), by_path)
            self.assertEqual(report["status"], "failed")

    def test_secret_binary_symlink_submodule_and_redaction(self):
        from selfworkflow.git_policy import check_repository

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            _init(root)
            secret_marker = b"-----BEGIN " + b"PRIVATE KEY-----\n"
            (root / "secret.txt").write_bytes(secret_marker)
            (root / "binary.dat").write_bytes(b"a\x00b")
            _git(root, "add", "secret.txt", "binary.dat")
            link_blob = _git(root, "hash-object", "-w", "--stdin", input_bytes=b"README.md").stdout.decode().strip()
            _git(root, "update-index", "--add", "--cacheinfo", f"120000,{link_blob},link")
            head = _git(root, "rev-parse", "HEAD").stdout.decode().strip()
            _git(root, "update-index", "--add", "--cacheinfo", f"160000,{head},vendor")
            report = check_repository(root, self.ROOT / "workflow/git-policy.yaml")
            codes = {item["code"] for item in report["findings"]}
            self.assertTrue({"known-secret-pattern", "binary-file", "symlink", "submodule"} <= codes)
            rendered = json.dumps(report)
            self.assertNotIn("BEGIN PRIVATE KEY", rendered)

    def test_over_limit_blob_fails_and_hash_bound_allowlist_can_exempt_it(self):
        from selfworkflow.git_policy import check_repository, load_git_policy

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            _init(root)
            huge = root / "approved-model.bin"
            huge.write_bytes(b"z" * (5 * 1024 * 1024 + 1))
            _git(root, "add", "approved-model.bin")
            failed = check_repository(root, self.ROOT / "workflow/git-policy.yaml")
            finding = next(item for item in failed["findings"] if item["code"] == "large-file-failure")
            policy = load_git_policy(self.ROOT / "workflow/git-policy.yaml")
            policy["allowlist"] = [{
                "path": "approved-model.bin", "objectHash": finding["objectHash"],
                "reason": "test fixture", "owner": "tests", "expires": "2099-01-01",
            }]
            allowed = check_repository(root, policy)
            self.assertFalse(any(item["code"] == "large-file-failure" for item in allowed["findings"]))

    def test_current_repository_has_no_policy_failure_or_frozen_c7_feature_diff(self):
        from selfworkflow.git_policy import check_repository, load_git_policy

        report = check_repository(self.ROOT, self.ROOT / "workflow/git-policy.yaml")
        self.assertNotEqual(report["status"], "failed", report)
        policy = load_git_policy(self.ROOT / "workflow/git-policy.yaml")
        self.assertEqual(policy["allowlist"], [{
            "path": "dependencies/upstream/tea",
            "objectHash": "2882e9c8972a94f48d5e848039eec435436f2459",
            "reason": "Pinned official TEA source used by the optional V3 test-quality adapter",
            "owner": "SelfWorkFlow maintainers",
            "expires": "2030-12-31",
        }])
        changed = subprocess.run(
            ["git", "diff", "--name-only", "3ff07d6..HEAD"], cwd=self.ROOT,
            check=True, capture_output=True, text=True,
        ).stdout.splitlines()
        frozen = (
            "extensions/knowledge/c7-openwiki/", "src/selfworkflow/c7_openwiki.py",
            "tests/conformance/test_c7_openwiki_adapter.py", "tests/fixtures/c7-openwiki/",
        )
        self.assertEqual([path for path in changed if any(path == prefix or path.startswith(prefix) for prefix in frozen)], [])


if __name__ == "__main__":
    unittest.main()
