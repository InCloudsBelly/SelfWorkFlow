# 只读参考：abi.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
id: cpp.abi
reasoningStatus: supported
nativeValidationStatus: unverified
entrypoint: skills/cpp-core/references/abi.md
positiveSignals: [abi, odr, layout, vtable, export, serialization-compatibility]
falseSignals: [source-only-private-refactor]
testObligations: [producer-consumer, layout-baseline, old-data, old-binary]

````
