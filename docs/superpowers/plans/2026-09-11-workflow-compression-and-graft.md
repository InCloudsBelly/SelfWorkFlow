# SelfWorkFlow 工作流压缩实施计划

状态：用户已确认实施；Batch A 最小修复已写入，验证证据见本次任务；未提交、未安装、未推送。

## 当前批次

本包只授权 Batch A：压缩启动上下文、拆分按需模块、更新运行时打包和测试，并保持现有 CodeGraph 行为不变。Graft Provider 是 Batch B，必须另建完整设计/TEA/Plan、独立 Review 和用户确认；本包不授权 Graft 代码、Submodule、Installer、Worker、缓存或 Wiki Hook。

## Batch A 精确范围

允许修改的文件和符号固定为：

- `WORKFLOW.md`；
- 新增 `workflow/modes/light.md`、`workflow/modes/full.md`、`workflow/modes/deep.md`；
- 新增 `workflow/modules/code.md`、`review.md`、`knowledge.md`、`artifacts.md`；Graft 不在本批次模块清单中，显式要求时只返回 `unsupported/unverified`；
- `src/selfworkflow/adapters.py` 的 `_CORE_PATHS`，通过既有 `build_runtime` 打包新文件；不新增 loader、manifest 信任根或 Catalog 解析器；
- `tests/behavioral/test_workflow_matrix.py`；
- 必要的既有 conformance 文本断言适配：`tests/conformance/test_matt_skills_foundation.py`；
- 新增 `tests/unit/test_workflow_compression.py`；
- `catalog/modules.yaml` 中既有自动 Grill/TEA/代码 Review 的 operation predicate，以及 `workflow/pipeline.yaml` 中仅对行为变更启用 TEA 的条件；
- `src/selfworkflow/installer.py` 的 `_managed_instruction`，仅补充安装后普通任务读取已打包 mode/module 的中文引导；
- 本设计、TEA 和实施计划三份文档：
  `docs/superpowers/specs/2026-09-11-workflow-compression-design.md`、
  `docs/superpowers/specs/2026-09-11-workflow-compression-test-design.md`、
  `docs/superpowers/plans/2026-09-11-workflow-compression-and-graft.md`。

不允许修改 lifecycle/evidence Schema、Review 独立性、用户配置、凭据、Wiki 数据、公共 API/ABI、持久化格式、全局宏、共享热路径、项目调用者、Graft 实现或 CodeGraph 路由/历史文件。Catalog 仅允许收窄本批入口已声明的自动 Grill/TEA/代码 Review operation predicate，不得新增模块或改变其他路由。不得自动删除用户已有状态。

owner 层是工作流入口、模式/模块加载和 runtime 打包。更窄替代是保留一个大入口，但无法达到上下文目标。本批次不新增公共接口、持久化格式、全局构建变体或跨项目调用者。回滚只能使用基线绑定的逐文件补丁，不得 reset 或批量删除。

## 顺序与门禁

1. 记录当前分支、dirty/untracked 清单、文件 hash、runtime manifest、`WORKFLOW.md` 字符基线和三份本批次文档 hash。明确记录并排除既有 Graft untracked 文档：`docs/providers/graft.md`、`docs/superpowers/plans/2026-09-10-graft-provider.md`、`docs/superpowers/specs/2026-09-10-graft-provider-design.md`；不暂存、不修改。
2. 以本三份文档、`workflow/protected-rules.yaml`、相关 Catalog 条目、当前项目规则和完整变更清单组成预实施 Review 包。预实施使用一个 `plan-integrated-review` 独立临时 SubAgent；落地代码 Review 才使用 Standards/Spec 两个独立临时 SubAgent。两者复用现有 Review/Host-attestation Schema、校验器和回执，不新增字段。完整包记录 approved request、`requestHash`、`planHash`、stage、attempt、capability snapshot、验收图、按序 Review Skill manifest、统一 package hash，以及所有 committed/staged/unstaged/untracked/deleted/binary/file-mode 项；worktree/index 字节和 mode 分开绑定，并单独记录基线到 Batch A 的 task delta。
3. Critical/Important 全部解决，所有 Minor 写 disposition；文档变更后重新做整包 Review。未通过不得实施。
4. 用户明确确认实施。此前只允许只读检查和设计/计划文档修订。
5. 在新增测试前，先运行并记录既有基线，区分环境/既有失败：

   ```powershell
   .venv\Scripts\python.exe -m unittest tests.behavioral.test_workflow_matrix tests.unit.test_catalog -v
   ```

   然后只新增测试并运行 RED：

   ```powershell
   .venv\Scripts\python.exe -m unittest tests.unit.test_workflow_compression -v
   ```

   预期失败必须是缺少拆分入口、模式/模块文件或字符阈值，不得是环境或语法错误。

6. 通过 RED 后实施最小入口/模块/打包修改，重复同一命令 GREEN，再运行：

   ```powershell
   .venv\Scripts\python.exe -m unittest tests.behavioral.test_workflow_matrix tests.unit.test_catalog tests.unit.test_workflow_compression -v
   .\scripts\verify.ps1 -Suite conformance
   .\scripts\verify.ps1 -Suite behavioral
   .\scripts\verify.ps1 -Suite installer
   ```

7. 只执行临时目录的 package、installer plan/verify/dry-run；不执行真实安装、push 或 Batch B。用临时目录锁定 `tiktoken==0.11.0`、`o200k_base`、`disallowed_special=()` 对分别绑定的基线/候选 UTF-8 输入产生 proxy token 收据，候选不超过基线 70%；缺少 tokenizer 时不得声称 token 降幅，只能报告 `unverified`，不阻止核心压缩验收。
8. 对最终完整 diff 做 Standards/Spec 独立 Review，核对逻辑闭环、失败路径、侵入、中文文档、用户改动和无关修改；清理临时 SubAgent。模型必须按本地 Review 配置实际回传，缺失/不匹配即 fail-closed。运行新鲜完成门禁，报告所有 skipped/unverified。

## Batch B 交接

Batch A 完成后，另建 Graft 任务。新包必须纳入现有 `2026-09-10-graft-provider` 设计/计划的精确 hash，补齐 owner/文件/符号、公共与持久化边界、具体 RED/GREEN/native 命令、侵入预算、唯一 Catalog ID、能力证据和 CodeGraph 遗留迁移。未通过独立 Review 和用户确认前不得实现或安装。

## 回滚

任一阶段失败都保留证据并停在失败阶段，只恢复本计划实际修改的文件；恢复前必须校验全部目标的 expected-postimage/current-hash，恢复后复核基线 hash、file mode 以及新增/删除语义；发现用户并发修改或 hash 不符就停止并报告，绝不覆盖。不得删除 Graft 文档或清理 CodeGraph 遗留状态。任何未计划发现记为相邻改进，先完成当前批次。
