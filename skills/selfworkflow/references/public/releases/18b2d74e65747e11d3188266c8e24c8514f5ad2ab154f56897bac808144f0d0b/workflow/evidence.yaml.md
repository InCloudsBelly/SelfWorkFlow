# 只读参考：evidence.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
requiredFields:
  - classification
  - capabilities
  - selectedSkills
  - acceptanceCriteria
  - changes
  - review
  - verification
  - skipped
  - residualRisks
verification:
  unverifiedFrom:
    - not-run
    - partial
  completionEligible:
    - passed
    - not-applicable

````
