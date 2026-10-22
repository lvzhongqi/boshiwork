---
name: prompts-writing
description: 编写或修改 Orrery 流水线提示词，并同步维护对应的中文版本；适用于项目提示词的结构、约束、示例和输出要求设计。
---

# Writing pipeline prompts

尽量用简洁、直白、逻辑清晰的语句写提示词：不要反复论证，少用长难句，不加过多无用的修饰，不乱用专业词汇和行业黑话。

## 架构

提示词按以下顺序组织，标签有内容才出现，每条要求只写一次。

### 系统提示词

#### 前缀语料块（`{{ document }}` 等）

放最长、跨调用逐字不变的材料。它位于最前面，便于 prefix cache，也让模型先读材料、后读问题。

#### `<task>`

在这里介绍本提示词的背景以及具体的任务。

#### `<constraints>`

只写顺着 task 仍容易做错的地方，一些必须的约束。

#### `<success_criteria>`

写完成品成立时必然为真的陈述句，逐条可核对，不写执行顺序。

#### `<example>`

放 0–3 个例子，例子要给全，注释写清楚。

#### `<failure>`

只用于确实提供模型侧退出接口的节点，写明何时结束任务及如何报告。Apply 和 Inject
依靠提交、机械检查与修复轮闭环，不写这个区块。

#### `<output_format>`

由 runner 追加到最后一个 block，提示词 `.md` 文件中不写。字段形状与取值由 submit tool 的 schema 规定，字段含义写在各字段的 `description` 中。

### 用户提示词

#### `<context>`

放本次调用的背景材料。

#### `<input>`

放本次要处理的对象，不混入任务说明。

#### 无标签指令

最后用一句祈使句提出本次任务，放在最靠近生成点的位置。


### 专用规则

- 编写或修改 `orrery/nodes/apply/` 下的提示词时，先完整阅读 [APPLY.md](APPLY.md)。
- 编写或修改 `orrery/nodes/inject/` 下的提示词时，先完整阅读 [INJECT.md](INJECT.md)。
- 改动任何 realizer / injector 的语义（description 或 rules 里的世界定义）之前，先查该
  subtype 在 VerdictBench 的全部用法：assumptions 条目、以它为条件或耦合它的 claims、
  参考 formal 模型里的对应编码。语义裁决以母本为准，不以文献先验为准。

## 外部插入

每份提示词是 jinja2 严格模式渲染的模板。插入点写作 `{{ variable }}`，变量只携带本次调用的数据。


## 中英双语

每份提示词修改时，注意同时修改同目录同文件带`_zh`后缀的提示词为对应的中文版本。
