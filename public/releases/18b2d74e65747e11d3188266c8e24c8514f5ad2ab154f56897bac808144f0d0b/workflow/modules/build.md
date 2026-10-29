# 编译缓存保护

- 编译检查复用用户现有增量编译环境，允许必要的正常增量更新，不为验证便利使共享缓存失效。执行前核对最近正常构建的命令、日志或配置，保持项目、Target、平台/架构、Configuration、工具链/SDK、全局宏以及 PCH、Unity、Live Coding 编译支持一致；无法确认时先报告，不盲目试编。
- 优先同环境下最窄充分的增量构建。UE 的 `-Module` 只限制本次动作范围，不隔离共享 Intermediate/PCH；不得擅自添加 `-NoLiveCoding`：它会改变 `WITH_LIVE_CODING`，与 IDE 配置来回切换可使共享头/PCH 失效。保留 Live Coding 编译支持不等于执行 Live Coding 或 Hot Reload。
- 未获明确授权，不执行 Clean/Rebuild，不删除或清空 Intermediate、Binaries、PCH、DDC 等产物/缓存，不通过切换全局构建选项或改写构建规则“修复”编译检查。
- 共享头、构建规则或工具链等必要变化仍可能合法触发大范围重编；预计有此影响时，先说明原因、范围和代价并取得用户确认。不同编译环境的验证使用已确认不会覆盖原产物/缓存的隔离输出；不能保证隔离时不执行，保留 `not-run/unverified`，不得把跳过说成通过。
- 实际动作量显著超出改动影响范围时，不反复切换参数重试；检查 makefile 失效原因、全局定义与 PCH 变化，安全可行时暂停本 Agent 发起的构建并报告，不终止用户或其他任务的构建。
