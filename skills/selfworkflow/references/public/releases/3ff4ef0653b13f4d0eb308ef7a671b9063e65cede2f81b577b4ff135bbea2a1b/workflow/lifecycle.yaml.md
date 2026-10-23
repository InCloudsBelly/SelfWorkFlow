# 只读参考：lifecycle.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
phases:
  - discovered
  - capability-checked
  - classified
  - designed
  - planned
  - implemented
  - reviewed
  - verified
  - completed
executionStatuses:
  - active
  - paused
  - blocked
  - failed
  - completed
verificationStatuses:
  - not-applicable
  - not-run
  - partial
  - passed
  - failed
capabilities:
  states:
    - supported
    - unsupported
    - unverified
  standardNames:
    - skill-discovery
    - independent-context
    - command-execution
    - filesystem-read
    - filesystem-write
    - test-execution
    - user-confirmation
    - task-resume
    - knowledge-read
    - knowledge-write
derivedVerification:
  unverifiedFrom:
    - not-run
    - partial

````
