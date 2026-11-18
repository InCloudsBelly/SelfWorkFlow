# 只读参考：git-policy.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
forbiddenRoots: [.venv, build, dist, artifacts, logs, runtime, .pytest_cache, htmlcov]
allowedSensitiveNames: [.env.example, .env.sample]
databaseSuffixes: [.sqlite, .sqlite3, .db-wal, .sqlite-wal]
sizeBytes: {warning: 1048576, failure: 5242880}
allowlist:
  - path: dependencies/upstream/anthropic-skills
    objectHash: ca45fc496a3436251f191354091d557da31c15b5
    reason: Pinned official Anthropic skill-creator reference for workflow maintenance
    owner: SelfWorkFlow maintainers
    expires: "2030-12-31"
  - path: dependencies/upstream/matt-pocock-skills
    objectHash: 4ae2317ddb22b046e26455e4f9c9b3aaaf62212d
    reason: Pinned Matt Pocock engineering skills foundation used by SelfWorkFlow
    owner: SelfWorkFlow maintainers
    expires: "2030-12-31"
  - path: dependencies/upstream/tea
    objectHash: a2819f62fc1b56486d223895eaa50578b490f2f5
    reason: Pinned official TEA source used by the optional V3 test-quality adapter
    owner: SelfWorkFlow maintainers
    expires: "2030-12-31"
  - path: dependencies/upstream/ponytail
    objectHash: 96608e078b2d5ea607c5c3b8b5a54d1c1fba6846
    reason: Pinned official Ponytail source used by the code-task workflow adapter
    owner: SelfWorkFlow maintainers
    expires: "2030-12-31"
  - path: dependencies/upstream/ui-ux-pro-max
    objectHash: 3a13158ff1f32156cbe144108de48eda2ecaed9a
    reason: Pinned UI UX Pro Max methods and search resources for interface design
    owner: SelfWorkFlow maintainers
    expires: "2030-12-31"
  - path: dependencies/upstream/composio-skills
    objectHash: be2a406907dbc61b73e6827ded415c96139d13a2
    reason: Pinned Composio content research writer reference
    owner: SelfWorkFlow maintainers
    expires: "2030-12-31"
  - path: dependencies/upstream/obsidian-skills
    objectHash: 3ccff5338ea700537839b21900aa5358a0402c98
    reason: Pinned Obsidian Markdown Bases and JSON Canvas format references
    owner: SelfWorkFlow maintainers
    expires: "2030-12-31"

````
