# SelfOpenWiki 可选适配

仅在用户选择该知识库为来源或发布目标时读取；生成与审查普通本地 Wiki 不依赖此服务。宿主没有该连接时继续本地候选，服务相关动作标未核实。

## 已连接的 SelfOpenWiki

首次调用 `openwiki_status`，按返回路径与版本确定唯一正式根、可用能力及恢复状态。当前一致性读取／个人发布要求 MCP ≥0.1.2、schema 2 和 external-agent 协议；读操作只需已验证的安全读取能力，发布才要求 `externalAgent.ready=true` 及完整生命周期能力。旧版或漂移只做状态／故障诊断，不默切 legacy 或 provider。

读取用 `openwiki_read` 先取目录／revision，再在真实大小限额内分批读页并绑定 `expectedWikiRevision`；不猜根目录、Claim 或 hash。单页超限时记录读取缺口；有独立授权的本地快照只能按实际字节与目录 hash 核对并披露方式，不冒称 native 正文读取成功。恢复状态不一致时沿后端恢复能力处理，不能绕过拒绝去读写正式根。

只有明确选择正式更新，且 status 的个人生命周期／候选／独立审查／CAS 能力可验证时，才使用当前 `selfopenwiki:personal-openwiki-v1`：

1. 按授权来源执行实际 prepare，核对全部被接受的来源与确认值；拒绝、越界或敏感来源不走别名绕过。
2. `openwiki_begin` 绑定 status 根与当前 revision；`openwiki_submit_plan` 列必要页面及导航，取得真实队列与隔离候选路径。
3. 串行 `openwiki_next_page`，Writer 只写返回 PageJob 分配的候选页。修改／撤回 Claim 前 `openwiki_inspect_page_claims` 读完整集合；`openwiki_submit_page` 只提交 sparse decisions，保留未要求变更的 Claim。
4. `openwiki_finish` 按真实 candidate receipt、实际 C7 reviewPackage、独立 Reviewer 回执和 CAS 发布推进。使用工具返回的 binding、generation 和 hash，不伪造回执或自行替代 C7-owned hash。
5. 仅 `status: complete` 且 `published: true` 报正式完成；其他状态沿 `nextAction` 继续或报告具体缺口。冲突重读受影响页，保留并发内容；实际语义或范围变化才重新确认。

读取不要求发布能力，也不创建更新事务。候选／更新所需规则由真实 work package 提供；已有兼容 adapter 时复用其操作细则。后端不可用仍可做已授权的独立研究或候选，不能静默换协议、provider 或 Wiki。不要直接复制稿件进正式根。
