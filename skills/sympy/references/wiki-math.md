# Wiki 数学公式与参数约定

仅在知识解释或 Wiki 成文包含数学机制时读取；沿知识模块的写入授权、来源与质量规则。

- 当计算关系、算法条件、几何变换、概率模型、累计/积分或误差关系用公式能帮助理解时，用 LaTeX 表达并配自然中文解释；说明它对应正文逻辑的哪一步、为何成立、何时适用。避免只有公式没有解释，也不把普通叙述强行符号化。
- 首次出现的符号要有参数说明：含义、输入/输出角色、必要的类型/矩阵形状、单位或无量纲属性、定义域和取值约束；求和/积分说明索引范围、积分域及测度。全文保持同一符号的含义一致，明确等式、近似与模型假设。
- 同一推导及相互引用的公式沿用一套记号。同一概念在公式、正文、图例和可复制的 LaTeX 中使用相同记号。不同概念用不同的基字母或可直接读出含义的名称，字号、粗细和大小写只辅助辨读。层号、坐标轴等索引用下标或上标。
- 公式与源码/来源相符；区分已有结论、等价改写与新增推导。保留边界、分支、分母非零和收敛等成立条件。不能从代码或资料确认的技术事实列为缺口，不为补公式编造模型。
- 按 Wiki 实际渲染器及版本选择定界符和命令；常见 Markdown 可用行内 `$...$` 与独立成段的 `$$...$$`，须先核验宿主配置。多行推导、矩阵和分段函数用实际支持的环境；不把完整 TeX 文档、宏包命令或代码块中的源码当作已渲染公式。
- 必要时用固定 SymPy 方法计算/复核并生成 LaTeX，保留假设、结果和执行证据。计算、语法和实际显示分别判断。按[质量标准](../../knowledge-backend/references/wiki-quality.md)检查受影响的公式显示，关注换行、溢出和符号，无法预览时记录未核实。

例如解释归一化加权值时，可写：

$$
\bar{x}=\frac{\sum_{i=1}^{n} w_i x_i}{\sum_{i=1}^{n} w_i}
$$

其中 $n$ 为样本数，$x_i$ 为第 $i$ 个样本值，$w_i$ 为无量纲非负权重，且 $\sum_i w_i>0$；结果与 $x_i$ 单位相同。再说明提高某个权重会增加该样本的影响；是否还需边界例由该页机制决定，不将此例套到不满足条件的实现。

## 图形学记号

- 按量的实际含义选用该专题的常见记号。几何中可用 $p$ 表示点、$\mathbf n$ 表示法线。光照推导常用 $L$ 表示辐亮度、$E$ 表示辐照度、$f_r$ 表示 BRDF，入射和出射方向用 $\omega_i$、$\omega_o$ 并说明朝向。工程量用能读出用途的记号，首次说明类型、单位或无量纲属性，以及对应的源码标识。 [PBRT 辐射度](https://pbr-book.org/4ed/Radiometry,_Spectra,_and_Color/Radiometry) · [PBRT 表面反射](https://pbr-book.org/4ed/Radiometry,_Spectra,_and_Color/Surface_Reflection)
- 跨空间、深度编码或帧使用描述性标记，例如 $p_{\mathrm{world}}$、$z_{\mathrm{device}}$、$L_{\mathrm{hist}}$。变换写明来源和目标，例如 $M_{\mathrm{world}\to\mathrm{clip}}$，并按实际实现说明行或列向量、乘法次序及相关透视除法。 [PBRT 变换](https://pbr-book.org/4ed/Geometry_and_Transformations/Transformations) · [DirectXMath 矩阵约定](https://learn.microsoft.com/en-us/windows/win32/api/directxmath/ns-directxmath-xmmatrix)
- 变量与运行索引用斜体，例如 $r$ 和 $i$。描述性下标、单位和命名运算用直立字形，例如 $d_{\mathrm{view}}$、$\mathrm{cm}$ 和 $\operatorname{floor}$。源码标识保留原拼写，公式和图例沿用同一套符号。 [NIST 量与下标排版](https://physics.nist.gov/cuu/Units/checklist.html)
- 复杂算式按含义拆分，给单位方向、分项权重和中间量取可读名称。条件赋值用分段式，数值算例用 LaTeX 的分数、根号和不等式，小数保留前导零。统一核对显示公式、相关正文、图例与可复制的 LaTeX。
