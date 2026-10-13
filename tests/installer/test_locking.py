from pathlib import Path
import tempfile
import unittest
from unittest import mock

from selfworkflow.transactions import TransactionError, exclusive_install_lock


class InstallLockTests(unittest.TestCase):
    def test_transient_release_failure_retries_and_releases_the_owned_lock(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            state = Path(temporary)
            unlink = Path.unlink
            attempts = []

            def transient(path, *args, **kwargs):
                if path == state / "install.lock":
                    attempts.append(path)
                    if len(attempts) == 1:
                        raise PermissionError("busy")
                return unlink(path, *args, **kwargs)

            with mock.patch.object(Path, "unlink", transient):
                with exclusive_install_lock(state):
                    pass
            self.assertFalse((state / "install.lock").exists())
            self.assertEqual(len(attempts), 2)

    def test_second_writer_is_rejected_and_lock_is_released(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            state = Path(temporary)
            with exclusive_install_lock(state):
                with self.assertRaises(TransactionError):
                    with exclusive_install_lock(state):
                        pass
            with exclusive_install_lock(state):
                self.assertTrue((state / "install.lock").exists())

    def test_persistent_cleanup_failure_preserves_body_error_and_owned_lock(self):
        for fail_body in (False, True):
            with self.subTest(fail_body=fail_body), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                state = Path(temporary)
                original = ValueError("operation failed")
                unlink = Path.unlink
                attempts = []

                def busy_lock(path, *args, **kwargs):
                    if path.name == "install.lock":
                        attempts.append(path)
                        raise PermissionError("busy")
                    return unlink(path, *args, **kwargs)

                with mock.patch.object(Path, "unlink", busy_lock):
                    with self.assertRaises(ValueError if fail_body else TransactionError) as caught:
                        with exclusive_install_lock(state):
                            if fail_body:
                                raise original
                self.assertEqual(len(attempts), 3)
                self.assertTrue((state / "install.lock").is_file())
                if fail_body:
                    self.assertIs(caught.exception, original)
                    self.assertIn("installer-lock-release-failed", original.__notes__)
                else:
                    self.assertEqual(str(caught.exception), "installer-lock-release-failed")


if __name__ == "__main__":
    unittest.main()
