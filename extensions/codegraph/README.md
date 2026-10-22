# 个人维护的 CodeGraph UE 后端

`codegraph_ue` 是个人维护的 Unreal 增强分支，来源为
<https://github.com/InCloudsBelly/codegraph_ue>。它不是官方发布包。
官方包仍由 `dependencies/locks/codegraph.lock.yaml` 固定；此分支由
`dependencies/locks/codegraph-ue.lock.yaml` 和 Git submodule gitlink 共同固定。

## 安装选择

Windows 安装器默认选择 `ue`。安装前验证来源 URL、gitlink、源码 commit/tree、
干净的子模块工作树及 package/lock 哈希，然后执行 `npm ci` 和 `npm run build`。
创建构建回执或调用 npm 前，实际 Node 必须通过内建 SQLite 内存数据库探针；
Node 25 及不提供可用 `node:sqlite` 的运行时会以 `codegraph-ue-node-runtime-unsupported` 停止。
只有构建完成且实际 Node、dist、node_modules 内容通过指纹核对后，才能注册后端。
UI workspace 也纳入指纹，允许 npm 在 node_modules 中指向该固定 workspace 的链接。
失败会终止本次安装，不自动切换到官方包或其他本地源码。

```powershell
Install_SelfWorkFlow.bat -CodeGraphBackend ue -ConfirmApply
Install_SelfWorkFlow.bat -CodeGraphBackend official -ConfirmApply
```

已经配置的个人 `-CodeGraphPath` 会继续保留。需要切换它时，显式使用
`-ReplaceCodeGraphOverride`；`-CodeGraphMcpLauncherOnly` 继续只修复当前来源的启动器。
显式 `-CodeGraphPath` 优先于 `-CodeGraphBackend`。以上命令会修改安装配置，
本次源码集成不会自动执行安装或切换当前后端。

## 构建来源与索引保护

构建回执保存在本目录的 `.build/codegraph-ue.json`，绑定固定源码、锁文件与完整运行内容。
后续 provider inspection 和 dispatch 会重新核对这些内容；改变源码、Node 或构建内容后需重新构建并注册。
回执不把保持原值的 package version 当作官方发布版本凭证。

固定源码、Node 和全部运行内容与成功回执相符时，安装器直接复用已有构建。
已有回执但内容漂移或上次构建未成功时，会报告 `codegraph-ue-build-identity-drift` 并停止，
保留原回执与产物。更新来源或恢复失败构建时，维护者须先受控停止使用该目录的旧后端，
归档 `.build/codegraph-ue.json`，再显式运行下面的源码构建命令，成功后重新注册。
本集成不自动停后端、归档回执或覆盖有漂移的活跃产物。

```powershell
.venv/Scripts/python.exe -m selfworkflow.cli source codegraph-ue-prepare --repository D:/SelfWorkFlow
```

SelfWorkflow 自动维护在 `reindexRecommended` 时停止，保留已有数据库，不通过
`index --force` 自动重建。此保护不改变 CodeGraph 显式 CLI 重建命令的语义；
升级已有大型索引仍需在独立候选中验证后安全切换。

更新增强分支后，应先提交该分支的改动，再同时更新父仓库 gitlink 与
`codegraph-ue.lock.yaml` 中真实的 commit/tree 和 package 文件哈希。
不要使用 `submodule update --remote` 将未固定的远端变化直接部署到个人工作流。
