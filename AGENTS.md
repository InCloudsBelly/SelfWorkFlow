# SelfWorkflow 仓库维护

本仓库本身是可直接使用的 Skill，根 `SKILL.md` 是规范入口；`skills/selfworkflow/` 是同一 Skill 的自包含安装副本。
维护本仓库的新顶层任务实际读取根 `SKILL.md`，优先于宿主默认的安装副本。已有任务继承本次已绑定的 SelfWorkflow revision/documentRoot，不因维护源码或阶段切换重新启动。

修改规则、方法、来源锁或随包资源后，在交付前同步最终 Skill 并校验：

```powershell
.venv/Scripts/python.exe -m selfworkflow.cli skill sync --repository .
.venv/Scripts/python.exe -m selfworkflow.cli skill check --repository .
```

上述命令只供维护者使用；消费者 clone 后直接读取根 `SKILL.md`，无需生成步骤、维护环境或初始化 submodule。
源码、根入口、生成的安装副本和完整新版本目录作为同一次修改交付；不能只改源码或只提交公共入口。检查失败不得宣称 Skill 已更新。
保留既有 `releases/<revision>/`，不原地修改或删除在途任务可能读取的版本。不手工编辑生成副本；入口文字改根 `SKILL.md`，规则改对应源文件，再同步。
随包脚本和机器数据保持可执行/可读取格式。MCP、Viewer 与严格 Host 属于独立部署能力，按当前任务实际需要验证。
保持专业方法按需加载；维护此仓库不授权更新用户全局安装、推送远程或重启共享宿主。保护已有用户修改和编译缓存。
