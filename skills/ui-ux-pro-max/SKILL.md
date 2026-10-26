---
name: ui-ux-pro-max
description: "在创建、改造或审查真实用户界面且需要视觉、布局、交互或可访问性设计时使用。纯崩溃/线程/GPU诊断、静态科学绘图、文档排版和按既有规则的微小机械修改不触发。"
---

# UI/UX 设计

提供设计检索与判断，SelfWorkflow 和已有代码/产物 Skill 保持流程、实现及验证职责。先沿用项目技术栈、既有样式和用户约束；不默认迁移到 HTML/Tailwind，不把提及 UI 或 dashboard 当作改造界面的意图。

从本任务已绑定的引用根（文档模式 documentRoot；显式契约用已核验 runtime 根）读取 `references/community-skills/ui-ux-pro-max/`；复用当前版本与所需引用身份。脚本为该目录下的 `src/ui-ux-pro-max/scripts/search.py`，数据保持其同级 `../data`。路径/hash 不可验证时报告缺口。

执行时将本次命令的工作目录设为脚本所在的 `scripts` 目录，并使用 `search.py` 文件名，兼容 Windows 长路径下的同级模块导入。

- 新页面或整套视觉方向：使用 `python -B -X utf8 search.py "<产品与设计意图>" --design-system -f markdown`。
- 单个组件/体验问题：只做一个明确 `--domain ux|style|color|chart|typography` 的相关查询；已知框架细节用 `--stack`，不预加载所有 CSV 或启动全套设计系统。
- 校验结果是否适合产品、平台和当前问题；无匹配时只重写查询一次，再明确说明缺少数据匹配，使用一般原则。

上游 `src/ui-ux-pro-max/templates/base/skill-content.md` 是生成模板；需要时只读 Query Contract、Common Rules 或 Pre-Delivery Checklist 的相关部分。模板占位符与厂商路径不能直接执行，实际路径以上述绑定目录 解析为准。

默认只读检索，不执行 `--persist`/`--force`、安装软件或创建新项目。用户需要保存设计产物时，显式用 `--output-dir` 指定当前任务已授权的项目输出绝对路径。`-B` 防止写入不可变快照的 __pycache__。

交付当前需求所需的设计决定、实现建议与适用验证；接着由 sites/visualize 或实际项目代码 owner 承接实现。静态数据曲线继续使用科学绘图能力。
