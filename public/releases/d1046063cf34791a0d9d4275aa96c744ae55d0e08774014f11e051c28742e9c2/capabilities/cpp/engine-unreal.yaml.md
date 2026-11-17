# 只读参考：engine-unreal.yaml

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
schemaVersion: 1
id: cpp.engine.unreal
reasoningStatus: supported
entrypoint: skills/cpp-core/references/unreal.md
positiveSignals: [unreal-engine, ue5, uobject, uht, ubt, game-thread, render-thread, rhi-thread]
falseSignals: [generic-cpp-without-unreal]
testObligations: [target-platform-config, unity-non-unity, uht, gc-lifecycle, thread-boundary]
nativeValidationStatus: unverified

````
