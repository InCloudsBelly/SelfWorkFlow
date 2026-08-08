---
name: kg-c7-openwiki
description: Use when the user explicitly asks an Agent to query, organize, propose, or update a personal project knowledge base through the C7OpenWiki MCP tools.
---

# C7OpenWiki Knowledge Maintenance

Call `openwiki_status` first for every request and treat its actual initialization, authentication, model, recovery, and capability fields as authoritative. Never infer a tool or model capability from this Skill.

Prepare local code and text paths with `openwiki_prepare_sources`; show the returned file metadata and risk boundary, then bind both returned manifest ID and confirmation text. A changed file invalidates the old confirmation. Never send credentials, private keys, token stores, `.env`, or unsupported binary documents.

Use `openwiki_query` for reads and proposals. It does not publish formal Wiki content, but OAuth refresh and temporary transaction state may change. Use only unique, verified specialized Skill IDs in request order; the backend owns its required base Skill.

Call `openwiki_update` once only after the user has reviewed the final scope and explicitly confirmed writing. Set literal `confirmedByUser: true`; this is a misoperation guard, not authentication. Report the backend's actual model evidence and terminal state. Do not claim compare-and-swap revision support unless the live contract exposes and verifies it.

Close minor issues autonomously. Preserve provisional items as follow-up. Resume Grill-me only for blocking missing evidence, expanded scope, or a user decision. A review-attention result is already published when its `published` field says so; attempt only bounded evidence-based closure and require a new confirmation for another update.
