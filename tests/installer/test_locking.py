from pathlib import Path
import tempfile
import unittest

from selfworkflow.transactions import TransactionError, exclusive_install_lock


class InstallLockTests(unittest.TestCase):
    def test_second_writer_is_rejected_and_lock_is_released(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            state = Path(temporary)
            with exclusive_install_lock(state):
                with self.assertRaises(TransactionError):
                    with exclusive_install_lock(state):
                        pass
            with exclusive_install_lock(state):
                self.assertTrue((state / "install.lock").exists())


if __name__ == "__main__":
    unittest.main()
