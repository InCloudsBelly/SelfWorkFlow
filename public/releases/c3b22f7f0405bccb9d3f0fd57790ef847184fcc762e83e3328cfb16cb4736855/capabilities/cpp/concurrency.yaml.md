# 只读参考：concurrency.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
id: cpp.concurrency
reasoningStatus: supported
runtimeValidationStatus: unverified
entrypoint: skills/cpp-core/references/concurrency.md
positiveSignals: [thread, lock, race, atomic, memory-order, async, coroutine]
falseSignals: [single-threaded-event-order]
testObligations: [interleaving, cancellation, shutdown, owner-destruction]

````
