from __future__ import annotations

import hashlib
from pathlib import Path
import re
import unittest

import yaml

from selfworkflow.implement_spec import (
    ImplementSpecEvidenceError,
    ticket_dag_hash,
    validate_implement_spec_evidence,
)


ROOT = Path(__file__).resolve().parents[2]


class ImplementSpecContractTests(unittest.TestCase):
    """Validate the published adapter contract, not agent execution or scheduling."""

    def test_explicit_adapter_contract_preserves_entry_and_completion_gates(self):
        path = ROOT / "skills/implement-spec/SKILL.md"
        self.assertTrue(path.is_file(), "Missing local implement-spec wrapper")
        text = path.read_text(encoding="utf-8")
        frontmatter = yaml.safe_load(text.split("---", 2)[1])
        self.assertEqual(frontmatter["name"], "implement-spec")
        self.assertEqual(frontmatter["metadata"]["activation"], "explicit")
        blocks = re.findall(r"```yaml\n(.*?)\n```", text, re.DOTALL)
        self.assertEqual(len(blocks), 1, "One reviewable adapter contract is required")
        contract = yaml.safe_load(blocks[0])
        self.assertEqual(contract["activation"], "explicit")
        self.assertEqual(contract["kind"], "instruction-wrapper")
        self.assertEqual(contract["minimumTickets"], 2)
        self.assertEqual(set(contract["requires"]), {
            "spec", "ticket-dag", "plan-review", "implementation-confirmation",
            "independent-agents", "independent-review", "git-permissions",
        })
        self.assertEqual(contract["missingEvidence"], "unverified")
        self.assertEqual(contract["upstreamReference"],
                         "skills/matt-pocock/implement-spec/SKILL.md")
        self.assertEqual(set(contract["outputs"]), {
            "integration-head", "ticket-results", "tdd-evidence",
            "review-evidence", "verification-evidence", "retained-worktrees",
            "pending-actions", "limitations",
        })
        self.assertEqual(set(contract["completionRequires"]), {
            "all-tickets-integrated", "independent-review-passed",
            "verification-passed", "no-open-blocking-findings",
        })
        self.assertEqual(set(contract["neverAutomatic"]), {
            "reset", "push", "pull-request", "ticket-close", "worktree-cleanup",
        })

    def test_upstream_selection_is_unique_and_hash_bound(self):
        lock = yaml.safe_load(
            (ROOT / "dependencies/locks/matt-pocock-skills.lock.yaml").read_text("utf-8")
        )
        selected = [item for item in lock["selectedSkills"]
                    if item["id"] == "implement-spec"]
        self.assertEqual(len(selected), 1, "Select the pinned upstream reference once")
        item = selected[0]
        self.assertEqual(item["path"], "skills/engineering/implement-spec")
        reference = ROOT / lock["path"] / item["path"] / "SKILL.md"
        self.assertEqual(item["hash"], "sha256:" + hashlib.sha256(reference.read_bytes()).hexdigest())

    def test_evidence_validator_accepts_two_ticket_dag_and_rejects_cycles(self):
        tickets = [
            {"id": "ticket-a", "dependencies": [], "acceptanceHash": "sha256:" + "a" * 64},
            {"id": "ticket-b", "dependencies": ["ticket-a"], "acceptanceHash": "sha256:" + "b" * 64},
        ]
        evidence = {
            "specHash": "sha256:" + "c" * 64,
            "tickets": tickets,
            "ticketDagHash": ticket_dag_hash(tickets),
            "planReviewHash": "sha256:" + "d" * 64,
            "implementationConfirmationHash": "sha256:" + "e" * 64,
            "independentAgentsHash": "sha256:" + "f" * 64,
            "independentReviewHash": "sha256:" + "1" * 64,
            "gitPermissionsHash": "sha256:" + "2" * 64,
            "planReviewStatus": "passed",
            "implementationConfirmationStatus": "confirmed",
            "independentAgentsStatus": "supported",
            "independentReviewStatus": "supported",
            "gitPermissionsStatus": "confirmed",
        }
        validate_implement_spec_evidence(evidence)
        cyclic = dict(evidence)
        cyclic["tickets"] = [
            {"id": "ticket-a", "dependencies": ["ticket-b"], "acceptanceHash": "sha256:" + "a" * 64},
            {"id": "ticket-b", "dependencies": ["ticket-a"], "acceptanceHash": "sha256:" + "b" * 64},
        ]
        cyclic["ticketDagHash"] = ticket_dag_hash(cyclic["tickets"])
        with self.assertRaisesRegex(ImplementSpecEvidenceError, "implement-spec-ticket-cycle"):
            validate_implement_spec_evidence(cyclic)


if __name__ == "__main__":
    unittest.main()
