# UE 构建缓存

沿通用编译保护，核对最近正常构建的 Target、Platform/架构、Configuration、工具链/SDK、全局宏、PCH、Unity 和 Live Coding 编译支持。

- `-Module` 只限制本次动作范围，仍使用共享 Intermediate/PCH。不得擅加 `-NoLiveCoding`，该参数会改变 `WITH_LIVE_CODING`，来回切换可使共享头和 PCH 失效。保持 Live Coding 编译支持。实际执行 Live Coding 或 Hot Reload 需要相应授权。
- 缓存保护包括 Intermediate、Binaries、PCH、DDC。编译动作异常扩大时，核对 UBT makefile 失效原因、全局定义和 PCH 变化。
