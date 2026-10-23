<!-- selfworkflow:documents -->
# SelfWorkflow 公共入口

用户顶层任务实际读取本入口一次，选择下方版本；子任务、独立 Reviewer、阶段切换和上下文续接继承主任务的 documentRoot 与 revision，不另选 latest。缺失或不一致的绑定应报告委派者。

[读取本任务规则](releases/a66bd50d06fe04abd94668541927117ded87511dc1552804e97a29bc783b8ea1/WORKFLOW.md)

revision: `a66bd50d06fe04abd94668541927117ded87511dc1552804e97a29bc783b8ea1`

链接所在目录即本任务 documentRoot。相对链接从声明它的文件解析；逻辑规则路径以 documentRoot 为根。只按需读取文档，不运行安装器、构造账本或注册原生 Skill。版本目录不可原地修改；旧任务继续使用原版。
