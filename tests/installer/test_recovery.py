from pathlib import Path
import json
import tempfile
import unittest

from selfworkflow.transactions import recover_transactions


class RecoveryTests(unittest.TestCase):
    def test_incomplete_transaction_is_reported_without_automatic_overwrite(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            state = Path(temporary)
            transactions = state / "transactions"
            transactions.mkdir()
            (transactions / "tx.json").write_text(
                json.dumps({"transactionId": "tx", "state": "applying"}),
                encoding="utf-8",
            )
            result = recover_transactions(state)
            self.assertEqual(result[0]["transactionId"], "tx")
            self.assertEqual(result[0]["action"], "manual-attention")
            self.assertTrue((transactions / "tx.json").exists())


if __name__ == "__main__":
    unittest.main()
