# Graft 专题 Deep 模块

- 一个对话只绑定一个 `topic-id`。专题 Deep 持续维护同一项目内上下文，不按 Git hash 建目录；以源文件 hash 增量重算变更/新增文件，删除已移除文件。
- 全局 `graft/` 保留非 Deep structural Map；专题 Deep 使用项目内 `./selfworkflow/graft-deep/<topic-id>/graft`，不创建临时 Git 仓库，不扫描全仓库。
- Deep 必须接收非空、项目内、无 Reparse Point 的相对文件清单，并将每个文件作为官方 Graft 的重复 `--only-dir`；当前项目全局 Map 与专题上下文分开。
- 仅主 Agent 可调用官方 `provider graft-deep` bridge；这是 Graft Deep 专用入口。Reviewer 不得调用 Graft/provider。桥接使用本次主对话显式提供的 model/reasoning-effort，不读取或要求 OpenAI API Key。
- 只有官方 build 成功、专题 context 的 `manifest.json` 存在、`check --json` 的 context/graph 均为 fresh 且源文件 hash 未漂移，才能报告 `fresh`；否则保留旧状态并标记 `failed`/`unverified`，不得扩大范围重试。
- Wiki 只可把专题结果作为可选来源，不能触发、依赖或承载 Graft Deep。
