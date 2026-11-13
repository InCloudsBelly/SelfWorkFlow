# 只读参考：safety.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
id: cpp.safety
reasoningStatus: supported
runtimeValidationStatus: unverified
entrypoint: skills/cpp-core/references/safety.md
positiveSignals: [undefined-behavior, integer-overflow, bounds, aliasing, iterator, exception-safety]
falseSignals: [formatting-only]
testObligations: [empty-min-max, hostile-length, invalid-enum, failure-invariant]

````
