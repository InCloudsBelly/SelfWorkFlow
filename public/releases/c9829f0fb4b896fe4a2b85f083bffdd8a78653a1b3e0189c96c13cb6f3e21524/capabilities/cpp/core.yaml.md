# 只读参考：core.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
id: cpp.reasoning
moduleId: cpp-core
status: supported
providerKind: prompt-skill
entrypoint: skills/cpp-core/SKILL.md
operations: [analyze, design, plan, implement, debug, review]
boundaries:
  - no-tool-or-runtime-claims
  - no-debug-execution
  - verification-evidence-required

````
