---
name: cpp-core
description: Use for reading, designing, implementing, debugging, maintaining, or reviewing C and C++ code. Load this compact core for C++ tasks, then read only the specialist reference files justified by ownership, template/type, concurrency, ABI, performance, safety, build, native-debugging, or Unreal Engine signals. Do not trigger for ordinary documentation or non-C++ tasks.
---

# C++ Core

提供不依赖任何本地工具或厂商 Agent 的 C++ 推理核心。外部 CodeGraph、LSP、编译器、Sanitizer、调试器和深度审计器都是可选 Provider；缺失时不得伪造其结果。

代码阅读优先级：若当前工作目录已绑定且索引新鲜的 CodeGraph，先用 CodeGraph
进行符号、调用关系、依赖和导航查询，再用 `rg` 做精确字面搜索、读取未纳入索引的文件和最终文本核对。
CodeGraph 缺失、过期、未覆盖目标文件或运行时不可用时，明确标记限制并回退 `rg`；不得隐式同步/重建，也不得把过期结果当作新鲜证据。

新对话第一次命中代码任务时，先做一次当前工作目录的 CodeGraph 状态检查。
若绑定存在但索引过期，向用户提供“更新并使用”“不更新但使用现有索引（过期只读）”
和“本对话不使用 CodeGraph”三个选项；更新/重建必须单独确认。用户选择后绑定为本对话偏好，
后续代码理解优先使用 CodeGraph，不重复询问，除非项目或 Provider 身份变化或用户主动切换。
更新失败或能力未验证时保留 `unverified`/过期标记，不能静默把 `rg` 结果冒充 CodeGraph 证据。

只读分析只应用推理核心和直接命中的按需参考；不会因此进入修改、构建、调试器或完整 Design/Plan/Review 流程。

## 核心流程

1. 固定目标、平台、标准版本、编译器/构建模式与用户已有改动。
2. 对 Bug 固定 failure envelope：期望、实际、精确输入、首次观察点、last-good / first-bad、复现与恢复状态。
3. 构造最小完整切片：producer → 持久状态/资源 → transform → consumer。区分 root-cause owner 与 detection point，在最早拥有数据及不变量的责任层修复，禁止下游补偿掩盖上游错误。
4. 明确所有权、生命周期、值类别、类型边界、状态不变量和错误传播；再检查 UB、整数/边界、异常安全、并发、ABI、性能与构建风险。
5. 采用最小侵入修改：保持稳定底层接口，除非共享需求和兼容性证据证明必须下沉；保护用户已有修改。
6. 计算缓存、生成物、序列化数据、checkpoint 与下游 consumer 的失效/重建范围。
7. 用最窄测试层证明 Red/Green、直接路径、失败路径、边界、状态不变量和受影响共享路径。构建、Sanitizer 或运行期证据未执行时标记 `unverified`。

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
