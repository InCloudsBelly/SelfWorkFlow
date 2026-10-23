# SelfWorkflow 维护

根 `SKILL.md` 是入口文字源；`skills/selfworkflow/` 是自包含生成副本。新维护任务读根 Skill，续接沿既有绑定。
规则、方法、来源锁或随包资源变更后，在仓库根同步并检查：

```powershell
.venv/Scripts/python.exe -m selfworkflow.cli skill sync --repository .
.venv/Scripts/python.exe -m selfworkflow.cli skill check --repository .
```

源码、根入口、生成副本与完整新 release 一起交付；检查失败不报更新。不手改生成文件，不改删旧 revision，供在途任务复用。
消费者 clone 后直接读 Skill，无需生成、venv 或 submodule；外部能力按需核验。维护不授权更新全局安装、远程发布或重启宿主；保护现有改动与编译缓存。

用户明确说“安装工作流”时，默认按 `workflow/onboarding.md` 将完整 `skills/selfworkflow/`
安装到当前用户 `.agents/skills/selfworkflow/`；该请求即授权本次文档安装，维护规则本身不触发安装。
已有 WheelMaker 等宿主来源联接时按接入规则更新来源并保留联接；Git push 复用或取得明确授权。
