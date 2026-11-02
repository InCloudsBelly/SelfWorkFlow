# 只读参考：build.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
id: cpp.build
reasoningStatus: supported
nativeBuildStatus: unverified
entrypoint: skills/cpp-core/references/build.md
positiveSignals: [compile, link, macro, preprocessor, toolchain, cmake, pch, unity-build]
falseSignals: [read-only-code-explanation]
testObligations: [target-build, non-unity-boundary, generated-code, critical-macro]

````
