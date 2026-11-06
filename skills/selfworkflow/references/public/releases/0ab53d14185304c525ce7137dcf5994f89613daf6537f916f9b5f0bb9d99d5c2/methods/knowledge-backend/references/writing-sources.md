# Wiki 写作规则固定来源

以下是正文契约中人工提炼的固定来源，不是运行依赖；消费者离线直接用随包规则，不访问GitHub、安装独立Skill或跟随main。保留源文件与许可证的SHA256供维护核验。

## humanizer-zh
- 仓库：https://github.com/ai-zixun/humanizer-zh
- commit：`f75f1ac9735c4f10da1bba0148e0ea7228c5c3b3`
- skill：[固定文件](https://raw.githubusercontent.com/ai-zixun/humanizer-zh/f75f1ac9735c4f10da1bba0148e0ea7228c5c3b3/SKILL.md)；SHA256：`d7ef1115ef9f05697bf08dc0218983e0c8fcb472e5c33eb4bb1d6faa200c0a32`。
- license：[固定文件](https://raw.githubusercontent.com/ai-zixun/humanizer-zh/f75f1ac9735c4f10da1bba0148e0ea7228c5c3b3/LICENSE)；SHA256：`609132fb364baa7688c086c5baa267ebb88edf32ea431d2dbf3e745d39576d3f`。

## technical-writing
- 仓库：https://github.com/cursor/plugins
- commit：`4dd1d05818d19792e7cd6e818f1667f95f7e1dbe`
- skill：[固定文件](https://raw.githubusercontent.com/cursor/plugins/4dd1d05818d19792e7cd6e818f1667f95f7e1dbe/pstack/skills/technical-writing/SKILL.md)；SHA256：`61fe9c424a798ebf36ad94941f87be049cb8827bdf86d21474a0dde37b513c43`。
- license：[固定文件](https://raw.githubusercontent.com/cursor/plugins/4dd1d05818d19792e7cd6e818f1667f95f7e1dbe/pstack/LICENSE)；SHA256：`bc957ca6bee02792566a1a028d105e02e247c6e77cf057061674273da77b200e`。

## 融入边界

humanizer-zh用于中文主线、节奏、去翻译腔和控制判断强度；不引入作者声音、语料选择、风格询问或全局标点禁令。technical-writing用于读者用途、条件/动作、精确术语和消歧；不照搬英文词数、固定缩进、强制拆页或unslop依赖。项目约定和技术完整性优先，风格修订纳入H3/E1及既有Review，无新增评分维度或外部调用。

## 许可证（原文保留）

### humanizer-zh — MIT

```text
MIT License

Copyright (c) 2026 aizixun

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### technical-writing — MIT

```text
MIT License

Copyright (c) 2026 Lauren Tan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
