# TODO

只记**还没做的**，做完一条删一条（做过什么去看 git log）。节点的设计与边界写在各
节点自己的 docstring 里；协议级的坑归
`.agents/skills/experiments/references/protocols.md`。优先级 P1 > P2 > P3。

---

## P0 USENIX artifact 交付

已投稿，声明会开源 Orrery、VerdictBench 和实验产物，匿名链接
https://anonymous.4open.science/r/Orrery-F56D 。

产物的三段流水线已经做完，各做一件事，后一段读前一段（`release/usenix/README.md` 是
唯一真相）：`source_data_to_3_latest.py` 选出论文用到的 568 个 run 并对着论文自己的
run 缓存逐个校验 → `latest_3_to_remove_sensitive_open.py` 去隐私、把受版权的规范正文替换成等长占位 →
`open_to_thin.py` 瘦身成 14.57 MB / 3609 个文件。验收做到了「论文脚本读 thin 重算出的
`measured.tex` 与已提交版逐 macro 一致」。

语料一个字节都不打包：`run.json` 里的 ground truth 是产出机器上的绝对路径，控制台把
它重新锚到 `paths.lib_root`（默认就是并排的那个 checkout，正是发布目录的形状）。
旁边没有 Bench 时 run 照样完整回放，只是不提供对照面板。

**Web 回放已经做完**（英文界面用 `recorded`/`live`，不用 `replay`——本领域 replay
指重放攻击，而 Denning-Sacco 正是靠重放攻击被证伪的可回放协议之一；代码里这套东西
叫 playback，仓库里 replay 一词只在"攻击"和"把 transcript 重新喂进去"两个既有含义上
出现）（`orrery/api/playback.py` + `orrery/web/server.py` 里十几行
`app.state.playback.<x>` 形态的切口）：控制台默认就是回放模式，左上角一个开关切实跑。
回放是账本的第二个生产者，durable 帧逐字节等于 `events.jsonl`（`tests/unit/api/
test_playback.py` 把这条断言成测试），逐 token 片段从 transcript 的 `assistant` 重建、
铺在 `prompt_filed`→`round_started` 的间隔里，倍速按每个 run 自己算，落在 50–70 秒。

剩下的：

1. **产物自己的 README**。thin 里现在只有数据没有说明，得告诉审稿人哪 7 个协议能
   回放、怎么起控制台、其余是论文数据层、完整数据在哪。
   顺带：**匿名发布仓库还没有组装步骤**。开发仓库 gitignore 掉 `runs/` 和
   `VerdictBench/` 是对的（不该把产物和语料压进开发历史），但那意味着
   Orrery-Anonymous 是另一个仓库，得有个脚本把源码 + runs + VerdictBench 装到一起、
   写好 README、`git init`。这一步现在不存在。
2. **`a_experiments_open`（561 MB）挂上去**，拿到匿名链接填进上面那份 README。
   不能挂 Anonymous GitHub——它的仓库上限是 60 MB（`src/config.ts` 的
   `MAX_REPO_SIZE`），USENIX 的政策原文点名推荐 OSF 这类能生成匿名链接的库。
3. ~~产物的落位~~。已定：匿名仓库根下三个主目录 `orrery/`、`VerdictBench/`、
   `runs/`（thin）。回放根默认 `runs/main`（`paths.playback_root`，可在 config 或前端改），
   `paths.lib_root` 默认改成 `./VerdictBench`。审稿人克隆一次、起服务即可。

## P0 工件入口：审稿人第一次运行

来源是实测：`anonymous_release.py --keep-stage` 造出真正的评审版暂存树，拷到干净目录，
新建 venv 装一遍，然后逐个入口跑。
**已过的**：`pip install -e .`、无 key 直接进 recorded 模式（7 个协议）、回放全链路、
`experiments.reproduce`（六份产物）、`orrery kb` / `config` / `prompt`、跑批三命令
（preflight、未完成 run 时拒绝启动、换 backend / 换 solver 时打印偏离）。剩一条：

1. **LICENSE / 永久存档：现在不用，接收之后必须**。查过 USENIX 的规程（'26 CFA、
   secartifacts 的 submission 与 available instructions、'27 CFP）：**LICENSE 文件不是
   任何一个徽章的要求**，"license" 在 USENIX 文档里只作为「不能分享」的**理由**出现
   （licensing restrictions / NDA）。匿名评审版更不需要——AE 流程是 **single-blind**，
   匿名只约束**投稿时给的那条链接**。

   真正的约束在别处，而且和现在的计划冲突：**Artifacts Available 徽章要求永久公开存档，
   且明确不接受 GitHub / GitLab / 个人网站**，只认 Zenodo、FigShare、Dryad、
   Software Heritage 这类。而 Zenodo 这类平台在存档时**必须选一个 license**——所以
   license 是「接收之后做永久存档」那一步冒出来的，不是现在。

   连带两条要记住的：camera-ready 里要放永久链接和 `\usepackage[available]{usenixbadges}`；
   '27 CFP 对匿名链接的要求是「无跟踪机制，不得暴露用户名、组织名、**commit history**」
   ——发布脚本已经把提交身份设成 Anonymous 且目标仓库是独立历史，符合，但别把真实历史
   推上去。

**还有一件设计上要重新决定的**：回放模式没有出现在任何一份 README 里。这是整个工件对
审稿人最友好的东西——零 key、零 ProVerif、7 个协议连提示词、模型回复、verdict 和
ground truth 对照一起重放——却只写在 `orrery/web/serve.py` 的 docstring 里。工件
README 现在的开头是「两个必填项」，读完的第一印象是「没有 API key 什么都看不了」。
这一段应该是 README 的第一节。

**`tests/` 不发**这件事现在是有意的、也说得通：`orrery prompt` 的 fixture 已经搬进包里
（`orrery/utils/prompts/fixture`，契约测试盯着它进 wheel），所以工件里没有一条命令依赖
`tests/`。代价是审稿人没有「不花 API 钱的功能自检」——`reproduce` + 回放已经很接近，
但没有一条命令叫「验证工件能工作」。要不要补一条，随 README 那件事一起定。

## P0 提示词漂移：把应对材料做成可复算的脚本

**事实**：论文的重复运行跨越了框架开发期的多个提示词版本。用 `extract_principals`
的提示词做探针（它只吃文档、不吃上游产物，所以同协议跨 run 的差异必然是模板本身变
了），101 个协议里 **52 个**的三次跑用了不同版本；baseline 那边 244 个 (协议,场景)
组合里 116 个用了不止一种。差异是实质性的，例如 principals 的输出 schema 删掉过
`signing_keypairs` 整个字段。

**已经量过的结论**（这次是手算的，没落成脚本）：

| | |
| --- | --- |
| 跨版本的 acc 变化 | +0.018，95% CI [-0.030, +0.065]，t=0.72 |
| 符号检验 | 变好 12 / 变差 9 / 持平 24（n=45） |
| **同一版本内的运行间波动** | **平均绝对差 0.073** |
| 跨版本的 | 平均绝对差 0.094 |

也就是说，提示词变化带来的差异和同一提示词下本来就有的运行间波动是同一量级，而论文
对三次取均值正是为了抹平后者。论文里那句 "we report means over \nRuns{} runs rather
than a bit-identical output" 已经把三次均值定位成对付不可控变异的手段，漂移落在它的
射程内。

**要做的**：写成 `experiments/` 下的一个脚本，让审稿人能自己复算这组数，而不是只能
听我们说。论文冻结了改不了正文，所以这是被问到时的备答材料，不是主动披露。

**它没证明什么，得写进脚本的 docstring**：它说的是没有净偏移，不是单个协议的数字不
受影响——个别协议的跨版本差最大到 ±0.5。

# P1

## GOALS 检查层四条机械不变量

未动工，按优先级：

1. **phase 钉相位**——v7 的 `phase_shape` 检查未迁入，是实缺口，最要紧
   （不钉会让前向安全类目标过度声称）；
2. inj 形态 ↔ subtype 一致（EDHOC 假 true 的结构性封堵）；
3. witness 三件套完备（free + query + out 恰各一）；
4. 事件配对参数类型逐位一致。

## 提示词与诊断的欠账

- **修复轮诊断缺放置位置**：错误形态整体从「缺守卫」迁移为「位置错」，说明位置
  规则是模型最稳定的盲点。改 `orrery/checks/rules/goals.py` 的文案，并考虑把
  「守卫置于最后一条协议发送之后」在 injector `.md` 里独立成小节。

# P2

## 场景段改动范围检查

**目前没有任何编辑范围围栏。** ScopeSpec 四谓词已整体删除：
它判的是锚定方式而非改动内容，`lifted_parameter` 每次固定浪费一轮，而锚得够细照样
能改坏内容。要重新加就只加**确定性**的——判据必须落在改动后的文本上，而不是落在
anchor 的写法上。另：各提示词里「范围之外的差异会被框架退回」的空头承诺句要扫干净。

## identity 检索里的 `ca` 权重哨兵

`IDENTITY_MODELING.yaml` 的 `identity.signed_certificate` 别名表里有一条
`ca ca_alias_weight_sentinel`，不是任何人会写的短语，是为保持打分不变留的占位。
**yaml 里刻意不写解释**（那份文件审稿人要看），来龙去脉只在这里。

来历：原先那条是中文别名，`retrieval.py` 的分词正则 `[a-z0-9_]+|[\u3400-\u9fff]+`
把它切成 ASCII token `ca` 加一整块 CJK，于是**只要 query 里出现 "CA" 这个词，这个
条目就白拿 +2 分**——包括那些明说「本协议没有证书、没有 CA」的 query。开源清中文时
其余 37 条中文线索删掉零影响（它们不含 ASCII token），只有这条有实际权重。

实测（`a_runs` 里 221 条真实 identity query）：直接删掉，19 条（8.6%）返回的候选集合
或顺序改变。典型是 NSSK——纯对称密钥、query 字面写着 "No certificates or CA
validation exist"，`signed_certificate` 靠这 +2 分从 11 分升到 13 分，挤掉
`private_provisioning` 进了前三。**删掉之后的结果更对**，所以这是个该修的 bug，只是
修了会动历史数字。

待办：下次重跑基线时把这条哨兵直接删掉，同时确认 19 条变化都是往好的方向。
触发器 = 主线实验重跑、不再需要和已投稿数字逐位对齐。

## `prompt_lang=zh` 的建模库检索已失效

开源清中文时，三个 `kb/modeling_idioms/*.yaml` 里 37 条中文线索词（`aliases` /
`positive`，不是提示词，是 `retrieval.py` 的匹配数据）被删掉了。后果是中文 query 在
三个库里全部 0 分：

- **identity**：返回空列表 → 走 `[identity-modeling-coverage-gap]` 那条报错分支。
  模型被告知「建模库没覆盖」，同时被禁止自己发明 CA/registry——等于身份建模在 zh
  模式下没有指导。
- **time**：全 0 分后靠 `_DEFAULT`（`time.opaque_fresh_value`）兜底，答案恰好还对，
  但检索本身没工作。
- **structure**：库里只有一条，恒返回它，退化看不出来。

**连带一条测试变成空跑**：`tests/unit/modules/test_time_variant_modeling.py:27` 的
`PLAIN` 里那条中文 query，断言它落在 `time.opaque_fresh_value`。现在还是绿的，但走的
是兜底而不是检索——测试保护的东西已经没了。别被 916 passed 骗了。

**不影响实验**：`prompt_lang` 默认 `en`，三个 batch 都在 `experiments/batches.py`
里显式钉了 `en`，api/web 也不暴露这个开关，只有手改 config 才进 zh 模式。

三条路，按倾向排序：

1. **正式退役 zh 检索**——删掉那条假绿的测试用例，在 `retrieval.py` docstring 写明
   检索只吃英文 query。zh 提示词继续可用，只是模型别拿中文去查建模库。
2. **线索词按语种进 yaml**——加 `aliases_zh` / `positive_zh`，装载时按 `prompt_lang`
   选。zh 恢复原状，代价是 yaml 里重新出现中文（匹配数据，不是提示词）。
3. **让 zh 提示词产出英文 query**——改 4 份 zh 提示词并重新对读，改动最小。

触发器 = zh 模式真要用于任何正式产出时；在那之前它就是坏的，别假装它能用。

## 写集不相交只是散文契约

四处注释写着 "disjoint by contract"（build_root 的可交换层假设互不相交），没有任何
机械验证。真撞上了顺序就承载语义，而 root 层的全序只是为确定性。

## expert

- **跨进程零互斥**。两个 chat 会话对同一个 run、或一边跑流水线一边在 chat 里执行
  修正，都无拦阻。不变量是「一个 run 目录同时只能有一个写者」，所以锁该是 run 级、
  流水线与 expert 共用。拿不到锁就拒绝并说明是谁占着（锁文件记 pid，进程已死则接管）。
- **确认框没有钱**：`FixCost` 数的是「作废几个文件」，用户要决定的是「这次重跑花
  多少」。留痕里每次调用的 usage 是现成的。
- **纯代码节点也应该可修**（2026-08-16 用户要求）。现状：`fixes._resolve` 已经拒绝
  `model_driven=False` 的目标（load_document / aggregate / cross_check 三个），
  所以它们现在是「不能修」而不是「假装修了」。目标仍是**让它们也能被修**——属新
  能力。动工前先定义「纯代码步骤能接受什么样的指令」。
- **expert 的流式只到片段为止**：emitter 已接进 `run_agent`，`ModelDelta` 进 bus，
  `/chat/stop` 能取消回合；剩下的只是「后端不流式就没有片段」这条既有约束。

## 2026-09-15 全栈审查留下的逻辑问题

机械可修的都已改掉并有测试；下面是真要裁决才能动的。

- **`reproduce.py` 的「最近三次」窗口按 kind 取不按 status 取**。失败、中断、被
  kill -9 后停在 running 的 run 各占一席，把更早的完整 run 挤出窗口，却又因为
  `agg_state != scored` 不进均值——样本变少而不计为 miss；在 extract_flow 之前就死
  的 run 则整个跳过（报告里列为 not scored）。两种失败待遇不对称。下一次实验设计
  指标时定：窗口取最近 N 次**尝试**并把失败计为 miss，还是取最近 N 次**打分成功**
  的 run 并另报失败率。消融表 `match` 的口径已经和 `fold()` 统一（旧标尺 run 剔除），
  按新口径 `\abLargeMatch` 是 275.5 而不是投稿版的 321.5；投稿版的数字已随论文
  冻结，这里的改动只服务下一次实验。
- **`/api/browse` 能列本机任意目录**：本地工具的既定选型；`--host 0.0.0.0` 时等于把
  文件系统目录结构暴露出去。写操作已加同源守卫（跨站页面发不动 interrupt / approve /
  stop），读操作要不要也挡，是要不要做鉴权的裁决。
- **回放到未回复的 `expert_asked` 时看不到「提问进行中」**：置 `state.asking` 的代价
  是服务器崩溃后永久锁死，两边都不对。
- **`reject_double_answers` 在真实路径永远不触发**：`validate_assumptions` 已按
  (axis, instance) 拒绝，条件只能引用 variable 条目，fixed ∪ conditions 不可能撞键。
  `reject_commitment_conflicts` 同理（无 realizer 声明 conflict）。留着当纵深防御和
  扩展点不花钱，只是 AGENTS.md 里"claims 关卡再拒一次"是名义上的。

## 攻击复现（第 13 步）的遗留

设计与细则见 `docs/attack-reproduction-design.md`。

- **超过 120 步的轨迹还没见过**：除了七个回放样例，又拿 `a_experiments_open/` 里
  五个大协议（EDHOC-draft-12-dh、TLS13-draft20、5G-AKA、ISO-9798-3 tp-mut-3、
  FIDO-UAF 注册）只重入第 13 步试过（`a_runs/_attack_trial/`），25 格全部复现并写出
  讲解，最长的脚本 26 步、会话最多 10 条。超过 120 步的截断提示、长格式超过
  `attacks.long_timeout_s` 退回默认显示，仍然只有单测走过。
- **讲解质量只逐字读过几格**：七个可回放 run 共 27 格都写出了讲解，抽看的
  Denning-Sacco 重放和 ISO-9798-2 的分组总结都讲对了，其余没有逐格核对。超过 10 格时
  的轮转挑选只在 ISO-11770-3（18 格做 10 格）上走过一次。
- **回放样例的第 13 步是本机补跑的**：`runs/main` 下 7 个可回放 run 已经在本机
  重入 `reproduce_attacks` 补上了这一步（讲解用的是现在的模型，不是当初那批实验）。
  它只写在瘦身树里：发布流水线第 3 步（`release/usenix/open_to_thin.py`）从
  `a_experiments_open/` 重建时会丢，而且瘦身规则不保留 `02_proverif_trace_*.txt`，
  那是第 13 步重跑攻击要读的文件。真要重建发布树，先把这两件事补进流水线。

## review 遗留

- reviewer 审查失败与「通过无发现」在 review.json 里无法区分，返回加显式状态字段；
  顺带收口它散文违规时 `OutputFormatViolation` 的 traceback 打印（会泄到批量宿主
  控制台）。

## 逐句对读六项只做完第一项

verdict 全对只是必要条件。②认证事件 keying ③诚实对端判别位置 ④消息结构保真
⑤原语用法 ⑥secrecy 探针绑定，要在新产物上系统做一遍。旧案：begin 插在解密前
（过度声称安全方向）、Neuman-Stubblebine 标准 query 带时序我们没有。

## 词表三条未裁的设计问题

（其余词表条目均已解决）：

1. **weaksecret / 事件例外档的目标侧契约未按 "Downstream contract" 格式声明**
   （`primitive.broken`：低熵值走 weaksecret 查询，目标从可达性机密改抗猜测；
   DH/KEM 走 query 加事件异常析取，true 语义弱化为「泄漏被例外覆盖」）。参照
   `admission.open` 的写法补进 realizer docstring。
2. **`primitive.broken(v)` 与 `data.assumed_secure(v)` 是否冲突**——「能离线猜出」
   与「永不获得」的相互作用取决于 weaksecret 的实现语义，落地前不定、不实现。
   这是全词表唯一悬而未决的冲突对（其余 conflict 已审计干净：denies 性质的子类只有
   `assumed_secure` 一个，reuse 族刻意不冲突，noop 一律中立）。跟第 1 条一起裁。
3. **channel 轴三个能力位折进一轴，绑定位不对称**：读×伪造 2×2 之外的会话绑定位
   只在 secure 角展开（secure vs secure_nonbinding），authentic / confidential 无
   nonbinding 变体且无声明说明是刻意裁剪。候选：绑定独立成问题，或轴文档写明裁剪
   理由。

## `check_failed` 把「评分不满分」表达成了「运行失败」

一个根因，两处症状。cross_check 发现格子与 ground truth 不一致时抛
`CheckFailed` —— 这是全代码库唯一一处抛它的地方。它之后的步骤只有声明了
`runs_after_check_failure` 的才照常跑（现在是 `reproduce_attacks`），跑完 run 仍记
`check_failed`。

1. **退出码把评分当故障**：`main.py` 的 `return 0 if r.status == "ok" else 1`，
   于是「acc 87.5%」和「节点崩了」「配置没填」同一个退出码 1。而同仓库的批次
   runner（`experiments/batch/orrery.py`）自己判 `status in ("ok", "check_failed")`
   都算跑到底了 —— 两层对同一件事的判断是矛盾的。改前先确认没有 CI/脚本依赖当前
   退出码；要区分就用单独的码或 `--strict`。
2. **状态值本身**：run 完整跑完、产物齐全、报告已写，没有任何东西失败，叫
   `check_failed` 不对。但它是持久化值 —— `runs/` 下 122 个 run 的 `run.json`
   和 `events.jsonl` 里写着它，是论文数据和回放素材，改值会让历史 run 读不出状态，
   还牵动批次 runner 和 6 处测试断言。

**已经做了的**：只改表达层（控制台显示名、配色、图标、CLI 措辞），状态字符串没动。
退出码和状态名是一次真重构，要挑不赶论文的时间一起做。

# P3

- **检查层粒度**：waives 太宽——realizer 声明豁免某检查时是全场景豁免，机制支持
  `检查id:key` 精确豁免但没人用，真问题被一起消音过（Otway-Rees 实例）；生效探针
  在只给 holder 的 target 上静默失效（LIB 有 10 处 holder-only）。
- **提示词侧三条只能靠实测收口**：① `flow` 提示词里两个脚手架块（接收态五步节奏、
  值来源四分，合计约十五行）要不要删——低资源 DSL 的实证倾向是「留」，删之前必须
  ablation，一次一块才能归因；② init_knowledge 的 `description` 四段式散文该拆成
  四个 JSON 字段（现无人按分隔符切分，不是活 bug，但两个模型之间的约定靠字面维持，
  漂了没人拦）；③ 一份提示词是否真能通吃三家——在每家都有独立 baseline 之前，
  这是未验证的假设。
- **能力下沉小账**：solve 与 cross_check 的比对逻辑是纯领域能力却住在节点里，该下沉
  `orrery/modules`；aggregate 自己实现了一遍三值合取，改调 `verdicts.combine`；
  三个上游 node.py 重复约七成，加第四个上游步时提取共性。
- **未接的目标类型与语料**：Equivalence / Privacy 无注入器（unlinkability 要 choice
  编码）；ISO 的 freshness 轴 KB 没有（Kerberos §1.6 是它的实证需求方）；UAF 依赖
  `honesty.malicious_possible`（stub，机制已定死在其 docstring：初始知识含信道项
  全泄漏，rules 落地是机械活），接入时按 authenticator 类型拆子协议目录；
  v5 遗留 LIB 目录「接哪个迁哪个」（SSHv2 与 TLS13/draft21 已裁决放弃，恢复条件写在
  各自 README）。
- **用户 2（最小假设集搜索）**：调用形状已就位（不给 claims 即用户 2，claims 节点现
  报「未接」）。缺搜索驱动（枚举 + 单调剪枝 + 反例检测）。轴内 stronger_than 已在
  KB 声明；跨轴蕴含边按定案不声明，极小化靠删一条重验证，蕴含边只作剪枝优化按需
  再立。产物 = 完整场景矩阵 + 每目标极小充分集族。**前提是 verdict 可复现性**
  （Neuman-Stubblebine 实测：同一假设集两次跑可能回 unknown）：候选是固化改法后
  重放、每场景跑 k 次取多数、或推理带置信度。

# 触发器清单（到点才建，没到不要提前建）

每条写「待建的东西 —— 触发器」。触发器没到就不要动工。

- **context editing**（resume 时把陈旧 tool_result 换成占位符）——第一次真实修正后
  观测到 expert 拿旧产物答话。
- **position-free 支路通道**（`append_main_branch`）——题面真出现双 holder 同场景
  泄露，或锚失配率实测偏高。
- **跨家族合并注入**——场景段改动范围检查建成。
- **跨 run 编译重放**——用户 2。
- **entity 状态同步轴**（SQN 漂移），以及 `sqnlevel`/`pred`/`isFresh` 与类型白名单的
  冲突裁决——5G-AKA 接入定案时。
- **会话配对结构轴**（`!(A|B)` vs `!A|!B`）——出现消费协议。
- **key confirmation 断言点维度**——5G-AKA / ISO 11770 接入。
- **ISO Annex B 三孤儿目标**（implicit key auth / key freshness / key control）
  ——11770 接入。
- **条件化与时序查询的事件形态**——Signal 时序目标真要接。
- **`flow` 逐轮 `r<N>.pv` 落盘去留**——待用户裁决（建议不落，全文已在留痕）。
