# SelfWorkflow 维护

根 `SKILL.md` 是入口文字源；`skills/selfworkflow/` 是自包含生成副本。新维护任务读根 Skill，续接沿既有绑定。
规则、方法、来源锁或随包资源变更后，在仓库根同步并检查：

```powershell
.venv/Scripts/python.exe -m selfworkflow.cli skill sync --repository .
.venv/Scripts/python.exe -m selfworkflow.cli skill check --repository .
```

源码、根入口、生成副本与完整新 release 一起交付；检查失败不报更新。不手改生成文件，不改删旧 revision，供在途任务复用。
消费者 clone 后直接读 Skill，无需生成、venv 或 submodule；外部能力按需核验。维护不授权更新全局安装、远程发布或重启宿主；保护现有改动与编译缓存。
