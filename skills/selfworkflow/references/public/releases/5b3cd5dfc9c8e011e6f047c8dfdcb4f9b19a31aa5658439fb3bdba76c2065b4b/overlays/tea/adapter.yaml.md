# 只读参考：adapter.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 3
sourceId: tea
sourcePath: dependencies/upstream/tea
artifactRoot: artifacts/test-quality
workflows:
  - id: teach-me-testing
    upstreamId: bmad-teach-me-testing
    root: skills/bmad-teach-me-testing
    support: {sourceIntegrity: supported, adapterSupport: unverified, runtimeCapability: unverified, behaviorEvidence: unverified}
  - id: atdd
    upstreamId: bmad-testarch-atdd
    root: skills/bmad-testarch-atdd
    support: {sourceIntegrity: supported, adapterSupport: supported, runtimeCapability: unverified, behaviorEvidence: unverified}
  - id: automate
    upstreamId: bmad-testarch-automate
    root: skills/bmad-testarch-automate
    support: {sourceIntegrity: supported, adapterSupport: unverified, runtimeCapability: unverified, behaviorEvidence: unverified}
  - id: ci
    upstreamId: bmad-testarch-ci
    root: skills/bmad-testarch-ci
    support: {sourceIntegrity: supported, adapterSupport: supported, runtimeCapability: unverified, behaviorEvidence: unverified}
  - id: framework
    upstreamId: bmad-testarch-framework
    root: skills/bmad-testarch-framework
    support: {sourceIntegrity: supported, adapterSupport: supported, runtimeCapability: unverified, behaviorEvidence: unverified}
  - id: nfr
    upstreamId: bmad-testarch-nfr
    root: skills/bmad-testarch-nfr
    support: {sourceIntegrity: supported, adapterSupport: supported, runtimeCapability: unverified, behaviorEvidence: unverified}
  - id: test-design
    upstreamId: bmad-testarch-test-design
    root: skills/bmad-testarch-test-design
    support: {sourceIntegrity: supported, adapterSupport: supported, runtimeCapability: unverified, behaviorEvidence: unverified}
  - id: test-review
    upstreamId: bmad-testarch-test-review
    root: skills/bmad-testarch-test-review
    support: {sourceIntegrity: supported, adapterSupport: supported, runtimeCapability: unverified, behaviorEvidence: unverified}
  - id: trace
    upstreamId: bmad-testarch-trace
    root: skills/bmad-testarch-trace
    support: {sourceIntegrity: supported, adapterSupport: supported, runtimeCapability: unverified, behaviorEvidence: unverified}

````
