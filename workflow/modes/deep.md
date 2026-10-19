# Deep 模式

适用：高复杂度、高风险、边界不清或要求深度分析。Deep 只增加真实问题的分析深度，不自动扩大文档、Agent 数量或启动 contract Host。

沿用 Full 的紧凑设计/测试/计划、自审、已有授权复用、行为 TDD 与新鲜验证；增加与实际风险相关的边界、恢复、并发、安全或性能检查，不为线性任务扩张测试架构。
完整 grilling 和 TEA（含 T3、ATDD、trace、NFR）均只按用户显式点名启用，不因 Deep、测试等级或项目默认自动加载，也不重复执行 Full 的访谈。

普通中间文档不单开审查；重大架构、安全、持久化、不可逆风险或显式要求才前置 plan-integrated-review。所有模式取消双 Review：交付前一个独立 Reviewer 综合 Standards/Spec 和测试证据，修复复核只检查受影响项并持续收敛。继承主 Agent 模型/推理配置，不读取专属模型配置。

纯分析一次独立 Review；机械文档同步窄自审。Reviewer 只读已绑定 package/evidence，不调用 CodeGraph/provider、验证、写入或下级 Agent；主 Agent 按 codegraph-read / codegraph-update 维护项目级全局图。缺少必要能力如实 unverified，不冒充通过。
契约防伪/回执不省略；用户禁止编译/测试时记 not-run/unverified。范围/owner/侵入预算/关键风险变化重新确认，不能因 Token/次数预算中止未完成任务。
