# 2026-11-02 来源升级与适配

本次按各 submodule 的配置分支或远端默认分支取固定快照：11 个来源中更新 6 个，另 5 个已是最新；不持续追随分支。完整 hash 见 Gitlink 与 `dependencies/locks/`。

| 来源 | 新提交 | 本次适配 |
| --- | --- | --- |
| TEA | `a2819f6` | 3.6.0；保留既有九个逻辑 ID，将 ATDD 映射到 automate/red、CI 映射到 framework/ci |
| Matt Pocock | `4ae2317` | 8 个新提交；implement-spec 每个 ticket 使用新上下文，仍须显式选择 |
| Ponytail | `96608e0` | 5.3.3；更新 debt/help 边界，保留当前任务范围与写入授权 |
| Anthropic | `ca45fc4` | 上游仅 mcp-builder 变化，已选 skill-creator 正文未变 |
| UI UX Pro Max | `3a13158` | 更新数据与查询脚本，验证 Nuxt UI 查询 |
| OpenWiki | `d3b953e` | 0.7.2；刷新零补丁来源绑定，安装与 inspect 统一 Node >=22.22.0 |

Composio、Obsidian、Scientific、CodeGraph UE 与 Viewer 已是最新。Matt 新增的实验方法未自动接入默认入口；TDD、diagnosing 正文在本次八个提交中未变。已有来源许可与选定文件 hash 继续随锁校验，LF/CRLF checkout 不改变方法身份，实际正文漂移仍拒绝。

## 加载与紧凑性

比较已发布基线 `0ad1061f3fa1` 与新 release `e27269fc300e` 的 Unicode 字符数，不据此推算 token 或触发频率。

| 实际加载段 | 原字符 | 新字符 |
| --- | ---: | ---: |
| 仓库入口 | 1445 | 1445 |
| 安装入口 | 1405 | 1405 |
| TEA 方法 + headless + 所选 ATDD 入口 | 8546 | 8249 |
| implement-spec 方法 | 4547 | 4581 |

默认路由未扩张。TEA 仍显式触发；ATDD 只打包 red 子树和所需共享资源，JIT 只返回指定文件；删除重复入口副本。保留旧 API 到新路径的边界映射，不重写上游正文。既有不可变 release 保留，续接不重绑。

## 验证与边界

- Python 适配 50 项逐项通过（含公共 ATDD 宏根闭包）；Git 策略的 3 项小型 fixture 通过。整仓历史对象扫描已中止，不声称通过。
- Wiki 来源契约 31 项、setup/manage 9 项、MCP 集成 41 项通过；上游与 MCP 构建、TypeScript 类型检查通过。
- 独立 clone 的 core/knowledge 安装用例均通过，复用已有 Python 依赖；原工作区 Git 配置 hash 未变。将既有三份 Wiki 草稿覆盖到隔离源码后，构建、类型检查与同组 41 项集成测试也通过，随后恢复候选源码。
- Skill sync/check 通过；UI 新 release 查询返回 2 项结果；CodeGraph 来源身份校验通过。
- 原工作区在合回前核对 10 个父仓库草稿文件及 Viewer 的 11 个文件；草稿不混入本次提交，派生入口按合回后的来源重新生成。

首次 linked-worktree 安装 fixture 改写了共享 `core.worktree`，该次 normal 安装失败；已恢复 10 个配置路径并核对全部 11 个原目录与 HEAD，草稿字节未变。最终安装复验改用独立 clone 与独立子模块元数据，仅复用本地对象及依赖；不将首次失败算作通过。

构建与最终安装验证使用隔离目录。没有更新全局工作流安装、宿主 MCP 注册或服务，也没有重建 CodeGraph 索引、清空共享编译缓存或发布 Wiki。
