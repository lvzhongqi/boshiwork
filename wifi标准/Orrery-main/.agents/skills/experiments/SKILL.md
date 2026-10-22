---
name: experiments
description: Orrery 的**正式实验**——在远程服务器上经 batch runner 启动、协议命名与配置口径、批次管理，以及正式实验跑完之后定位 run、判断节点产物对错、追根因。只在结果要进论文／回归／指标时使用；本地 a_runs 里跑一个协议看看通不通属于开发调试，命令在 AGENTS.md，不需要本文。触发词：正式实验、远程实验、batch runner、批量跑协议、实验指标、分析实验结果。
---

> 命令里的 `$SRV`、`$EXP*`、`$RSRC`、`$RLIB` 等占位符在 `CLAUDE.local.md` 里定义
> （本机配置，不入库）。

# 实验

从启动到读结论的全流程。三份 references 按需读：

- 同步规则、远端环境安装、批次管理命令（查进度／看日志／中断／恢复／重跑）
  → [references/remote.md](references/remote.md)
- 五轴假设词表的完整档位与语义（判断 assumptions/claims 产物对错时查）
  → [references/vocab.md](references/vocab.md)
- 各协议的特殊情况（这个协议独有的、会绊倒下一次运行的事）
  → [references/protocols.md](references/protocols.md)
- one-shot baseline 对照实验（`experiments/oneshot/`）：它是什么、为什么不在
  `orrery/` 包里、怎么改它
  → [references/oneshot.md](references/oneshot.md)

---

## 一、跑实验

### 先分流

**结果算不算数**决定走哪条路：

- **要进论文、回归、指标、对比** → 正式实验，远程服务器 + batch runner，往下读。
- **改完代码想看看跑不跑得通** → 本地调试，用 `orrery.main run`，命令见 `AGENTS.md`，
  结果落在本地 `a_runs`，不作为任何指标。

两条路不能混。误在本地生成了正式 run，必须按远端现有编号连续追加迁移到对应目录，
并以远端副本为准。

### 未指定运行方式时的默认口径

用户只说"运行某协议"而没有指定输入与执行范围时，默认按以下方式运行：

- 新建 run 不传 `--run-name`，由程序在对应协议目录下自动分配
  `<protocol_id><NN>`（如 `NSPK01`、`NSPK02`）。只有重入已有 run 时，才把该 run
  已经分配到的名字传给 `--run-name`；不得为新实验手工另造命名体系。
- `--name` 必须填写 VerdictBench 中该协议的规范名称，不能用实验名、简称或
  任意目录名代替。大协议还必须按 VerdictBench 的目录身份正确传入 `--version`；存在
  多个分析目标时必须正确传入 `--subprotocol`。三者共同生成的 `protocol_id` 必须与
  VerdictBench 对应条目的 `protocol_id` 完全一致。
- 必须使用英文提示词：运行所用配置的顶层字段必须显式写为 `prompt_lang: en`。不得依赖
  默认值，也不得在正式实验中使用 `prompt_lang: zh`。
- 使用协议目录自带的 `annotations/` 作为 section 标注输入；`tag_sections` 只走已有
  annotation 的跳过分支，不调用 LLM 重新提取。若目标语料没有可用 annotations，直接
  停止并向用户确认，不得静默退回 `tag_sections` 提取。
- claims 使用 LIB 三件套，即 `inputs.lib_claims: true`，直接供入
  `claims/{assumptions,properties,claims}.json`。
- principals 与 flow 不使用 LIB，分别运行 `extract_principals` 和 `extract_flow`；随后
  运行场景中的 `apply` 与 `inject`。对应输入默认是 `inputs.lib_principals: false`、
  `inputs.lib_flow: false`、`inputs.end_point: scenarios`。
- "只跑 `extract_principals`、`extract_flow`、`apply`、`inject`"指只有这四类阶段允许
  发生 LLM 生成。`load_document`、LIB claims 的装载与关卡、`build_world`、
  `build_root`、`aggregate`、`cross_check` 等编排和机械节点仍按依赖正常执行。

### 正式启动：只使用 batch runner

正式实验不在服务器上手写 `orrery ... run <protocol>`，也不逐协议启动进程。唯一启动
方式是：**本地改完 → rsync 同步 → 登录服务器 → 在 Orrery 根目录跑 batch 脚本**。
服务器只负责执行，不得直接修改源码、`experiments/**/*.yaml` 或 VerdictBench。

同步命令与规则见 [references/remote.md](references/remote.md)。同步完成后：

```bash
ssh $SRV
cd $RSRC
source $RCONDA/etc/profile.d/conda.sh
conda activate orrery
```

三个正式启动命令：

```bash
# 主线实验
python -m experiments.batch run main

# claims 提取实验
python -m experiments.batch run claims

# one-shot baseline 实验
python -m experiments.batch run baseline
```

**一个入口**，三个 batch 都走它——谁用哪个 runner 写在 `experiments/batches.py`
的 `RUNNERS` 里，不用记。必须用 `-m` 模块形式，直接跑文件不会把 Orrery 根目录放进
`sys.path`。

长实验用 `tmux` 启动。不要在命令行传并行度；并行度只由 `$RSRC/experiments/config.yaml`
的 `max_runs_concurrency` 控制。新 Orrery run 仍不传 `--name`，batch 会记录程序
自动分配的 run 名。

**跑批读的是 `$RSRC/experiments/config.yaml`，不是根目录那份。**两份互不相干：根
目录那份是单跑和控制台用的，跑批这份只有凭据、语料、输出目录和并行度四样。启动前
确认它的 `paths.work_root` 指向实验根 `/home/xiaonan/lab/orrery/experiments`；
batch 名会被追加上去，启动时打印的 `batch X: runs -> …` 就是结果，对不上
立刻能看出来。第二行还会打印实际用的模型，和论文用的 `gpt-5.6-sol` 不一致时当场
说出来。

`prompt_lang: en`、预算、inputs 全部钉在 `experiments/batches.py` 里，任何配置
文件都覆盖不了——所以不用再担心谁的私有配置漏进实验。

四个命令，一个参数：`run` / `status` / `stop` / `resume` + batch 名；`run` 后面
再加一个协议 id 就只跑那一个协议，`resume` 必须带协议 id 和 `--from-node`。

`run` 是启动一批，不是修一批：**只要有协议手里攥着一个没跑完的 run，它就停下来报错，
一个子进程都不起**。接续用 `resume <batch> <protocol> --from-node <node>`（run 被
中断时自己会把节点名打出来，`status` 也会给出 run 名）——**不要**用 Orrery 自己的
`--run-name` / `--from-node`，那条路拿不到 `batches.py` 的实验设置，会用默认配置
把剩余节点跑完并重写 run 的 config.yaml；不想接续就把那个 run 目录删掉，再 `run`
就会重新起它。

`stop <batch>` 先给这一批的调度器发一次 Ctrl-C（它会停掉所有子进程、不再起新的），
再扫一遍调度器已死但子进程还活着的 run 逐个中断；每个 run 自己收尾，之后仍可重入。

---

## 二、分析结果

### 定位实验结果

1. 定位实验目录。**正式实验在远程服务器**
   `$SRV:$EXP/{main,claims,baseline}`（占位符见 `CLAUDE.local.md`），
   分析指标一律以远端为准。本地 `a_runs` 只是临时调试产物，不作为任何实验结论的依据；
   只有用户明确说"看本地那个"时才去那里；
2. 定位协议，用户通常会给出哪个协议的提取实验，如没有给出，则询问用户；
3. 定位具体的 run，默认分析实验项目下最新一次运行，目录下有 `latest` 连接，或访问编号最大的目录；

### 读取约定

run 目录的树如下，如果与事实不符，则通知用户（可能过期）。

```text
<work_root>/<协议>/latest -> <run 名>          指向最新一次 run 的符号链接
<work_root>/<协议>/_ground_truth/              ground truth 本地副本，协议级别，不属于任何一个 run；
                                               只在跑过带 ground truth 的 run 时才有，对照标准写法找这里，
                                               不用去外部语料库
    ├── claims/                                assumptions.json、properties.json、claims.json
    ├── source/                                协议源文档
    ├── formal/                                标准形式化代码，比如 proverif/main.pv
    └── results/                                results.json、cases_results.json

<work_root>/<协议>/<run 名>/
├── run.json                    run 状态 + 每个节点的结果
├── stages.jsonl                索引：每一次执行，按发生顺序
├── events.jsonl                事件流
├── gaps.jsonl                  gap 上报审计（第一次上报才会有）
├── work.md                     整条流水线的可读投影——分析永远从这份开始
├── _review.json                控制台写的人工审阅状态，不是节点产物，可能没有
├── 01_extract_principals/
│   ├── principals.json         参与方 + 各自初始知识
│   ├── quotes.md                支撑证据引用
│   ├── transcript.jsonl
│   └── rounds/                  每一轮的提示词与产物，00_prompt.md 打头
├── 02_extract_flow/
│   ├── flow.pv                  flow model
│   ├── checks.md                检查结论
│   ├── transcript.jsonl
│   ├── rounds/
│   └── review/                  独立复核，warning 级、不阻断
│       ├── review.json
│       ├── transcript.jsonl
│       └── rounds/
├── 03_extract_assumptions/      {assumptions.json, quotes.md?, transcript.jsonl, rounds/}；用户给了就没有会话
├── 04_extract_properties/       同 03，跟它并行跑，谁先分配到号不固定
├── 05_extract_claims/
│   ├── assumptions.json         从 03 原样搬一份，claims 判定要用
│   ├── properties.json          从 04 原样搬一份
│   ├── claims.json               哪个目标在哪些场景下被声称
│   ├── transcript.jsonl
│   └── rounds/
├── 06_build_world/apply/
│   ├── <NN>_<假设子类>/         一个 world 层假设一个目录，串行
│   │   ├── transcript.jsonl
│   │   ├── applied.pv           施加完这一条之后的模型
│   │   ├── rounds/
│   │   └── classify/            仅多写法假设才有：先判断该用哪种写法
│   │       ├── transcript.jsonl
│   │       └── writing.json
│   ├── world.pv                 施加完全部 world 层假设后的模型
│   └── notes.md                 施加了什么、什么本来就是 flow 的状态
├── 07_build_root/apply/         结构同上一级：root.pv 换 world.pv，假设换成可交换层的
├── 08_scenarios/<场景名>/       场景名 = claims.json 里的场景名，比如 00_baseline
│   ├── apply/
│   │   ├── <NN>_<假设子类>/     这个场景自己的条件，结构同 06/07
│   │   ├── scenario.pv          root model + 这个场景的条件，施加完之后的模型
│   │   └── notes.md
│   ├── inject/<目标族>/         一个目标族一次注入会话，比如 Secrecy、Authentication
│   │   ├── model.pv             scenario.pv + 这批目标的 query，喂给 ProVerif 的就是这份
│   │   ├── proverif.pv / .txt   喂进去的原文 + ProVerif 打印的输出，反例轨迹在 .txt 里
│   │   ├── transcript.jsonl     超过单次调用上限会拆成 call_<N>/transcript.jsonl
│   │   └── rounds/
│   └── verdict.json             这个场景下每个目标的判定结果
├── 09_aggregate/
│   ├── results.json             每个 property 的最终答案，跨场景合取
│   └── cases_results.json       每个 (property, 场景) 格子的答案
├── 10_cross_check/
│   └── cross_check.json         跟 ground truth 的逐格对错，只在给了 ground truth 时才有
└── _expert/transcript.jsonl     expert 长会话自己的留痕，下划线开头不用管
```

**两位数字前缀 = 分配顺序，不是节点在流水线表里的固定位置**——同一个节点这次是
`03_xxx`，下次可能因为重入、gap 回退变成别的号，不能拿这份骨架上的数字直接去拼别
的 run 的路径；具体这次 run 里哪个节点占哪个号，`work.md` 和 `stages.jsonl` 里都写
着。

### 分析步骤

下面这套步骤对应的是"某个判定跟 ground truth 不一致，要找出哪一步错了"这种最常
见的情况。没给 ground truth 的真实用户 run，或者某个节点直接 `NodeError` 崩了，
走不到第 2 步：前者直接看 `results.json`/`verdict.json` 是否符合协议文档描述的预
期，后者直接去崩溃节点自己的 `transcript.jsonl`/`rounds/` 里找原因，不用往下套。

1. 读 `work.md` 拿到全貌：跑没跑完、哪个节点失败或检查没过、跑了几轮。
2. 定位到具体判错的目标：看 `NN_cross_check/cross_check.json`（或 work.md 里的场
   景判定表），找到哪个 property、哪个 scenario 的 verdict 跟 ground truth 不一致。
3. 到该 scenario 目录下找这个目标的 `proverif.txt`，读反例轨迹（`goal reachable`
   / `Derivation`），弄清楚 ProVerif 具体是怎么攻破的、攻击者用了什么。
4. 拿反例轨迹里出现的具体行为，去 `<work_root>/<协议>/_ground_truth/formal/`
   下 ground truth 的标准 `main.pv`（或 `main_*.pv`），看标准写法这里是怎么处理
   的——先确认这确实跟标准不一致，而不是我们自己的模型本来就该长这样。
5. 顺着这处不一致，从生成模型的最终态（`scenario.pv`，或更上游的 `root.pv`）往
   回追，逐级对照 `world.pv`、`flow.pv`（flow 模型），看这处写法是从哪一步开始
   出现的——即推断是哪个节点产物引入的。
6. 定位到具体那一步之后，把这一步生成的 pv 和 ground truth 的 `main.pv` 再比一
   遍，确认这一步该做的事（它的语义）是不是提取/编码错了。
7. 如果同协议下还有其他历史 run（同一个实验目录下别的编号，如
   `NSSK01`/`02`/`03`），顺手对比一下这处写法——分清这次是偶然写错，还是同一条
   prompt 反复出问题，后者才值得改 prompt。
8. 到这一步如果还不能百分百确定具体哪里错，先把基于现有证据的推测性结论给用
   户，不要卡住不说。
9. 如果确认是提示词的问题，去读该节点对应的提示词文件（`orrery/nodes/.../
   rules*.md`），具体分析规则哪里有歧义或遗漏。

### 输出结论

首先一句话讲清楚根本原因出在哪个步骤，为什么错（如框架验证错，提示词设计错，抖动错误，超时错误，修复轮耗尽错误）；

其次，通过明确的 pv 代码对比示例，说清楚区别点，以及对应的错误原因。

最后，给出可能的改进方案。
