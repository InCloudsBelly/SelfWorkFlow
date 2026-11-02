# 类型系统

先确定公开契约和期望诊断，再检查重载集合、隐式转换、模板推导、Concept/约束、ADL、特化、`constexpr` 与编译期成本。保持约束最接近接口，避免用复杂元编程隐藏运行期不变量。

## 验证

至少包含应编译与应拒绝的类型组合、cv/ref/value-category 边界、歧义重载和跨编译器差异；必要时用最小 compile-only fixture。

## 边界

clangd/IDE 可解析不等于目标编译器、宏组合和真实 Target 可构建。
