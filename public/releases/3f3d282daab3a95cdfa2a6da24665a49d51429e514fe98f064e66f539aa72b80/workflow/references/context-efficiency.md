# 上下文提效来源与边界

仅维护时核对，日常不加载。2026-11-06 核验以下固定版本；SHA-256 按 UTF-8/LF。仅提炼方法，未导入上游正文/实现、安装行为或运行时依赖。

## qodo-ai/qodo-skills（MIT）

[Skill](https://github.com/qodo-ai/qodo-skills/blob/91651ae7d34e1dc1cc88d237c822e580387d324e/packages/qodo/skills/qodo-review/SKILL.md) · [LICENSE](https://github.com/qodo-ai/qodo-skills/blob/91651ae7d34e1dc1cc88d237c822e580387d324e/LICENSE)

原文 SHA-256：`2ab17ed2af80959ce17e4dfe0eb20bd621d1dfda86f367b4ca0641f745416977`；许可：`4a1eb770532b2425b79e2995ac80d0aff92527f0aa72427f06a09f5da6f13919`。

吸纳成熟切片检查点、同时至多一个自动检查点、完整/增量/复用及无进展停止自动循环；不导入远程审查服务、自动提交或额外调度。停止重审不免除必要覆盖/修复，复用保留未关闭项。

## tomzx/agents（MIT）

[Skill](https://github.com/tomzx/agents/blob/e9c4674dd39717e185bed40b7b964d3b794be89d/skills/review-pr/SKILL.md) · [LICENSE](https://github.com/tomzx/agents/blob/e9c4674dd39717e185bed40b7b964d3b794be89d/LICENSE)

原文 SHA-256：`17e31ba9f7f527426cf476b6f56b8285a1c29dc0dcd8717a3d3378512130c523`；许可：`6bf8777a0c68115318a97ccfa2a3dd7b041a9986f1e69b2a834387f0b1120553`。

吸纳内容指纹和简短差异回传；不套仅看改动行/HEAD 的复用。SelfWorkflow 仍覆盖未提交增量、消费者、规则和环境失效，不增 review.yaml 账本或发布动作。

## Context Engineering Agent Skills（MIT）

[context-compression](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/9ff0c99108b36d3b886defd825d8ac1f47dba374/skills/context-compression/SKILL.md) · [LICENSE](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/9ff0c99108b36d3b886defd825d8ac1f47dba374/LICENSE)

原文 SHA-256：`ab4fd1e1046db339d83ead5089d4cb9d9c487232945d4ff6be90e08a03f6cfea`；许可：`65bc33b0759a48b980962833b12bcb820404da9f5256bff39c00e89471bcf209`。

吸纳新摘要与既有状态增量合并、准确路径/标识、恢复问题核对；失效授权/版本/结论须替换，不只追加。不新建平行账本，不套窗口阈值、压缩比例或自动派 Agent。

2026-11-11 将同版上游登记为维护用 submodule，未升级此前核验的 commit。以下路径相对维护仓库根：`dependencies/upstream/context-engineering`；来源身份、Git tree、所选原文与许可 SHA-256 固定在 `dependencies/locks/context-engineering.lock.yaml`。另核验[评测参考](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/9ff0c99108b36d3b886defd825d8ac1f47dba374/skills/context-compression/references/evaluation-framework.md)，hash 为 `2584d5ab6c1322c0df7a581a6f5354be052bae077e16f76ef7c772f750ef81d2`。SelfWorkflow 的适配由[上下文模块](../modules/context.md)和[效果验证](context-compaction-evaluation.md)单独负责，不加载/分发上游整包，不引入自动 hooks 或第二套交接文件。

维护升级按需进行：

1. `git submodule update --init -- dependencies/upstream/context-engineering` 恢复仓库固定来源。核对 `.gitmodules` URL、gitlink、干净工作树、commit/tree、选定文件与许可的 UTF-8/LF hash。此研究来源不进入普通初始化/导出复制清单，`skill sync/check` 不代验其 Git 身份。
2. 需要升级时只在该 submodule fetch；先比较锁定 commit 与明确候选 commit 的选定原文、评测参考、许可及必要引用变化，再选用完整 commit。上游更新仅提供候选方法，不自动替换当前规则或授权。
3. 在干净来源切到已审候选，更新 gitlink、锁和本节版本/hash；仅将相关变化合并到现有 owner，不照搬上游触发阈值、压缩率、安装或调度。按效果验证与紧凑性审查验收，再执行仓库 `skill sync/check`，交付完整新 release；在途任务沿原绑定。

## rtk-ai/rtk（Apache-2.0）

[输出恢复文档](https://github.com/rtk-ai/rtk/blob/8268663fac0ba7e92e3a9e1f6e2cf943b659c07a/docs/guide/getting-started/configuration.md) · [LICENSE](https://github.com/rtk-ai/rtk/blob/8268663fac0ba7e92e3a9e1f6e2cf943b659c07a/LICENSE)

原文 SHA-256：`942a245a3d589284fc2fbe830e1198918cace49d3a2fef055dee373827a2a873`；许可：`33f694a31d9f9df3e292a9413a3cdb0113fa72698e2c719f657ff6b53165dcc4`。

仅借鉴截断后恢复原输出、避免重跑的机制，未复制其代码或文档；区分展示截断、存储完整性与入口可用性。旧输出不是当前状态，容量/期限不支持永久完整承诺。不安装 CLI、hooks、索引或缓存服务。

已有 ECC 渐进检索来源沿[搜索来源](search-guidance.md)，不重复引入固定轮数/评分。context-mode 仅作研究对照，未引入其 ELv2 实现或旧版路由。上游输出字节缩减不等于本任务 token、费用或延迟收益；本地部署效果需另验。

## MIT 许可

前三份许可合并保留版权声明：

```text
MIT License

Copyright (c) 2025 Qodo Team
Copyright (c) 2025 Tom Rochette
Copyright (c) 2025 Context Engineering Agent Skills Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
