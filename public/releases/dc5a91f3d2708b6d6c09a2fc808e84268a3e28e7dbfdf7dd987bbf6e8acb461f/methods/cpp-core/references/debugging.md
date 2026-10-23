# Native Debugging

先固定 failure envelope、符号/二进制身份、线程和首个异常点；区分 crash site、detection point 与 root-cause owner。沿 last-good / first-bad 检查输入、持久状态、生命周期和并发，不用下游 null-check 掩盖上游破坏。

## 验证

Bug 修复必须证明原始症状修复前失败、修复后通过，并覆盖相邻失败路径和状态不变量。栈、dump、Sanitizer 报告要绑定精确二进制和源码 revision。

## 边界

attach、launch、continue、表达式求值和内存/寄存器修改都有副作用；没有独立授权只做静态推理。
