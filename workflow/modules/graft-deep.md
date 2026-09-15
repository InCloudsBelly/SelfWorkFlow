# Graft 专题 Deep 模块

- 一个稳定 `conversation-id` 只绑定一个 `topic-id`。首次 Deep 必须同时提供二者；成功后绑定写入项目 `./selfworkflow/graft-deep/.conversation-bindings/`，只保存 conversation hash，不保存原始 ID。后续同一对话必须继续传同一 `conversation-id`，可省略 `topic-id`，由 SelfWorkFlow 自动恢复；指定不同 topic 立即失败关闭。
- 新对话先发现已有 Topic；用户选定后才绑定。用户选择不使用 Deep 时记录 `no-deep-topic`，该对话不调用 Graft；该选择与 Topic 绑定一样保持不变，不自动互相切换。
- 全局 `graft/` 保留非 Deep structural Map；专题 Deep 使用项目内 `./selfworkflow/graft-deep/<topic-id>/graft`，不创建临时 Git 仓库，不扫描全仓库。
- Deep 必须接收非空、项目内、无 Reparse Point 的相对文件清单，并将每个文件作为官方 Graft 的重复 `--only-dir`；当前项目全局 Map 与专题上下文分开。
- C/C++ 清单会沿显式文件中的 quoted local `#include` 做有限闭包，保持首次出现顺序；`.inl`、`.ipp` 按 C++ include 依赖纳入上下文，不扩展为整个目录。官方 Graft 仍负责实际解析；当前这两类文件在适配器中标为 `context-only`，不得伪报其已有官方结构符号节点。
- 未被官方 Graft 声明支持的文件（例如 UE `.usf/.ush/.hlsl`）在 Deep 入口直接失败关闭，不启动无效构建；这类文件改用源码读取或 `rg`，避免把不支持的输入混入 Tree-sitter。
- 仅主 Agent 可调用官方 `provider graft-deep` bridge；这是 Graft Deep 专用入口。Reviewer 不得调用 Graft/provider。Deep 的触发可以由当前模式自动决定，但模型不是用户输入：主 Agent/Host 必须把本次对话的当前 model/reasoning-effort 注入本次进程，使用 `SELFWORKFLOW_HOST_CURRENT_MODEL` 和 `SELFWORKFLOW_HOST_CURRENT_REASONING_EFFORT`；CLI 的同名参数仅保留为内部兼容入口，若与 Host 上下文冲突则失败关闭。桥接不读取或要求 OpenAI API Key；bridge 本身不能自行鉴权父对话模型，Host 无法提供当前值、只提供一项或上下文不完整时必须失败关闭。Topic manifest 的 `lastRun.model`/`lastRun.reasoningEffort`、旧的顶层同名字段和官方 Graft manifest 的 `model` 都只是历史证据，禁止当作当前调用配置，也禁止询问用户用历史值替代。
- Deep 默认以 `--concurrency 1` 运行，降低大文件、WASM/Provider 资源竞争造成的偶发 `Aborted()`；这不是对官方 Tree-sitter 解析失败的掩盖。只有官方 build 成功、专题 context 的 `manifest.json` 存在、`check --json` 的 context/graph 均为 fresh 且源文件 hash 未漂移，才能报告 `fresh`；否则保留旧状态并标记 `failed`/`unverified`，不得扩大范围重试。
- 每次专题 Graft 调用前后都必须明确回显：`conversationId=<当前对话 ID> → topicId=<绑定专题>`，并使用同一绑定的 context；缺少 Host 提供的稳定 conversation ID 时不得猜测或退回根图。
- 已有绑定且未提供 `scope-file` 时，自动复用该 Topic manifest 的 scope；用于修复 hash 漂移，不扩大文件范围。没有可复用 scope 时必须先提供明确文件清单。
- Wiki 只可把专题结果作为可选来源，不能触发、依赖或承载 Graft Deep。
