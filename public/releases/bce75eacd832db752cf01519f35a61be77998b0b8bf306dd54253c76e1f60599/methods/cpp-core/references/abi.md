# ABI 与兼容性

检查 ODR、可见性/导出、结构布局、alignment、packing、虚表、RTTI/异常模式、编译选项、标准库边界和 allocator ownership。序列化格式、插件接口和跨模块对象的兼容性单独建模。

## 验证

对受支持矩阵做 consumer/producer 双向构建，记录 `sizeof/alignof/offsetof` 或导出符号基线，并验证旧数据/旧二进制读取路径；不支持的组合明确 `unverified`。

## 边界

源码兼容不等于二进制兼容；同一编译器名称也不代表配置、CRT 和编译标志一致。
