# Code Implementation Contract Increment Baseline

- Fixed original commit: `08640be26b051354615941a11a65342a9a953297`
- Staged diff: empty
- Protected status entries: 54
- Normalized protected status SHA-256: `06e8e19461c8f0faf300adc5b06379a75ab98074bb3ae1cfd7fc7db3ce1500bd`
- Normalized tracked binary diff SHA-256 against the fixed commit: `cf720b2b72efaa1304910cbd29e7f8c79b5cc3e1a09358aba1490a080299e02c`

The three active design/test/plan documents and this baseline document are excluded from the protected-status digest because they are the current documentation package. All other entries below predate the first test or policy edit for the code-implementation-contract increment. Hashes are complete file-content SHA-256 values. `M` means tracked modified and `??` means untracked.

```text
M  be177cd40eddaed2de2a9c8eea98190fee56f19d78b9742c7fa3e83377e38158  README.md
M  a824724bbcf7cd4f8d1be70755240891697c1a78155ab43d101f9aa4f39c80af  WORKFLOW.md
M  c205380e42a1963ffafa55dfd18fd1500b86f1e8dcfead835bc5d941af69eea5  catalog/domains/code-quality.yaml
M  b1fc4c0cff61761bef25e452c4d788bb78d64fda11617525da52b17225a28254  catalog/domains/workflow.yaml
M  7b23523448b6bc87399c0226b7b3cd5a32d1f9eb13abe8415ea2a29730ffa4e2  catalog/modules.yaml
M  b8811ff28cab0d3e5cd76c82caa46b90c21490def74ed3df49da8ee1c2dd665c  catalog/v3/domains/workflow.yaml
M  fce61cba21f6236b5a52bf0b0457c578e237bc728484172dbb26df3dd4ec29dc  catalog/v3/index.yaml
M  964000674821f4f6db21b6a66d65f32bd5c10cbabf5536188355be858c04cc60  catalog/v3/modules/cpp-core.yaml
M  ce6def56e4b77fa8740c20e317e21a6f340db031ad130f097c8063eac4d5b029  docs/provenance/code-quality-baseline.md
M  98722daad52cc81c7fb4774d1ac7ec445fead0aecc44f4975e01ea43a3711dfd  extensions/knowledge/c7-openwiki/SKILL.md
M  107948165d12359c5c15d5ae1bddd112b5afc1153e243a66062a3bc316abec96  extensions/knowledge/c7-openwiki/adapter.yaml
M  19115443ef84c10e0bcf836c8802b3c150d00b48cd92c9b7a880a0421017aaf4  extensions/knowledge/c7-openwiki/provenance.yaml
M  dfe403c151f45a9b98d7860e3f686b4b73ef6becd564c589e24c601d0518d105  extensions/knowledge/c7-openwiki/tool-contract.json
M  db0aafec27a08d5ae832ea658fcc3c5bdd3b661bc13fc44ba860274888546b62  schemas/install-plan.schema.json
M  e5ce4edb2089afea0d0d491288976284f9bb767e96fd51338ac9cb8962e95129  scripts/install-selfworkflow.ps1
M  e5f18ade89eef9c12dd33e3d4747cbe3e58c271ef27913510aa9b1124e3c2ade  skills/cpp-core/SKILL.md
M  67208493466ac8a9ad3317dff7607da4ff8ffefa6f39dc8d00e68c012ab934ba  src/selfworkflow/adapters.py
M  8df308718e9dee8664fb7719c8fe5feb8b49000f8aea7a96313fb5808cada01d  src/selfworkflow/c7_openwiki.py
M  d89bcfb8a982dbd336b72a914b3237b21a499e5f823882b0be8fb267f2a5e706  src/selfworkflow/cli.py
M  05ce291582ae7866aa663b87c70a40259b076e0e0ea2ac586d212868ef894762  src/selfworkflow/installer.py
M  8088b96627e6583b35d991e9d37dddfb51ac982b6b1aa732ea4f2295364ccee0  src/selfworkflow/knowledge.py
M  8ab538b2c2af9c93f09db5249fcf4c63d093f42b3ee1a43e2ce5bc41889a81b0  tests/acceptance/test_install_sandbox.py
M  f99a1b90700f0387a10f10f6607e9fc90f124730b67f22eafeee2db77830e137  tests/behavioral/scenarios/code-quality.yaml
M  4a5c3b28315b1866f891f1d43c25aee9b8763bd20365fc71853bae311a91f42d  tests/behavioral/test_code_quality_scenarios.py
M  0502b2eb8d1ddc953a6064cf089eca7bc8fff00e1d243da2d2d6c67fca00118f  tests/behavioral/test_v3_cpp_workflow.py
M  9c5d4128a58e73544f24aef69b0758e7e7b39441a221f16c18128673aff28b5c  tests/behavioral/test_workflow_matrix.py
M  3b458ef8ffc17024b319093e73d24b8cb13454f5b93b690fbc67ef97c0f78227  tests/conformance/test_c7_openwiki_adapter.py
M  fb9fe808b22f26cb1fa7f70e585e9b191f5a1bb3ae2af9ca0178770e612078c8  tests/conformance/test_runtime_snapshot.py
M  905fadebb99a4ab230eef1639ad5d9699bcc1ae0b6c9291597970cbe5ebe96f9  tests/installer/test_apply.py
M  7cef56538ad28c433d06397cfc642fda697c58f05836419d65dea76a2f01509a  tests/installer/test_one_click.py
M  7f16a1886915bbd140bb743c445c5655efbcd86b6232d9b37d75d2f84790cd7b  tests/unit/__init__.py
M  44e89c5d59ff9cf3b35383cc403bf57ddbd670cc30856e0c1bf4450de7db33fa  tests/unit/test_knowledge_contract.py
M  89e2bf057463651ec37bb2cece26c2d2f563174b40a9424c9c35d7a215f7022d  tests/unit/v3/artifact_fixtures.py
M  29d31fcd4e5aa2f48dbd989f87d8c67dd09eed4f67ec75211452ca21b858d9e5  tests/unit/v3/test_catalog.py
M  d34ffc3c90c6f37f232e0f55956a2d0f8564854a3154cb71029dfcca4950553a  tests/unit/v3/test_cpp_router.py
M  7afaed7d7ff8259a6f3398bd71e71e9c1a6776c44d6ffdbf72a07c9d624c8334  tests/unit/v3/test_pipeline.py
M  10957b62d773d9d75308e4fb6528bba15ecc7b954071c65631e5994e41fe3f4a  tests/unit/v3/test_plan_graph.py
M  6abe69a1db58c1db3b6ec57b3ce8e4bc4e8cb6256547ffe8395cad549ce9185e  workflow/v3/pipeline.yaml
?? 9d6f0954024a17f7913cc92d52e387deae2d55fe9b2a397ac974ecc882d82b19  catalog/v3/domains/knowledge.yaml
?? 82fe9672033004bdd6726ba3992b4c43c85fededf4b00e7d61593d5aaf10a925  catalog/v3/modules/knowledge-propose.yaml
?? 0a6f1e8e1a33ae31e7650c8b8aa1ed283d0388ebc53577fcbc72a5781b745b38  catalog/v3/modules/knowledge-read.yaml
?? adf327131e78777efe5388fd33deac8ec7acbd1544e0ecfe016844c949b5e25c  catalog/v3/modules/knowledge-update.yaml
?? c910a756f66b19f1f45f551649f4bec75000cf9787dca9379925c52cf9fe0e02  catalog/v3/modules/plan-integrated-review.yaml
?? a8296ee13361f7e10882da2b690d41f62e80e5e540acd6ee1d55c93eccc84507  docs/reviews/2026-08-10-c7-openwiki-runtime-adapter-conformance.md
?? a31fdcd8c7627924d3e8a2e33503ac12770d8d3a3741ee44cacd77a10aed0a6d  docs/superpowers/plans/2026-08-10-c7-openwiki-runtime-adapter.md
?? 95be26c02b036ac0994cef6cbc80e602224a241ab042042b8feae47ef532a03e  docs/superpowers/plans/2026-08-10-codex-selfworkflow-bootstrap.md
?? e31d9f20329adecc3feb0c1fd35f7544b29a7b68de6162bd25982c72fbb7e9fe  docs/superpowers/plans/2026-08-10-general-skill-activation-boundary.md
?? f3481ee086e2fb2ed4807b63be4a547fb2ab05f9d1f153d3979cb4680fa2da2d  docs/superpowers/plans/2026-08-11-lightweight-knowledge-handoff.md
?? 76b715b0311f6bb459ff0714b7ac7eb135d609b4606d413fb9f0f6047f92aa9c  docs/superpowers/specs/2026-08-10-c7-openwiki-runtime-adapter-design.md
?? 911046e0a0a1e8642f2c2076d2afcaab8ef152025e6b81896391af1a188266b9  docs/superpowers/specs/2026-08-10-codex-selfworkflow-bootstrap-design.md
?? b1d676a8ee86280b592982d2d23f38590d7d8f0dd2e7f45823971fe0e1f546ad  docs/superpowers/specs/2026-08-10-general-skill-activation-boundary-design.md
?? 06d8e910d0d321411fac3c88714ad8f345e1a161b054cbde340bf20b87d53c43  docs/superpowers/specs/2026-08-11-lightweight-knowledge-handoff-design.md
?? 36fafa55fa55ba8e8661b7bde230b8ab629134277a412eb420b6a6f16c4383b2  src/selfworkflow/codex_mcp.py
?? e72da44d3b5420170b449dc98b11bd4e5e438c8ee6b81986498b791a96400903  tests/unit/test_codex_mcp.py
```

The status digest is recomputed by excluding these four documentation-package paths, sorting in Git's porcelain order, joining lines with LF, and adding one terminal LF:

- `docs/superpowers/specs/2026-08-11-progress-and-pre-implementation-review-design.md`
- `docs/testing/2026-08-11-progress-and-pre-implementation-review-test-design.md`
- `docs/superpowers/plans/2026-08-11-progress-and-pre-implementation-review.md`
- `docs/reviews/2026-08-11-code-contract-baseline.md`

After the final user confirmation and before the first test edit, persist the tracked baseline with:

```powershell
New-Item -ItemType Directory -Force build\audit
git diff --binary --output=build/audit/code-contract-before.patch 08640be26b051354615941a11a65342a9a953297 -- .
Get-FileHash -LiteralPath build\audit\code-contract-before.patch -Algorithm SHA256
```

Final audit uses the same fixed commit and verifies every non-allowlisted path above still has its recorded hash. Allowlisted paths are the three policy/Skill files, two source-lock Catalog files, five named test/scenario files, and the four documentation-package files. No V3, Schema, installer implementation, C7OpenWiki, README, C++ capability, or unrelated test path is allowlisted.
