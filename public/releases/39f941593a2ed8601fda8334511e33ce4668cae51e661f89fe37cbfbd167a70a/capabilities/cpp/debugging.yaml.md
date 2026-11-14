# 只读参考：debugging.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
id: cpp.debugging
reasoningStatus: supported
debugExecutionStatus: unsupported
entrypoint: skills/cpp-core/references/debugging.md
positiveSignals: [native-crash, stack-trace, core-dump, sanitizer, symbols]
falseSignals: [frontend-console-error]
testObligations: [original-red, fixed-green, adjacent-failure, state-invariant]
executionBoundary: debug.execute-requires-separate-authorization

````
