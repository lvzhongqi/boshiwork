# 提示词写作最佳实践调研报告

调研时间 2026-08-13。范围：Anthropic / OpenAI / Google 三家当代官方文档 + 公开实测论文。
本报告只讨论"提示词怎么写"这件事本身，不含任何本项目的内容，是最底下那层来源。
三层分工：规则看 `../SKILL.md`，规则为什么这么定看 `rationale.md`，某条结论出自
哪篇文档或论文看本文件。

**这是 2026-08-13 的快照。** 语义层的结论跨代稳定；涉及具体机型参数与默认值的部分
（尤其第 7 节）过期很快，引用前先核。

---

## 0. 三家当前旗舰与官方入口

- **Anthropic**：旗舰 Claude Fable 5 / Mythos 5（Opus 5、Sonnet 5 为主力档）。
  入口是 Prompting best practices，外加**每个模型一页分册**——通用技巧与模型差异
  分开写。
- **OpenAI**：旗舰 gpt-5.6-sol（`gpt-5.6` 别名）。入口是 Prompt guidance，已从
  cookbook 迁进 API docs，按 model 参数分页；给出模板骨架与内部实测数据。
- **Google**：旗舰 Gemini 3.7 Flash（3.5 系列在产）。入口是 Gemini 3 dev guide、
  Prompt design strategies 和白皮书；强调简洁，参数层变动最激进。

三家都已把"提示词指南"从单页拆成"通用原则 + 每代模型的行为差异"，这个拆法本身
就是对"提示词是否跨模型"这个问题的官方回答：**通用原则跨，行为差异不跨。**

---

## 1. 核心结论：提示词内容分三层，可移植性完全不同

- **语义层**——要它做什么、成功判据、给理由、示例、输出形状、消除自相矛盾、
  正向表述。**完全跨模型**：三家各自独立写下，措辞几乎相同。
- **结构层**——分块标签、章节顺序、长材料与指令的相对位置。**跨**，但标签语法
  各家偏好不同（见第 3 节）。
- **适配层**——effort / thinking / verbosity、温度能不能设、prefill、默认冗长度、
  字面执行强度、要不要写 CoT。**完全不跨**，每个小版本都变，且互相冲突。

推论：**不需要为每家写一套提示词，但必须为每家维护适配层 + 一条独立 baseline。**

反过来说，"为某个模型精调过的提示词"确实不通用——公开研究显示，即便以可迁移性为
显式优化目标，换模型后性能仍常掉 30% 以上，跨模型迁移多为中性或负面。但这与
"遵守共识规范的提示词具有高可移植性"并不矛盾：前者迁移的是过拟合，后者迁移的是原则。
这两件事必须分开谈。

---

## 2. 语义层：三家官方口径对照

**说清楚要什么，别指望推断。** Anthropic 写作 "Be clear and direct"，金规则是拿给
不懂上下文的同事读，他困惑模型也困惑；OpenAI 要求定义结果、成功判据、约束和可用
上下文；Google 写作 "clear and specific instructions"。

**给理由，模型从解释里泛化。** Anthropic 独立一节 "Add context to improve
performance"；OpenAI 用判据替代绝对规则；Google 白皮书同款。

**说做什么，不说不做什么。** Anthropic："Tell Claude what to do instead of what not
to do"；OpenAI 要求少用 ALWAYS / NEVER，只留真不变量；Google 有专节
"Instructions over Constraints"。

**少量高质量示例，覆盖不同分支。** Anthropic 建议 3–5 个、`<example>` 包裹，要
relevant / diverse / structured；OpenAI 要求 few-shot 与指令必须一致；Google 警告
示例过多会过拟合，强调示例间格式一致。

**消除自相矛盾。** Anthropic 指出新模型按字面执行，冲突时谁在下游谁赢，不可预测；
OpenAI 明确写模型会花额外 reasoning token 调和冲突。Google 未提。

**显式输出形状，缺失置 null 不猜。** Anthropic 用 Structured Outputs 取代 prefill；
OpenAI 要求抽取任务必给 schema，区分必填/选填，交卷前回扫遗漏；Google 是结构化
输出加客户端校验重试。

**显式放弃通道。** Anthropic 认为"给模型表达不确定的许可"可降低幻觉；OpenAI 在
模板里把 **Stop rules** 独立成段。Google 未提。

### 2.1 "outcome-first"：当代最重要的转向

三家在 2026 年同向转折：**给目标与判据，不给分解步骤。**

- OpenAI 给出内部实测数字：**更精简的系统提示词使评测分提升约 10–15%，总 token 降低 41–66%**；
  核心手法只有一条——**每条指令只说一次**。其推荐模板是
  `Role → Goal → Success criteria → Constraints → Output → Stop rules`。
- Anthropic 对最新一代明确写：为旧模型开发的指令集**往往过于规定性（too prescriptive），
  会降低输出质量**，建议在迁移时删除而不是重写。
- Google 写：为旧模型设计的冗长提示词工程会被新模型**过度分析（over-analyze）**。

同源的一条推论：**推理模型不需要你教它 think step by step。** OpenAI 的推理最佳实践
直接说这类措辞不必要、甚至有害；规定推理顺序的技巧（least-to-most 等）会约束一个
模型本可以做得更好的分解过程。

**但这不是无条件的。** 低资源 DSL、强格式产物、领域硬约束场景下，脚手架可能仍有正收益。
删过程脚本必须做 ablation，不能凭规范直接删。

> **2026-08-17 复核：本节"三家同向转折"说过头了。** 逐字查三家当前官方页，口径并不一致：
>
> - Anthropic [Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)：
>   "Provide instructions as sequential steps using numbered lists or bullet points
>   **when the order or completeness of steps matters**" —— 支持编号步骤，判据是顺序或
>   完整性。同页 Thinking 节才说 "Prefer general instructions over prescriptive steps"，
>   管的是推理过程，不是做事指令。同页另注：**Opus 5 要删掉自检指令**，否则
>   over-verification。
> - OpenAI [GPT-5 prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide)：
>   通篇给显式过程（"Batch search → minimal plan → complete task"）并要求
>   "Always verify your changes extremely thoroughly"。
> - Google [Gemini 3 Developer Guide](https://ai.google.dev/gemini-api/docs/gemini-3)：
>   以前用 CoT 硬逼推理的复杂提示词，改用 `thinking_level: high` 加**简化提示词**。
>
> 即：同一句"请彻底自检"在 GPT-5 上是推荐、在 Opus 5 上是官方叫你删的。分歧全部落在
> 适配层（表 1 第三行），语义层依旧完全跨。SKILL.md 的四步归位顺序就是据此定的。
>
> 标签同批复核：**三家都没有标签清单**，只要求一致 + 描述性。Anthropic 举
> `<instructions>` `<context>` `<input>`，Google 举 `<context>` `<task>` 并要求
> "Choose one format and use it consistently"，OpenAI 的 GPT-5 指南自造
> `<context_gathering>` `<persistence>` 等。唯一被点名的是示例：单个用 `<example>`，
> 多个再套一层 `<examples>`。

---

## 3. 结构层

### 3.1 分块标签：有效，但收益的来源要说对

收益不来自尖括号，来自**消歧义**——让模型无歧义地知道哪段是数据、哪段是指令、
哪段是示例、哪段是本次变量。

- **Anthropic**：XML 仍在通用原则里独立成节，适用条件写得最精确——
  「当 prompt 混合了指令、上下文、示例和变量输入时」。同时其博客补充：现代模型
  不靠 XML 也能读懂结构，简单 prompt 用清晰标题与空行即可，开销更小。两者不矛盾：
  **混合型 prompt 用，简单 prompt 不必**。
- **OpenAI**：官方指南写「使用 **Markdown 格式与 XML 标签的组合**」；GPT-5 系列
  指南通篇用 `<xxx_spec>` 分段，并引用 Cursor 的实践说结构化 XML spec 明显优于散文。
- **Google**：要求用一致的结构分隔符（XML **或** Markdown），并强调 **别混用，选一种**。

实操结论：**XML 定边界 + markdown 排正文**是三家都能接受的形态（属于分层使用，不算混用）。
tag 名要少而稳定，不要当排版用，不要四层嵌套。这些 tag **不需要是良构 XML**，
标签内出现 `<`、`&`、未闭合括号都无妨，不要为"合法 XML"去转义正文。

**标签名没有 canonical 集合**（2026-08 复核）。三家都没规定必须用哪些名字，只要求描述性
且前后一致（Anthropic 原话：use consistent, descriptive tag names across your prompts）。
官方文档里点过名的：Anthropic `<instructions>` `<context>` `<input>` `<example>` /
`<examples>` `<documents>` / `<document>` / `<document_content>` / `<source>` /
`<thinking>` / `<answer>`；Google `<context>` `<task>`，常见小节 Role / Constraints /
Context / Task / Instructions；OpenAI 不规定名字，通篇用 `<xxx_spec>`。

**三家都没有规定 user message 内部有哪些标签**，规定的是提示词整体的组件清单，组件落在
system 还是 user 是工程选择。Google 的清单最全：Objective / Instructions / Persona /
Constraints / Context / **Input data** / Examples / Output format——其中 Input data 与
Context 是两个组件，Anthropic 也单独点名 `<input>`。本项目据此把 user 侧拆成
`<context>`（背景）与 `<input>`（这次要处理的对象）。Examples 官方允许放 user 侧
（Anthropic：长材料置于 "your query, instructions, and examples" 之上），本项目放 system
侧，理由是例子跨调用不变、要吃 prefix cache——这是有意偏离，缓存不是质量。

**OpenAI 规定的是内容要素而非标记形式**，原话：「State the goal, relevant context,
constraints, required evidence, success criteria, and output format.」六件。
本项目的标签集取这六件与三家点过名的交集：`<task>`（goal，Google 点名）、
`<constraints>`（OpenAI 要素词 + Google 小节名）、`<success_criteria>`（OpenAI 要素词）、
`<output_format>`（OpenAI 要素词）、`<context>`（Anthropic 与 Google 都点名）、
`<example>`（Anthropic 点名）。required evidence 即 3.4 的引用块。`<failure>` 三家都无
对应词，是本项目自有的放弃通道。

### 3.2 顺序：一个表面分歧，以及它的收敛形式

- Anthropic：长材料（20k+ token）放**顶部**，问题放**结尾**；给出实测
  「结尾提问在复杂多文档场景可提升约 30%」。
- Google：同样，数据在前、问题在后，并建议用 "Based on the preceding information..."
  这类桥接句把模型的推理锚到给定材料上。
- OpenAI：developer message 内部建议 `Identity → Instructions → Examples → Context`，
  context 靠后。

看似矛盾，实为两件事：前两家说的是**跨消息的整体布局**（大语料 vs 指令），
OpenAI 说的是**单条 developer message 内部**的组织（context 指补充资料，不是大语料）。

**收敛出的唯一规则**：*大材料与本次指令分居两端，"本次要做什么 + 自检"永远最靠近生成点。*

### 3.3 长度：所有模型共同的物理约束

- *Lost in the Middle*（TACL 2024）：信息在上下文首尾比在中间更可靠地被使用。
- Chroma *Context Rot*（2025，18 个模型含 GPT-4.1 / Claude 4 / Gemini 2.5）：
  没有模型均匀使用上下文；输入越长越不可靠；1M 窗口不等于能在 1M 上可靠推理。

所以"提示词越短越好"不是审美，是有实测支撑的工程约束。

### 3.4 Ground-in-quotes

长文档 + 语义判断的场景，强制"先逐字引用（带出处）再判断"。三条收益：
模型必须挂在具体原文上；工程层可 parse 引用块做事后审计；文档自相矛盾时模型必须
表态引哪句，决策可追溯。

注意兼容性：**引用块与严格 JSON 模式不兼容**（JSON 模式会把它截掉）。要么走自由文本 +
本地解析，要么把引用做成 schema 的第一个属性（生成顺序随 schema 顺序）。

---

## 4. 写法层

### 4.1 正向优先：这确实是业界标准

三家白纸黑字：

- **Google 白皮书**有专节标题就叫 **"Instructions over Constraints"**：优先给指令，
  只在安全、明确性或特定要求时才用约束。
- **Anthropic**：不要写 "Do not use markdown"，要写
  "Your response should be composed of smoothly flowing prose paragraphs."
- **OpenAI**：少用 ALWAYS / NEVER，改用**判据**；只有真正的不变量
  （安全规则、必填字段、绝不能发生的动作）才用绝对措辞。

机制上的原因：否定本身对 LLM 更难——存在系统性的 **affirmation bias**（忽略 "not"
直接对物体作答），有专门的否定基准（*This is not a Dataset*）和视觉语言模型的否定研究
（MIT 2025）。更实际的原因是：**禁令只圈掉一块，剩下的空间仍未定义**；正向表述直接指定落点。

### 4.2 但禁令不是禁区——最优形态是三件套

官方从没说"不许写禁令"，只说"别只写禁令"。硬禁令的最优形态：

```
禁令  +  正向替代写法  +  一句为什么
```

三缺一都不合格。Anthropic 明确说模型能从解释里泛化，所以"为什么"不是修辞，是有效载荷。

有意思的反证：有实测报告称在代码审查这类需要对抗性推理的任务上，否定式提示
（"不要漏掉 X"）反而显著提升缺陷检出。这说明**禁令的价值场景是"抑制模型即将做的事"**，
而不是"定义要做的事"。两者不冲突。

### 4.3 有限穷举优先于开放描述

"提取一个合适的参与方，包含以下 N 类"优于"不要太多、不要太少、不要有 X"。
对应官方的"白名单 + 判据"模式。两条附加要求：

- **白名单只在唯一位置定义。** OpenAI 的 Prompt Optimizer 修复的三大失效模式就是：
  ① 指令自相矛盾 ② 输出格式规格缺失或含糊 ③ **few-shot 示例与指令不一致**。
  规则区写枚举、输出格式区又写一遍且不一致，正是第 ① 与第 ② 的合体。
- **判据给决策顺序**，而不是给一堆并列条件让模型自己权衡。

### 4.4 不堆 ALL-CAPS

Anthropic 明确：`CRITICAL: You MUST` 这类措辞在新模型上会造成**过触发**，
修法就是"把措辞降回正常"。OpenAI 同向。编号 + 一句后果说明即可。

### 4.5 当代最贵的新风险：限定语变成硬闸门

这是 2026 年最值得单列的一条，也是多数公开指南还没跟上的。

新一代模型（Claude Sonnet 5 / Opus 5 / Fable 5、GPT-5.x）**字面执行强度大幅提升**。
风险重心从"ALL-CAPS 过触发"转移到 **"温和的限定语被严格执行"**。

Anthropic 给出的官方案例极具代表性：code review 提示词里写"只报高危问题"/"保守一点"，
新模型会照办到底——**它仍然同样深入地调查，只是不再报告它判定低于你所设门槛的发现**。
表现为召回率下降，**但这不是能力退化**。官方给的修法是：把"发现"与"过滤"拆成两步，
在发现阶段明确告诉模型它的任务是覆盖率而非筛选。

推广出来的规则：**提示词里每一个限定语都要标注它属于哪一类**——
"想要的收窄"（保留），还是"意外的闸门"（必须配一条优先级更高的补全条款，
并显式写明例外关系）。每加一条限定语，grep 一遍同一份提示词里的补全条款。

---

## 5. 结构化输出：一个必须权衡的取舍

- *Let Me Speak Freely?*（EMNLP 2024 Industry）：**格式约束越严，推理任务掉得越多**；
  严格 JSON 模式会因输出次序被打乱而损害推理。分类任务则相反，结构化能提升准确率。
- Google 官方补充：schema 过于复杂（长属性名、大枚举、多可选属性、数值上下界约束）
  会直接触发 InvalidArgument；建议缩短名称、拍平嵌套、减少带约束的属性。
- 三家都提供了 structured outputs / JSON schema，且都建议**缺失字段显式置 null，不要猜**。

实操取舍：

- **纯抽取、字段确定、无需推理**——上严格 schema。
- **需要语义判断的抽取**（要先引用、先推理再填字段）——走自由文本加本地校验，
  或两段式：先自由文本判断，再单独一次调用做序列化。
- **任何情况下**——下游 parser 绝不依赖模型输出的自然语言格式（"Holder: …;
  What: …" 这种四段式），改成独立字段。

最后一条是通用工程原则：能让错误在结构上不可能发生，就不要做事后解析。

---

## 6. 示例数量

- 官方口径：Anthropic 建议 3–5 个；Google 强调实验，并警告过多会过拟合。
- 公开实测：代码翻译任务在 **5–25 例**区间功能正确性达峰，超过反而下降
  （*When Many-Shot Prompting Fails*）；神经架构生成任务 **n=3** 是甜点，n=6 时失败率飙到 99.8%。
- 结论：**3 个左右是通用起点，超过 25 基本一定在倒退**；且最优值任务相关，必须实测。
- 硬要求：示例之间要覆盖不同判别分支；**示例必须与规则一致**。

---

## 7. 适配层：三家的硬事实（截至 2026-08）

这些是"必须为每家单独处理"的部分：

- 传非默认 `temperature` / `top_p` / `top_k` 直接 400——Anthropic Sonnet 5。
- 官方要求从生成配置里**删掉** temperature / top_p / top_k——Google Gemini 3.x。
- prefill（预填 assistant 消息）不再支持——Anthropic 4.6+、Google Gemini 3.7。
- `budget_tokens` 报 400，改用 `effort`——Anthropic 4.7+。
- `thinking_budget` 改名 `thinking_level`，默认从 high 降到 medium
  ——Google Gemini 3.5+。
- 模型**自带自检**，官方要求删掉提示词里的"最后验证一步"类指令
  ——Anthropic Opus 5。
- 关闭 thinking 时可能把内部 XML 标签漏进可见输出，"不要推理"类指令会加剧
  ——Anthropic Opus 5。
- 有 `reasoning_extraction` 拒答类别，**不要要求模型复述内部推理**
  ——Anthropic Fable 5。
- 默认更简洁，要 chatty 必须显式要——Google Gemini 3.x、OpenAI 5.6。
- 默认响应比上一代更长，effort 不控制可见长度，要显式提示——Anthropic Opus 5。
- reasoning effort 六档含 `none`——OpenAI 5.6。

---

## 8. 迁移纪律（三家一致）

1. **先定 baseline**：换模型时先不动提示词跑一遍，拿到基线再改，否则分不清是模型差异
   还是提示词差异。OpenAI 把这条列为迁移第一步。
2. **不要整包重写**：先只换 model id 与参数，跑现有 eval 找行为变化，再做外科式修改。
3. **从最小提示词起步**：OpenAI 对最新一代的建议是"从能保住产品契约的最小提示词开始，
   再按需加回"，而不是把旧 stack 整个搬过来。
4. **一轮改动要可归因**：一次改太多无法定位是哪条变更起的作用。
5. **每家一条独立 baseline**：这是"一套提示词通吃"能否成立的唯一证据来源。

---

## 9. 二轮补充调研（2026-08-13）：一轮未覆盖的四个领域

一轮调研覆盖的是"单次调用的提示词怎么写"。本项目的实际形态是**带工具的多轮 agent 循环
生成低资源 DSL**，这带出四个一轮完全没碰的领域。

### 9.1 工具描述也是提示词

Anthropic《Writing effective tools for agents》（其官方工程博客，内容由 agent 实测迭代得出）：

- **tool description 会整体进入模型上下文并引导调用行为**，是提示词的正式组成部分，
  优化 description 是改进工具最有效的手段之一；
- 参数名自带语义：`user_id` 而非 `user`；不让模型面对裸 UUID / 内部编号；
- description 的写法标准是"讲给一个不懂内部背景的新同事"：把领域黑话、输入输出格式、
  资源之间的关系显式写出来；
- **工具报错文案要给出具体、可执行的下一步**，不要裸错误码或 traceback；带一个正确用法示例；
- 返回内容只给高信号信息，截断时附"接下来怎么搜得更准"的指引。

Anthropic《Define tools》官方文档（2026-08 补入，措辞比博客更硬）：

> Provide extremely detailed descriptions. This is by far the most important factor in
> tool performance. …… What each parameter means and how it affects the tool's behavior
> …… Aim for at least 3–4 sentences for each tool description.

推论：**"每个字段填什么"的官方归属是 tool description 与每个参数自己的 `description`，
不是提示词正文**。复杂或格式敏感的输入另有 `input_examples` 字段（会被 schema 校验，
简单例约 20–50 token，嵌套例 100–200）。有限取值用 `enum`，让错值在 API 层就失败。
OpenAI 口径更短（1–2 句讲清做什么、何时用），归属一致：写在工具定义里。

### 9.2 修复回路：反馈质量决定修复率

*How Many Tries Does It Take? Iterative Self-Repair in LLM Code Generation*
（arXiv 2604.10508，7 个模型实测）：

- **两轮修复拿到全部可得收益的 76–95%**，第一轮增益最大，3–4 轮边际趋零；
- **8B 级小模型同样能有效自修**（Llama 3.1 8B 靠错误反馈 +9.8pp），推翻"弱模型不会自修"的旧结论；
- **反馈的具体程度直接决定修复率**：名字类错误（undefined variable，诊断信息最具体）修复率约 77%，
  语法错误约 66%，assertion 类错误（只知道结果不对、不知道哪里不对）仅约 45%；
- self-repair 比独立重采样省一半以上 token 且效果更好（112K token 达 93.3% vs 231K token 达 90.9%）。

推论：**回炉上限 2–3 次是实证甜点；诊断文案必须带"哪里、期望什么、实际什么"三件套**，
只说"检查未过"的诊断把修复率从 ~77% 拉到 ~45% 一档。

### 9.3 低资源 DSL：语法脚手架有实证正收益

- *Enhancing Code Generation for Low-Resource Languages: No Silver Bullet*（arXiv 2501.19085，
  6 个模型 × R/Racket）：**小模型 fine-tune 最优；中大模型 in-context learning "永远有正收益，
  幅度不一"；超大模型 fine-tune 反而可能掉**。
- Survey（arXiv 2410.03981）：few-shot、grammar prompting（把语法规则/骨架放进提示词）等
  prompt 侧技术能在不重训模型的情况下显著缩小低资源语言的差距。

推论：ProVerif 正是典型低资源 DSL。**提示词里的语法脚手架（模板骨架、成对 fun/reduc 形状、
禁用模式、接收状态节奏）是有实证支持的正收益项**——这是 §2.1 "outcome-first、删过程脚本"
的真例外，删除仍需逐项 ablation，但方向上不应删。

### 9.4 弱模型适配：改结构显式度，不改语义层

公开工程实测的共识（Palantir prompt 工程指南、多篇小模型对比）：

- 小模型需要**更显式、更分步、更结构化**的指令与更紧的输出 schema；frontier prompt 里的
  指令常隐含小模型不具备的能力假设；
- few-shot 示例要**针对实际观察到的失败模式**挑选，而不是泛泛覆盖；
- 任务适配性：分类 / 路由 / 结构化抽取 / 短上下文 QA 小模型普遍可胜任；
  多步推理、长上下文综合、开放生成需要大模型。

推论：**适配弱模型的路径不是为它重写一套提示词**（那是过拟合，见 §1），而是
(a) 保留语法脚手架不删；(b) 结构显式度拉满（tag 骨架、编号规则、白名单）；
(c) 观察到具体失败模式后加 1–2 个针对性示例。这三条对强模型都无害或有益，
所以仍是一份提示词三家（乃至弱模型）共用。

---

## 参考文献

**官方文档**

- Anthropic · [Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
- Anthropic · [Prompting Claude Opus 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5)
- Anthropic · [Prompting Claude Sonnet 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5)
- Anthropic · [Prompting Claude Fable 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5)
- Anthropic 博客 · [Prompt engineering best practices for 2026](https://claude.com/blog/best-practices-for-prompt-engineering)
- OpenAI · [Prompt guidance (gpt-5.6)](https://developers.openai.com/api/docs/guides/prompt-guidance?model=gpt-5.6)
- OpenAI · [Prompt guidance (gpt-5.5)](https://developers.openai.com/api/docs/guides/prompt-guidance?model=gpt-5.5)
- OpenAI · [Model guidance / latest model](https://developers.openai.com/api/docs/guides/latest-model)
- OpenAI · [Prompt engineering guide](https://developers.openai.com/api/docs/guides/prompt-engineering)
- OpenAI Cookbook · [GPT-5 Prompting Guide](https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide)
- OpenAI Cookbook · [GPT-5.1 Prompting Guide](https://developers.openai.com/cookbook/examples/gpt-5/gpt-5-1_prompting_guide)
- OpenAI Cookbook · [GPT-5.2 Prompting Guide](https://developers.openai.com/cookbook/examples/gpt-5/gpt-5-2_prompting_guide)
- OpenAI Cookbook · [Prompt Optimizer](https://developers.openai.com/cookbook/examples/gpt-5/prompt-optimization-cookbook)
- Google · [Gemini 3 Developer Guide](https://ai.google.dev/gemini-api/docs/gemini-3)
- Google · [What's new in Gemini 3.5](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5)
- Google · [Latest model (Gemini 3.7 Flash)](https://ai.google.dev/gemini-api/docs/latest-model)
- Anthropic · [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- Google · [Prompt design strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies)
- Google Cloud · [Structure prompts](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/prompts/structure-prompts)
- Google Cloud · [Prompt design best practices](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/prompt-best-practices)
- Google · [Prompt Engineering 白皮书（Lee Boonstra）· Instructions over Constraints](https://www.leeboonstra.dev/prompt-engineering/prompt_engineering_guide6/)

**公开实测与论文**

- [Does Prompt Formatting Have Any Impact on LLM Performance? (arXiv 2411.10541)](https://arxiv.org/abs/2411.10541)
  ——同内容换 plain / Markdown / JSON / YAML，GPT-3.5-turbo 波动最高 40%，GPT-4 明显更稳健。
- [Let Me Speak Freely? (EMNLP 2024 Industry, arXiv 2408.02442)](https://arxiv.org/abs/2408.02442)
  ——格式约束越严，推理任务掉得越多。
- [Lost in the Middle (TACL 2024)](https://aclanthology.org/2024.tacl-1.9/)
- [Chroma · Context Rot (2025)](https://www.trychroma.com/research/context-rot)
- [When Many-Shot Prompting Fails: LLM Code Translation (arXiv 2510.16809)](https://arxiv.org/html/2510.16809)
- [Does Few-Shot Learning Help LLM Performance in Code Synthesis? (arXiv 2412.02906)](https://arxiv.org/abs/2412.02906)
- [This is not a Dataset: A Large Negation Benchmark (arXiv 2310.15941)](https://arxiv.org/pdf/2310.15941)
- [MIT News · 视觉语言模型无法处理否定词 (2025)](https://news.mit.edu/2025/study-shows-vision-language-models-cant-handle-negation-words-queries-0514)
- [Prompting Science Report 2: The Decreasing Value of Chain of Thought (arXiv 2506.07142)](https://arxiv.org/pdf/2506.07142)
- [The Pink Elephant Problem: Why "Don't Do That" Fails with LLMs](https://eval.16x.engineer/blog/the-pink-elephant-negative-instructions-llms-effectiveness-analysis)
- [Simon Willison · GPT-5.5 prompting guide](https://simonwillison.net/2026/apr/25/gpt-5-5-prompting-guide/)
- [philschmid · Gemini 3 Prompting Best Practices](https://www.philschmid.de/gemini-3-prompt-practices)

**二轮补充（第 9 节的依据）**

- [Anthropic · Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [How Many Tries Does It Take? Iterative Self-Repair in LLM Code Generation (arXiv 2604.10508)](https://arxiv.org/html/2604.10508v1)
- [Enhancing Code Generation for Low-Resource Languages: No Silver Bullet (arXiv 2501.19085)](https://arxiv.org/abs/2501.19085)
- [A Survey on LLM-based Code Generation for Low-Resource and Domain-Specific PLs (arXiv 2410.03981)](https://arxiv.org/abs/2410.03981)
- [Palantir · Best practices for LLM prompt engineering](https://www.palantir.com/docs/foundry/aip/best-practices-prompt-engineering)
- [Prompt Engineering Guide · Function Calling in AI Agents](https://www.promptingguide.ai/agents/function-calling)
