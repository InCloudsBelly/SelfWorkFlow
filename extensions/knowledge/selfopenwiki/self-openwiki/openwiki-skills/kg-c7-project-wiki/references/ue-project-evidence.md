# Kuaishou UE / C++ 项目证据

## 定位入口

按实际仓库 manifest 验证后使用以下常见入口：`Engine/Source/Runtime|Editor|Developer|Programs`、插件 `.uplugin`、模块 `<Module>.Build.cs`、Target、Commandlet/Builder、配置与 Shader include。公共 API 与内部实现分别检查 `Public/`、`Private/` 和 `*_API`；测试通常在被测模块 `Private/Tests/`。

稳定页面只写仓库相对路径和符号。本机绝对路径只属于事务来源信息，不进入 canonical 结论。

## C++ / UE 证据维度

- 生命周期/所有权/GC：`UPROPERTY`、`TObjectPtr`、owner、委托/timer/句柄清理与析构闭环；不用 `std::shared_ptr` 管 UObject。
- 静态初始化：全局/静态阶段不能依赖尚未初始化的 UObject 子系统或同步资产加载；记录延迟初始化入口。
- 线程：UObject GameThread 约束、异步捕获、回调线程、锁、任务依赖和对象寿命。
- 性能：Tick、热循环、容器复杂度、同步加载、字符串与每帧/每实例/渲染路径开销。
- 网络/蓝图：Replication 注册与条件、RPC 校验、Blueprint 暴露、默认值和兼容性。
- 模块/API：`.Build.cs`、循环依赖、导出、Editor/Game 隔离、平台宏。
- 序列化/ABI：字段顺序/对齐、Custom Version、Unversioned schema、RHI/Shader 参数、跨 DLL 与旧 Binary。

模式命中不是已发生缺陷。记录命中代码、成立条件、实际后果和验证证据。

## 最小影响链

```text
changed symbol/config/asset
  -> direct callers or generated/Blueprint references
  -> module/platform/serialization/Shader or asset contract
  -> persisted artifact/cache/package
  -> runtime, old binary, tool or downstream consumer
```

回答 owner、直接/间接影响清单的获得方式、空结果证据、需重建/重跑阶段、最小验证以及未执行项。不得为了写 Wiki 擅自编译、Cook、重存资产、同步 P4 或修改源码。
