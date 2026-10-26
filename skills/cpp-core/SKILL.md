---
name: cpp-core
description: Use for reading, designing, implementing, debugging, maintaining, or reviewing C and C++ code. Load this compact core for C++ tasks, then read only the specialist reference files justified by ownership, template/type, concurrency, ABI, performance, safety, build, native-debugging, or Unreal Engine signals. Do not trigger for ordinary documentation or non-C++ tasks.
---

# C++ Core

提供不依赖任何本地工具或厂商 Agent 的 C++ 推理核心。CodeGraph、LSP、编译器、Sanitizer、调试器和深度审计器是辅助能力；缺失时不得伪造其结果。

图谱绑定、新鲜度、失败与生命周期统一遵循 [workflow/modules/codegraph-read.md](../../workflow/modules/codegraph-read.md)；本方法不另做状态检查、初始化或询问偏好。只读已绑定项目图并复核源码，工具缺失如实 unverified；不将 rg、AST 或图谱当构建/运行证据。

只读分析只应用推理核心和直接命中的按需参考；不会因此进入修改、构建、调试器或完整 Design/Plan/Review 流程。

## C++ 判定

责任层、故障切片、状态/失效、最小改动和测试归[代码方法](../code-quality/SKILL.md)，同版已读直接复用，不重复启动流程。
固定平台、C++标准、编译器/构建模式；检查所有权、生命周期、值类别、类型边界、UB、整数/边界、异常安全、并发/内存序、ABI、性能与构建风险。工具只提供证据，不能代替消费者、真实构建或运行验证。

## 按需参考

只读取命中信号的文件，不要预载全部内容：

- 资源、指针、引用、悬空、泄漏：`references/ownership.md`
- 模板、Concept、重载、推导：`references/type-system.md`
- 线程、锁、原子、内存序、异步：`references/concurrency.md`
- ODR、布局、虚表、导出、序列化兼容：`references/abi.md`
- 分配、缓存、拷贝、SIMD、复杂度：`references/performance.md`
- UB、整数、边界、别名、迭代器、异常：`references/safety.md`
- 编译、链接、宏、PCH、工具链：`references/build.md`
- Native Crash、堆栈、符号、Sanitizer：`references/debugging.md`
- UBT/UHT、UObject、模块、Game/Render/RHI 线程：`references/unreal.md`

## Provider 与副作用边界

- 代码图、LSP 或 AST 是检索证据，不自动成为真实构建、ABI 或运行期语义证明。
- 查询前检查 Provider 绑定与新鲜度；索引初始化、同步、重建、attach、launch、表达式求值和内存修改是独立操作，必须遵循宿主授权。
- 普通 Debug 只执行 `debug.reason`；不得偷偷启动或 attach 调试器。
- Forensic/Heavy 审查仅在高风险且用户明确确认后推荐和执行；普通 Review 不加载。

## 交付

报告修改归属、逻辑闭环、失败路径、安全/侵入性、失效范围、真实验证证据，以及所有未验证项。不能把命令成功、同进程瞬态状态或 Fake Provider 测试写成真实消费者行为已通过。
