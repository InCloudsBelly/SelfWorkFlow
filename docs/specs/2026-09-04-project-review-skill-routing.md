# 项目级主 Code Review Skill 覆盖路由

状态：已实现，待最终回归与发布审查。

## 目标

允许每个项目为代码 Review 声明项目专属的主 Skill；在 Full/Deep
代码修改的双独立 Review 中，Standards 与 Spec 两个 Reviewer 都收到同一份
经过路径和内容 hash 校验的 Skill 清单。项目 Skill 覆盖通用 Review Skill 的主职责，
通用 Review Skill 仍作为 supplementary 能力保留；两者都不能替换 SelfWorkFlow
的 TEA、验证、授权和安全规则。

## 配置边界

项目可提交 `.selfworkflow/review.yaml`：

```yaml
schemaVersion: 1
additionalReviewSkills: # 兼容旧字段名；语义为 project Review override
  - id: project.ue5
    path: .agents/skills/kg-ue5-code-review/SKILL.md
    contentHash: sha256:<skill-file-sha256>
    required: true
```

`path` 必须是项目根目录下的相对正斜杠路径；不接受绝对路径、路径穿越、反斜杠
或 reparse/symlink 逃逸。Skill 文件必须是 UTF-8 可读取的普通文件，实际字节
hash 必须等于 `contentHash`。条目顺序就是加载顺序，`id` 不得重复。配置不存在
表示本项目没有 project Review override，不触发扫描、下载或询问。

## 会话与 Review 行为

新项目对话的首个代码分析、修改或 Review 任务只检查一次该配置；项目身份变化
或用户明确要求重新检查时才重检。状态报告为 `absent`、`loaded` 或 `unverified`，
并绑定项目根和每个 Skill 的 hash。不会因为发现 `.agents/skills` 目录就自动扫描。

Full/Deep 的代码修改仍调用通用 `mattpocock:code-review` 的 Standards 与 Spec
双轴。代码派发使用独立的 `independent-code-review` 模式和代码 Review subject
契约；Grill 设计派发继续使用独立的 `independent-design-review` 契约。若配置中至少
有一个 project Skill 校验通过，project Skill 是 primary，通用 Skill 是 supplementary；
两个 Reviewer 都收到：

1. 通用 Review 输入；
2. 同一份按配置顺序排列、标记 primary/supplementary 的 Skill manifest；
3. 每个 project Skill 的原文和 `contentHash`；通用 Skill 由固定 lock 提供。

两个轴必须收到完全相同的项目 Skill manifest 和对应字节；当前版本不支持按轴
拆分项目 Skill 清单，避免两个 Reviewer 的输入不一致。

项目 Skill 的覆盖只改变 Review 专项判断的主次，不得改变 protected rules、审查范围、
严重度、独立性要求、TEA 或完成门禁。
同一项目配置中的重复 `id`、路径漂移或 hash 冲突 fail closed。`required: true` 的 Skill 缺失、漂移
或无法加载时，双 Review 标记 `unverified` 并暂停完成；可选 Skill 失败只记录为
`unverified` 和残余风险，并从实际 Reviewer manifest 中排除，不伪称已执行。

Light、非代码任务和仅设计/问答任务不因本配置自动加载额外 Skill。项目配置不改变
全局 Catalog、流程深度、TEA 阈值或默认模型。

## 验收与测试

- 合法配置可读取，条目顺序保留，完整配置和 hash 绑定；
- 缺失配置返回 `absent`，不扫描目录；
- 绝对路径、穿越、终端 `..`、反斜杠、重复 ID、hash 漂移和 symlink/reparse
  均 fail closed；
- Full/Deep 代码 Review 的两个轴收到相同顺序、角色和相同 hash 的项目 Skill；
- Light、非代码和项目未配置时不加载；
- 项目 Skill 不得覆盖 protected rules，配置变化使会话绑定失效。

Host 在构造时接收项目根与会话身份；新项目对话的首个匹配 implement、debug 或显式
代码 Review 中自动调用
`start_project_review_session()`，后续阶段复用该会话。Full/Deep 代码 Review 再调用
`build_code_review_context()`，由 `dispatch_code_review()` 将结果交给双 Review 派发，
由 Host port 把同一上下文分别交给两个独立 Reviewer。Grill 后的设计 Review
保持原有设计门禁，不携带项目 CodeReview Skill。会话使用已校验的不可变 Skill
快照；用户要求重检、项目身份变化或 Host 检测到配置/文件漂移时，必须结束旧会话
并新建会话，不得继续沿用旧绑定。
非 Grill 的代码 Review 使用 Host 的 `dispatch_code_review()` 入口；它复用同一
会话绑定和上下文构造，并分别派发 Standards 与 Spec 两个独立 Reviewer，不允许
绕过项目 Skill 路由。

该能力属于 Agent/Host 的项目适配策略；没有支持双独立上下文的宿主时，仍按
SelfWorkFlow 的 `unverified` 规则处理，不伪造 SubAgent 或 Review 证据。Host
应在同一进程中使用校验器返回的 `build_code_review_context()`（其内部使用
`reviewer_manifests()` 与 `reviewer_skill_bytes()`），把相同的两份输入分别交给
Standards 和 Spec；CLI 只输出 manifest，不输出 Skill 原文。该函数是 Host
接入 Matt `code-review` 双 SubAgent 的边界，不声称自身创建 SubAgent。
