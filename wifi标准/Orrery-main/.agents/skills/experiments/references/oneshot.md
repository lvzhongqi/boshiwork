# experiments/oneshot/ —— one-shot baseline 实验

**这个目录是 one-shot baseline 实验。** 它比较单次端到端生成与节点流水线，
两边使用同一个模型。模型敏感性实验应固定流程并用 `--model` 跑同一批协议，
那套 sweep 还不存在。

## 这个目录是干什么的

主线把一份协议文档变成 ProVerif 模型，走的是十个节点（principals → flow →
assumptions → properties → claims → world → root → apply → inject → solve），
每个节点有自己的工具、检查和修复轮。

这个目录把框架的建模阶段换成**一次 `system + user` 请求**，回复之后的求解、聚合和
对标保持一致，用来回答一个问题：完整 Orrery 框架相对 monolithic one-shot baseline
带来了多少收益。

用法和参数看同目录的 `README.md`，这里只写代码问不出来的东西。

## 为什么不在 `orrery/` 包里

分层架构有两条规则（见根 `AGENTS.md`），这个实验两条都占：

- `evaluation/` 虽然是旁路包，但那里明确写了"逐 run 对标不在这，那是节点表末端的
  `cross_check` 节点"；
- "除 cross_check 节点外任何代码不得触碰 ground_truth 路径"。

它既要绕开节点分解，又要自己读 ground truth。放在包外就不受
`tests/contracts/test_layering.py` 约束，可以自由 import `orrery.infra` /
`orrery.modules` / `orrery.nodes` 的现成能力。
`pyproject.toml` 的 `packages.find` 只收 `orrery*`，所以这个目录不会被打包。

**别把它挪进 `orrery/`**，也别为它在 `orrery/` 里加节点。它不是流水线的一步。

## 唯一的变量是"这份 .pv 是怎么写出来的"

这是整个实验的立身之本。回复之后的每一步都**故意**和主线共用实现，改动时不要让任何
一条漂掉：

| 环节 | 共用的东西 |
| --- | --- |
| 文档 | `inline_corpus(doc_set, cfg.document.inline_max_chars)`，与主线各 document reader 的 system block 0 逐字节相同 |
| 三份 json | 只用于确定本次 world、完整 scenario 和 goals，不让模型重新抽取，也不把其余候选场景塞进提示词 |
| 场景展开 | `expand_assignments(claims, assumptions, subtype_is_noop)`，产出的赋值和 `cases_results.json` 的格键完全对齐 |
| verdict 归属 | 主线同一个 `query_owners`，含 `auth_b_to_a` vs `auth_b_to_a_noninj` 的子串消歧 |
| 三值合取 | 抄 `nodes/aggregate` 的规则（全 true 才 true，其次有 false 则 false，否则 unknown） |
| 对标 | 直接调 `nodes/cross_check` 里的 `compare()` |
| 探针 | `pvtext/probe` 的事件名、放置规则、`remove_probe`、"可达 = false 或 cannot_be_proved" |

主线两个形状在这里是**复现**而不是照抄，`reference.py` 顶部有完整论述：

- **一份规则文本，多个目标。**主线一个点一次会话，同 subtype 同写法的 fixed data 点合成
  一次 batch（`nodes/apply/node.py` 的 `<batch_contract>`）。monolithic 请求整体只有一次
  会话，所以五个目标选中同一条规则时，规则渲染一次、五个目标列在它的 `<applies_to>` 里。
  按目标各渲染一遍曾经是 450 行重复段落，没给模型任何新信息。
- **写法是声明数据，不是判断。**多写法 subtype 按目标值的寿命选形态
  （`writings_by_lifetime`，由 `pvtext/lifetime` 从模型投影）。baseline 建提示词时还没有
  模型可投影，所以两种写法都发下去、各自标注选中自己的寿命，寿命判据由提示词按主线那条
  规则原样陈述（角色定义内的 `new` 是 per_session，其余是 long_lived）。

## 三个刻意的取舍

**提示词默认英文。** 主线跑的就是英文：节点的 `build_prompt` 取 `lang="en"`，
没有任何地方覆盖它，各节点旁边的 `_zh` 文件是给人读的、被 `.gitignore` 挡住、
不发出去。中文 baseline 比英文主线等于凭空多一个变量。这里沿用同一套 `localized`
约定，语言由配置的 `prompt_lang` 决定——和主线每个节点读的是同一个键，这里没有第二个开关。
**改提示词时两份都要改**，否则语言消融就不成立了。

**一场景一次调用，不是一协议一次调用。** 主线也是一场景一份 `.pv`，拿"一次回复产
K 份文件"去比会把"没有分解"和"一次要得太多"混在一起。每次调用仍然是 one-shot：
无工具、无上游产物、场景之间零状态。

**没有修复轮。** 每个场景只有一次模型调用。回复缺少完整模型或模型不能通过
ProVerif 语法检查时，场景直接记为失败，对应目标记为 `unknown`；不得把任何错误反馈给
模型。这样 baseline 始终是论文定义的 direct one-shot，而不是带求解器反馈的 agent loop。
这不删除主线的纯求解策略：探针提交态机械加 `set reconstructTrace = false.`，剥掉探针后
若某个目标第一次返回 `cannot_be_proved`，同一模型只保留该目标的 query，再用
`set preciseActions = true.` 限时求解一次。这里没有第二次 LLM 调用，也没有改模型。

## 什么在提示词里、什么不在

这条线是消融的边界，`reference.py` 顶部有完整论述，摘要：

- **在里面**：本次 run 的 world、本次调用唯一的完整 scenario、对应 goals，以及它们
  实际命中的主线规则。其他 variable 取值和其他场景不进入提示词，避免模型再次选择场景。
- **在里面**：标准原语声明清单。哪一对 `fun`/`reduc` 拼出 `sdec` 是转写惯例；不给
  就变成在测 ProVerif 语法记忆，不是在测协议理解。
- **在里面**：当前 world、scenario 和 goals 实际命中的 builder / realizer / injector
  规则，以及主线 flow 使用的身份、时变参数和角色体结构三个方法库。内容直接从主线注册表与
  规则文件按需渲染，不在 baseline 里抄第二份。比较的是“同一套建模规范由节点流水线执行”与
  “一个 monolithic prompt 一次执行”，不是“有规则”与“没规则”。
- **在里面**：`<honest_run_probe>` 探针契约。它和 `w_<gid>` / `begin_<gid>` 命名契约同一性质，
  都是"让结果可归属"的仪表，不是"教它怎么建模"——主线也只把探针的**位置**留给模型。

**往提示词里加东西之前，先想清楚它落在这条线的哪一侧。**

## 仪表：探针与空真检查

主线的 `extract_flow` 用模板把探针发下去，模型只填"写在哪"，`flow_reachability`
再问 ProVerif 每个角色能不能走到那儿。baseline 自己写整份文件，所以同一份契约写进
**提示词**（`<honest_run_probe>`），放置规则由 `experiments/oneshot/probe.py::placement` 机械
校验——规则和措辞都是主线那套，不重写。

**不能机械插探针。** 成功位置只能由模型指：EDHOC draft-08 写的是
`if 收到错误 then 0 else <整条协议>`，框架自己往"进程体最后一个 `0`"插会插进错误分支，
对着一份正确的模型报"角色不可达"。放在 baseline 上更糟——这是要写进论文的**测量数**，
假阳性等于往自己有利的方向作假。

**空真检查**回答另一个问题：认证目标写成
`inj-event(end_g(x)) ==> inj-event(begin_g(x))`，`end_g` 从不发生时 ProVerif 把它证成
**true（安全）**。追加一条 `query event(end_g(x))`（类型从模型自己的 event 声明抄）
就能把"安全"和"空真"分开。保密目标没有 `end_` 事件，也就没有空真查询——它的见证值只在
进程体内部可观测，追加声明够不着，这条边界是明写的，不是漏了。

**每个场景三次 ProVerif，因为没有两件事能共用一份文件：**

1. **提交态**——在模型回复前机械加 `set reconstructTrace = false.`，作为 one-shot 的
   语法关和探针求解；原始回复仍单独保存在 `reply.md`；
2. **`remove_probe` 之后**——喂 results.json 的目标 verdict，来自一份不带我们任何仪表的
   模型。这里调的**不是** `strip_probe`：它还会把具名信道改公开，而场景模型里的
   `[private]` 可能是场景自己的机密信道假设，不是探针留下的。这一步永远重跑：第 1
   次带着 `reconstructTrace = false`，可证伪的目标在它下面会报 cannot_be_proved，
   所以哪怕模型压根没写探针、两份文本只差那一行设置，也不能拿第 1 次的结果当目标
   verdict；
3. **去掉模型自己的 query、只留空真 query**——`query event(end_g(x))` 和目标自己的
   query 都带 `g`，塞在一次运行里靠字符串分辨就是在猜。

第 2 步若有目标返回 `cannot_be_proved`，再按目标各跑一次 preciseActions；已判定的目标
绝不重跑。`reconstructTrace` 已随探针剥掉，不进入目标求解或 preciseActions 文件。

我们从模型文本产出的文件跑不过 ProVerif 时，抛 `InstrumentationError`——那是**我们的**
错，不是 baseline 的，必须响亮。

**探针的代价要记着**：baseline 因此多了一件可以做错的事。`run.json` 把
"没标探针 / 标错位置"（`probe.problems`）和"标了但不可达"（`reach`）分开记，正是为了
论文里能分开报。

**这个代价已经真的发生过一次，而且是提示词的错。** 约束 13 第一版写的是
"`event reached_X().`，带进程终止句点"，模型照做，把句点写在了一条 `then` 分支的末尾、
`else` 前面——语法错误。5G-AKA 的 `binding_backhaul` 三轮修复全烧在这上面
（2026-08-24）。句点只在这条分支同时是**整个进程体末尾**时才对，措辞把特例写成了通则。
现在的措辞直接照抄主线 `extract_flow` 的约束 17/18，连同主线约束 15（"只有文档说明了
检查失败会怎样时才写 `else`"）一起搬过来——正是这条缺失让模型写出了
`then <探针> else 0` 这种结构。旧实验曾靠修复轮通过；当前 baseline 不再修复，因此
**动这段措辞时先想清楚 if/else 中间的分支长什么样。**

**同一次事故还暴露了第二件事：baseline 提示词整份没有 `<example>` 段**，也就没有任何一处
出现过 ProVerif 注释，模型于是按 C 风格写了 `/* ... */`，两个场景的第 0 轮都死在这上面。
主线有 12 处 `(* ... *)`（模板头 + 三个示例片段），注释风格是**被示例带出来的**，不是靠
一条规则。现在 baseline 也照这个办法补了一个 `<example>`，内容是主线示例里的探针片段。
**别用"加一条注释语法规则"去代替它** —— 那会在提示词里多一条主线没有的约束。

## 命名契约

verdict 的归属不靠 query 顺序（ProVerif 会重写 query），靠**名字里带目标 id**：
`free w_<goal_id>` / `event begin_<goal_id>`。提示词把这条写成最硬的约束。

主线的 `split_by_goal` 遇到"一条 query 谁也不属于"或"同时属于两个目标"会直接报错；
这里记成 note 并把该目标判 `unknown`。对 baseline 来说**这是测量结果，不是代码
bug**——它写不出可归属的 query 本身就是数据。`runner.py` 的 `split_verdicts` 因此
自己实现，但归属判定复用 `query_owners`，两边是同一把尺子。

同理，一个场景跑挂了要记 `status: "failed"` 并把目标判 `unknown`，不要抛异常。
**脚本自己的错**（配置缺失、语料读不出、claims 解析不了）照旧显式报错。

## 实跑记录（2026-08-24，5G-AKA/AKA，gpt-5.6-luna，effort=high）

**探针第一次赚回了自己的成本。** 两个场景都产出了 ProVerif 接受的模型，
`binding_backhaul` 的 19 条目标里 18 条判 true（安全），逐格对标 13/19 命中——
看上去是一份及格的答卷。探针说的是另一回事：

```
probe.problems: []            ← 三个角色都标了，位置都对
reach:  {HN: false, SEAF: false, UE: false}
vacuous: 19 条里 16 条为真
```

**三个角色一个都跑不起来**，那 18 个 "safe" 全部证在空轨迹集上，13 个"命中"是因为
该场景的标准答案本来就多半是 true。没有探针，这一列会被当成 0.68 的成绩写进表里。

`nonbinding_backhaul` 是对照：reach 3/3，只有两条 SQN 相关目标空真——
同一个模型能力，差别在这一份模型活着。

这份记录的意义不在数字，在于**"语法过了、verdict 也有"离"模型是对的"还差两道**，
而这两道正是分解买来的东西。

## 实跑记录（2026-08-22，NSPK，gpt-5.6-luna，effort=high）

**这批记录早于探针**（探针 2026-08-24 加入提示词），所以它们的 `reach` 和 `vacuous`
字段是空的，汇总时 reach 会被记成 0——那是"这个 run 没测过"，不是"测出来不可达"。
要这两个数就得重跑，别拿跨这次改动的两批数去比。

7/8 格，acc 0.88。中英文两版结果一致。剩下那格 `auth_a_to_b` 在
`attacker_controlled` 场景下判 false、ground truth 是 true——baseline 真实的建模错误。

第一版还暴露过两个提示词漏洞，都已修进约束：模型把"进程体以 `0.` 结尾"误用到
main process（写成 `).`，语法错误），以及 `fun adec(...)` 和 `reduc` 里的 `adec`
重复声明。修完之后那个场景从"四轮报废"变成"两轮跑通"。
