# 只读参考：policies.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
classification:
  complexity:
    C0: Pure question answering or read-only lookup.
    C1: Explicit small or mechanical change.
    C2: Multi-file feature, local refactor, or design choice.
    C3: Architecture, migration, cross-system change, or substantial unknowns.
  risk:
    R0: No state change.
    R1: Easily reversible local change.
    R2: Public interface, persistent data, compatibility, performance, or security boundary.
    R3: Irreversible action, production release, credentials, or major data risk.
globalMinimum:
  complexity: C0
  risk: R0
thresholds:
  requiresFullDesign:
    anyDimensionAtLeast: 2
  suggestGrillMe:
    anyDimensionAtLeast: 3
    combinations:
      - complexity: C2
        risk: R2
upgrades:
  ambiguity:
    increment: 1
    maximum: 3
  projectMinimum:
    mayIncreaseGlobalMinimum: true
    mayDecreaseGlobalMinimum: false
  user:
    mayIncrease: true
    mayDecrease: false
  recordRejectedDowngrade: true
capabilityGate:
  acceptedStates:
    - supported
  pauseStates:
    - unsupported
    - unverified
  missingReportHandling: pause
  ordering: lexical
  pause:
    status: paused
    code: required-capabilities-unavailable
    fields:
      - missingCapabilities
      - purposes
      - reasons
      - recommendations
      - oneTimeAlternatives
      - nonWaivableBoundaries
    oneTimeAlternatives:
      requiresExplicitUserAuthorization: true
      allowsManualVerification: true
      allowsAutomaticDowngrade: false
    nonWaivableBoundaries:
      - one-time alternatives require explicit user authorization
      - required capability cannot be treated as supported without evidence

````
