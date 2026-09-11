# SelfWorkFlow 工作流压缩 TEA 测试设计

状态：用户已确认实施；核心、conformance、behavioral、installer 验证已通过，等待修复后最终独立 Review。

本测试集只覆盖压缩批次；Graft Provider 由后续独立测试包负责。

## 测试矩阵

| 编号 | 场景 | 证据 |
| --- | --- | --- |
| A1 | 启动入口、模式文档、模块文档、进度/失败报告和生成的项目文档叙述均为中文；路径、代码、符号、命令、错误原文、模型名、Skill 名和协议字段可原样保留 | 解析与文档行为测试 |
| A2 | 启动入口、`writeTask=false`、禁止编辑/副作用和能力/证据门禁始终加载；Light 只加载 Light 与命中的任务模块，不加载 Full/Deep 专属内容 | 文件清单与越权写入测试 |
| A3 | Full 只读取 Full 与命中模块，并仅在行为 `implement`/`debug` 路由 `design-grilling`、`tea-test-design`、代码任务的 `review-code-review`、`tea-test-review`；`plan-integrated-review` 仍按 Full/Deep 计划门禁；行为变更 TDD | Catalog `route_modules` 真实矩阵 + 模式文档顺序 |
| A4 | Deep 只读取 Deep 与命中模块，并只执行一次 `design-grill-me`/frontier；不重复 Full 的 grilling 路径 | Catalog `route_modules` 真实矩阵 + Deep 路由清单 |
| A5 | `tea-atdd`/`tea-trace`/`tea-nfr` 默认不加载，显式请求且阶段匹配才加载；显式 Graft 只返回 `unsupported/unverified` | 正触发测试 |
| A6 | 非代码任务不加载 code/Graft；只读任务省略写入实施流程但仍保留 `writeTask=false`、禁止编辑和禁止副作用；Full/Deep 不加载无关模块；显式模块也不得绕过 operation/write selector | 误触发与越权失败测试 |
| A7 | runtime 打包所需模块缺失或不可复制时 fail-closed；manifest 为每个拆分文件保存 hash；已有 artifact/installer 漂移门禁继续负责发布时校验。Agent 按需读取属于入口契约，不在本批次新增 loader 或新的信任根 | runtime 缺失源 + manifest hash 测试，既有 installer 漂移测试 |
| A8 | 项目 Review Skill 为主策略，通用 Review Skill 只补充；保护规则不可覆盖 | 优先级测试 |
| A9 | 硬约束行为生效：禁止伪造 capability/Review/test/evidence；禁止静默降级；凭据/敏感信息保护；用户改动保护；未授权副作用/不可逆操作阻止；完成前必须有新鲜证据；关键确认；任务外异常停止；Scope/Plan/侵入边界；Review/Verify/知识中文落地 | 正反行为与 fail-closed 测试 |
| A10 | CodeGraph 默认入口、显式调用、安装提示、README、历史文档、配置/缓存、既有 Graft 文档和本批次外文件 hash 均不因压缩批次改变；本批次不出现活跃 Graft 路由 | 保持性断言 |
| A11 | 用严格 UTF-8、拒绝 BOM、Unicode code point 算法重算固定 hash 基线；启动入口不超过基线 30% 且不超过 10,500；用 `tiktoken==0.11.0`、`o200k_base`、`disallowed_special=()` 对分别绑定的基线/候选输入产生 proxy 收据，候选 token 不超过基线 70%；缺失或漂移则 token 结果为 `unverified`，不阻止核心压缩 | 字符/hash 测试与测量报告 |
| A12 | 固定顺序 `Review → 用户确认 → TDD`；确认前编辑代码/测试、越界编辑或跨预算均失败关闭 | 顺序门禁测试 |
| A13 | 冲突分类、无独立 SubAgent、模型不匹配、Reviewer 清理失败、包漂移、旧证据、伪造收据和未授权副作用均为 `unverified`/blocked | 失败路径测试 |
| A14 | Review 复用现有 Review/Host-attestation Schema 和校验器；不新增字段；现有回执的 provider、receiptId、dispatch/operation nonce、execution mode/identity、level/decision、freshness、输入/输出 hash 缺失或错配时保持无效 | 既有 Schema/失败测试 |

## TDD 与命令

先记录既有测试基线，再新增 `tests/unit/test_workflow_compression.py`，一次运行全部新增行为测试取得 RED；预期失败按测试 ID 来自缺少拆分入口、模式/模块文件、路由冲突、越权写入、manifest 漂移或字符阈值，不能是环境/语法错误：

```powershell
.venv\Scripts\python.exe -m unittest tests.unit.test_workflow_compression -v
```

实施最小修改后，重复同一命令作为 GREEN，再运行：

```powershell
.venv\Scripts\python.exe -m unittest tests.behavioral.test_workflow_matrix tests.unit.test_catalog tests.unit.test_workflow_compression -v
.\scripts\verify.ps1 -Suite conformance
.\scripts\verify.ps1 -Suite behavioral
.\scripts\verify.ps1 -Suite installer
```

Installer 只做测试内临时目录的 plan/verify/dry-run，不执行真实用户安装。Token 预研使用临时目录锁定 `tiktoken==0.11.0`，不写入仓库依赖。文档测试检查路径、链接、中文输出和生成 runtime manifest。任何跳过项写明原因并标为 `unverified`。

## Review 完成条件

预实施 Review 使用 `plan-integrated-review` 的一个独立临时 SubAgent；落地代码 Review 使用 `review-code-review` 的 Standards/Spec 两个独立临时 SubAgent；两者不是同一门禁。两者均复用现有 Review/Host-attestation Schema、校验器和既有回执字段，不新增 Schema。完整包仍绑定 approved request、`requestHash`、`planHash`、stage、attempt、capability snapshot、验收图、设计/TEA/Plan、项目规则、按序 Review Skill manifest、规则/文件/文档哈希，以及 committed/staged/unstaged/untracked/deleted/binary/file-mode 完整工作区清单；另有与基线比较得到的精确 Batch A task delta。worktree/index 字节和 mode 分开绑定。所有 Minor 必须有处置。
