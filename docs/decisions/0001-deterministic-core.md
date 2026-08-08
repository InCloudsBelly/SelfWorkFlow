# Decision 0001: deterministic core and optional integrations

Status: accepted

SelfWorkFlow keeps lifecycle, classification, protected invariants, Catalog routing, evidence, installation plans, and release decisions deterministic and vendor-neutral. Agent-specific instructions, Superpowers, and knowledge backends are replaceable adapters selected through explicit capability and provenance records.

Git is the only development source. Runtime snapshots are generated artifacts; machine state, transactions, backups, credentials, OAuth state, databases, and temporary evidence do not become workflow source. A missing optional knowledge backend does not block code delivery. Missing required process capability pauses modifying work rather than silently degrading.

This boundary permits upstream Agent and OpenWiki evolution without embedding maintainer-local paths or model reasoning in durable workflow knowledge.
