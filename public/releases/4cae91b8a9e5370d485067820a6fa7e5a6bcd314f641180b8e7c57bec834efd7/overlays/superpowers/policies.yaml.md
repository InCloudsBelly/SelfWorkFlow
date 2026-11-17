# 只读参考：policies.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
missingSource:
  modifyingTask: pause
  readOnlyTask: disclose-and-continue
  silentDowngrade: forbidden
grillMe:
  activation: explicit-only
  highComplexityAction: recommend-to-user
  postReview:
    skill: brainstorming
    independentContextRequired: true
runtime:
  loading: selected-stage-only
  mutateUpstream: forbidden

````
