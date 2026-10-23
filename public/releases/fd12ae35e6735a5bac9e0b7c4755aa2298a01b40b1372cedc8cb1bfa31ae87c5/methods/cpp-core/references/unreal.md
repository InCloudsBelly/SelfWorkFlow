# Unreal Engine C++

区分 UBT/UHT 与普通 C++：检查 Target、Platform、Configuration、module dependency、API 导出、generated header、unity/PCH 和 MSVC 扩展。UObject 生命周期检查反射可见引用、GC、弱引用、CDO/静态初始化和 GameThread 归属；渲染路径区分 Game/Render/RHI 线程与资源释放栅栏。序列化和引擎 fork 修改要评估旧数据、旧二进制、Shader/PSO 与模块 ABI。

## 验证

使用项目允许的真实 Target/Platform 构建和 UE Automation seam；覆盖 unity/non-unity、UHT、关键线程切换、GC/销毁和 producer 到 Runtime consumer。项目禁止本地构建时保持 `unverified`，不要自行运行。

## 边界

普通 AST/clangd 结果不代表 UHT、UBT、宏展开、目标平台或 Runtime 行为；项目专属 code tag 和发布兼容规则由项目适配器按需加载，不能固化进通用核心。
