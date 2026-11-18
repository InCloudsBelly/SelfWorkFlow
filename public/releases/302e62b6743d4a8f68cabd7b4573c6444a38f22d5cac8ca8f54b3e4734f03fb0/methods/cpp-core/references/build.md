# 构建与工具链

固定编译器、标准、Target、Platform、Configuration、宏和生成步骤。检查声明/定义、链接顺序、条件编译、PCH/unity 偶然依赖、生成头、模块边界和增量构建缓存。

## 验证

至少执行受影响 Target 的非 unity 或等价边界检查、干净/增量路径与关键宏组合；不能执行时给出准确命令和 `unverified` 风险。

## 边界

单个 TU 编译不证明链接、生成代码或其他 Target；IDE 索引成功不证明构建成功。
