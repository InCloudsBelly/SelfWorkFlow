# knowledge 发布前复审

日期：2026-10-31。基线为 `a47e5f67a06f86724d66cec4f02834859288cbba`。用户授权审查、写入 Skill 并推送远程；沿用本任务原有规则绑定与同一独立 Reviewer。审查覆盖本方案的规则、运行时代码及必要的预初始化恢复/SymPy 接入依赖，未把工作区全部改动自动纳入提交。

## 已修复的发布阻碍

1. **旧来源快照误判恢复记录（P2）**：真实来源验证每次创建新 snapshot 路径，崩溃遗留快照或 retained 初始化副本中的合法 `state.json` 会被当成未知事务记录，导致重试永久拒绝。实际 fresh-path 用例先因 `restore_required` 失败，再修复为通过。仅在 tmp 直接子目录的已知来源/初始化位置，以目录身份、受信路径和字节判定；snapshot 要求完整来源 treeHash，retained 要求三份控制包及全部既有候选字节。只允许原本合法的部分 Skill/来源复制；未知控制记录、链接、篡改均保留并拒绝。
2. **空 Wiki 初始化拒绝（同根 P2）**：没有 Markdown 时，按文件键推导的目录集合遗漏了合法空候选骨架。`mode=init` 恢复用例实际 RED→GREEN；孤儿与 retained 共用私有初始化校验，只允许 generation-1 候选及其祖先空目录，要求候选目录真实存在。未知空目录继续拒绝。
3. **源码指纹包含未提交 Viewer 内容**：本地 Viewer 已有其他任务继续修改，原指纹不代表将推送的干净提交。交付验证改用隔离工作区与固定 submodule 提交；只按实际交付字节重新绑定 compatibility，公开工具 schema/字段和 v1 持久格式保持。

同一 Reviewer 已补齐 HEAD 比较范围，复核并关闭两项同根 P2；SymPy 固定来源、许可证/资源闭包与其入口也已补审，无剩余可行动问题。机械交付证据由主 Agent 执行取得，不把静态审查称为测试通过。

## 范围与验证边界

保留十二项指标、权重、4/90/95 门槛、来源核对、独立集中评价与最终 CAS；v7 数学解释/参数规则、共享观察和定向复核已经写入源码及自包含 Skill。旧评价保留原版本绑定。

仅交付当前完整 release `106a8a850dd867c911d5c3ff98a1a6a3c2187d06de4b1dd24478ab9e5398dffb` 及其必要源码；已提交的旧 release 保持，其他本地未提交历史 release 保留。本地 Viewer 图像/公式等脏改不提交，gitlink 沿用 `8d5ec949b5bb12d11d3fed463784a3384f3b3c5d`。

验证在 `D:/SelfWorkFlow/.worktrees/k1031` 进行，固定依赖从已有 Git 对象检出，不复制脏 Viewer 字节；复用现有 node_modules 只读依赖及已物化的 OpenWiki 身份材料，不执行依赖重装、上游/helper 重建或全局安装/宿主重启。原长路径/工作区外隔离尝试未通过准备阶段，不计入消费者通过证据；最终采用工作区内可写隔离目录。

## 执行证据

- TypeScript：隔离目录 `tsc --noEmit -p tsconfig.test.json` 退出0；为真实进程中断测试在同一隔离目录执行 `tsc -p tsconfig.json`，退出0，没有覆盖主工作区 dist。
- 恢复文件：43/43通过，含两个原反例及未知目录、来源篡改、缺包、缺候选、额外控制记录等保留/拒绝分支。
- 隔离邻接回归：六文件179个不同用例。首轮167通过、12失败，原因是隔离目录缺少子进程需要的编译 dist 或 `.work/openwiki`；该准备错误不计作行为 RED。隔离编译并只读复用已有物化 OpenWiki 后，仅重跑这12项，全部通过，其余100项明确未在该定向命令重跑。最终179个不同用例均取得通过结果。
- 隔离文档消费者/SymPy闭包及实际知识打包：2/2通过，临时参考文件已恢复。
- 来源兼容校验：同步/异步完整manifest相等，`assertPersonalCompatibility`通过，公开tool bindings严格相等，基础Skill hash保持 `47f2c3b99da439d40c7f4062eb17b8c802403fd19dd1ca7c87455aa9c715df3b`。实际交付adapterSetHash=`sha256:4dc4992e630310c36092b98424f7e93effa91a92a3a6c0f1a9010adfa6997abc`，module manifest=`sha256:f2c84718f064fb56ba60f2553fb9001a7c789066ff79ea1addb9bd175ac288c5`；仅更新两项源码绑定，其他manifest字段保留。
- 在隔离目录执行 `skill sync --repository .` 退出0、`status=synchronized`，生成445份文档，revision仍为上述106a8a版本；旧revision未改删。

最终隔离 `skill check --repository .` 退出0、`status=verified`，revision与sync一致。发布前以Git tree对象核对主工作区暂存内容与已验证隔离目录的暂存内容；提交仅包括当前完整release及必要源码/测试/审查记录，不纳入本地Viewer改动和其他未提交历史release。自有源码diff空白检查通过；不可改写的上游随包资源保留原始字节与许可，不对旧release手工清理空白。

校验命令的JSON结果保留在本地忽略的 `build/knowledge-publish-2026-10-31/`，不作为live能力证据发布。

底层 helper 微测沿用前日报告，不重新宣称端到端成文质量/耗时 A/B 已完成；本轮未验证随交付 Viewer 的数学实际显示，也未颁发新的 live 能力证据。远程源码发布不等于运行服务已经切换。
