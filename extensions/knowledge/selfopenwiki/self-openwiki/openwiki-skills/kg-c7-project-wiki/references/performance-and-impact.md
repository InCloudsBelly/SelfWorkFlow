# 性能、资源与跨阶段影响

## 性能与内存

- `.utrace` 必须绑定唯一文件；区分 GameThread、RenderThread、RHI、GPU、worker、Slate、IO。`WaitForTasks` 先视为等待症状，沿上游找 owner。
- dump 先读 `.memreport`/Summary，再按热点钻取；独占口径、估算口径、UObject serialization 与 RHI 常驻不可混算。
- 多份数据同时列增长、下降、基线、热点、版本/时间、置信度和未验证项；不把不同 CSV 同名字段直接相加。

## Shader / PSO / 资源

```text
material or shader include
  -> material instance / include dependency
  -> permutation / shader type / vertex factory
  -> Shader Library / SHK / DDC / PSO artifact
  -> runtime material, render pass or platform
```

分别记录 artifact validity 与 combination coverage；“新 C++ + 新 Shader 工作”不能证明旧 C++/新 Shader 兼容。缺少 unresolved/dropped/new PSO 证据时写 `Unknown`。

## SceneExport / WorldPartition

按 `producer -> persisted artifact -> transform -> consumer/detection point` 建最小链，比较 `last-good / first-bad`。退出码、dirty flag、checkpoint READY 不单独证明产物有效。修复归最早拥有数据与不变量的 stage，下游只拒绝非法输入并改善诊断。

关注 Actor/component/instance identity、mapping/proxy 完整性、HLOD/PVS partial output、保存点，以及 Desktop/Mobile、WP/non-WP、LightMap/HLOD/TOD 等模式矩阵；不同模式不能互相推断。

## 旧 Binary 兼容

记录 `develop writer -> artifact/protocol -> preonline old reader`。按需检查 Package/Custom Version、属性 schema、Blueprint bytecode、PostLoad、Shader/RHI ABI、Cook/DDC、Asset Registry、Pak/IoStore、网络/回放/配置/Native ABI。旧 reader 或结构化证据缺失时写 `Unknown`。
