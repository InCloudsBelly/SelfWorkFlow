# 只读参考：ownership.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
id: cpp.ownership
reasoningStatus: supported
runtimeValidationStatus: unverified
entrypoint: skills/cpp-core/references/ownership.md
positiveSignals: [ownership, lifetime, raii, pointer, reference, use-after-free, memory-leak]
falseSignals: [managed-language-gc-only]
testObligations: [normal-destruction, partial-failure, move-state, delayed-callback]

````
