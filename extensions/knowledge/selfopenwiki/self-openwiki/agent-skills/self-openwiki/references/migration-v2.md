# SelfOpenWiki v2 迁移说明

## 适用范围

v2 适用于已有 Markdown Wiki、旧 C7 receipts，或需要把旧个人 Wiki 设计迁移到
OpenWiki 官方 PageJob/Claim 生命周期的仓库。迁移不会把个人 Wiki 合并进
SelfOpenWiki，也不会修改 `upstream/openwiki`。

## 迁移边界

1. 把现有个人 Wiki 的绝对 Git 仓库根作为 `wikiRoot`；不能传入子目录、软链接、junction，
   也不能让 MCP 自动初始化 Git。
2. 先读取当前 Wiki revision，再通过 `openwiki_begin` 创建或恢复 Run。
3. 旧页面、frontmatter、Claim sidecar 或来源结构如有差异，只生成候选 migration report，
   不直接覆盖原始 Wiki 或其 `.git`。
4. 通过 `openwiki_submit_plan`、PageJob、Claim inspection 和 sparse decisions 形成候选；
   仍由 C7 candidate receipt、独立 Review receipt 和 CAS publication 进入正式 Wiki。
5. `status: complete` 且 `published: true` 之前，不得报告迁移完成。失败时保留候选和原始
   Wiki 快照，用户可修复后 resume，或使用明确确认的 abort 放弃。

Claim 迁移以页面旁的 `.claims/<page>.json` sidecar 为 authoritative source，并校验
其中的 `pageVersion` 与页面内容 hash 一致。缺失 sidecar 表示该页暂无 Claim；格式错误、
链接路径或过期版本会阻止写入。迁移工具只提交针对已读取快照的 sparse decisions，不会
把客户端传入的 Claim 列表当成新的 authoritative source。

## Git 与运行时

个人 Wiki 的 commit、branch、remote、fetch、push、reset、checkout 和 merge 都属于
外层用户 Git 操作。SelfOpenWiki 只读取 Git 根身份和内容，并把事务、PageJob、Claim
决策、receipt 与恢复状态写到同级 `<wikiRoot>.selfopenwiki`。

上游 OpenWiki 的更新只改变 SelfOpenWiki 绑定的 Submodule revision、v2 零补丁 manifest、
兼容性清单、适配器和本 Skill。个人 Wiki 的迁移报告与正式发布不写入 Submodule。
