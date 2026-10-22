# AGENTS.md
## 项目背景

本项目结合大模型进行密码协议的自动形式化分析，把工业级的密码协议文档自动转换为 形式化代码，并生成安全结论，降低人工成本。

## 核心概念与用户类型

本项目的思路是，利用大模型从密码协议文档中提取 flow model（流程模型），它是一个现实世界 DY 模型下的基础运行模型。
随后，提取当前协议文档下的假设和目标。
其中，协议可能描述一系列固定的假设（可能为空）。
随后，协议描述了一系列安全属性，以及每个属性对应的假设场景（可变）。

上述情况是从真实协议而来的，进而引发了两类具体的用户，这些用户是目前学术领域的真实应用场景对应的用户。

用户 1（主线）：他问目标 G 在假设条件 A 下是否成立。
用户 2（最小化假设）。他问 G 成立的最小假设集合是什么。

本项目针对用户 1 和 2 提供了提取和分析的能力。

## 核心流程

入口 `pipeline/main.py::run`，一次调用等于一个协议的一次 run。模型链条是
flow model → world model → root model → scenario model。节点按顺序：

1. `load_document`：加载文档集（main 加 refs），纯代码。
2. `tag_sections`：LLM 标注每个章节，供后续引用。
3. `extract_principals`：提取语义参与方与运行前稳定值。
4. `extract_flow`：提取 flow model，即整条流程的形式化代码。
5. `extract_assumptions`：读出世界论域（`world` 段）与假设空间（fixed / variable）。
6. `extract_properties`：读出安全目标，用封闭的目标词表表达。
7. `extract_claims`：读出哪个目标在哪些场景下被声称，持有唯一那道跨产物关卡。
8. `build_world`：world model = flow + `world` 段，run 恰一次。
9. `build_root`：root model = world + 全部 fixed 假设，run 恰一次。
10. `scenarios`：按可变场景展开，场景间并发，逐场景出结论。
11. `aggregate`：三值合取合并出每条 property 的答案。
12. `cross_check`：跨场景检验，得到最终结果。
13. `reproduce_attacks`：把 false 格背后的攻击重跑成逐步脚本，供控制台播放和讲解；
    有 GT 时只取与 GT 一致的格，超过上限的格留给用户手动触发。检查失败后照样运行。

这份清单唯一的真相在 `orrery/pipeline/table.py`。每个节点的产物、检查规则、边界
条件和设计理由,写在该节点自己的 docstring 里（`orrery/nodes/<节点>/node.py`）
——**改某个节点前先读它**。

### 三条贯穿设计

- **产出者自治**：每份产物归一个节点，由它决定"用户给了就用、没给就抽"。不为"读取
  用户文件"单开节点——只搬运不校验的中转站没人把关，正是当年 skeleton.json 被拆掉的
  原因。flow model 的传入就是这么加的：分支在 `extract_flow` 和 `extract_principals`
  各自里面，没有 `read_model`。
- **供入即钉死**：产物是给进来的节点，重跑写回同样的字节，所以它不是任何"回去重做"
  的目的地。唯一真相源是 `nodes/base.py::pinned_nodes`，四个地方读它：节点自己让路、
  `report_gap` 的合法目标里剔掉它（`RunEnv.upstream`）、控制台把格子画灰、
  `/api/runs/{name}/rerun` 拒绝重入。四份各写一遍就会在加第六种供入的那天散架。
  连带一条：五个 document reader 全被供入时，没人再读语料，`tag_sections` 整个跳过
  ——**只给母本不算**，那时 assumptions 和 properties 还要读文档，大协议少了 tags
  就只能看见目录。
- **四个 document reader**（`tag_sections`、`extract_principals`、
  `extract_assumptions`、`extract_properties`）挂同一份 `READER_TOOLS`、渲染同一份
  语料块，所以语料在前缀缓存里只写一次读三次。缓存是 tools → system → messages 的
  纯前缀匹配，工具数组差一个字节就赔掉整段语料，所以契约测试按上线字节比对这四个
  节点（`tests/contracts/test_tool_lists.py`）。`extract_flow`（要原语目录与按需身份
  建模库）和
  `extract_claims`（要 report_gap）各有自己的工具，自愿退出这个组。
  词表一律内联进提示词而不是给查询工具，就是为了不破坏这个组。
- **依赖是声明的**：`Node.depends_on` 说这一步等谁，经 `/api/meta/vocabulary` 交给
  前端画图。节点表是一条直线，真实形状是 DAG——assumptions 和 properties 并行，
  `extract_claims` 汇合三者。前端不自己维护第二份表。

## 对象级假设词表（五轴）与世界假设

词表 = realizer 类声明（`nodes/apply/realizers/<axis>/<subtype>/`），五根轴，每轴问
一个对象上的中性事实问题，档位弱→强，每轴一个 noop 档为流态默认：

- **data**（值，`of`）：攻击者是否/何时拿到该值。
  chosen < disclosed < 三个受限泄露档 < none < assumed_secure。
- **key_reuse**（值，`of`）：该密钥协议外第二用途给攻击者什么。
  oracle < observed < separated。与 data 能共存，所以是两根轴而不是一根：
  data 管持有，key_reuse 管使用。
- **channel**（链路，`link`）：public < {authentic ∥ confidential}
  < secure_nonbinding < secure。
- **admission**（身份准入域，`scope`）：攻击者能否在该 scope 取得自己的合法参与
  信息。open < closed。
- **primitive**（密码族，`family`）：broken < weak_member < ideal。

**一个对象一个答案**：子类型是关于同一个对象实例的互斥答案，实例由 `instance_key`
指名。同一 (轴, 实例) 只准有一条声明——`validate_assumptions` 在声明层拒绝，claims
关卡 `reject_double_answers` 在每个场景的 fixed ∪ conditions 上再拒一次。

**世界假设另算**：role_binding / population / session_multiplicity 三根轴在
`assumptions.json` 的 `world` 段（词表是 `nodes/world/builders/` 的类声明），由
build_world 恰一次施加，永不出现在场景条件里。判据是层级：对象级假设是既定世界中
对象上的谓词（一个值、一条链路、一个身份 scope、一个密码族），世界假设约束整个分析
世界（有哪些东西、谁能演什么角色、跑几轮）。

各档完整语义、寿命约束、admission 的 sighted apply 规则见
`.agents/skills/experiments/references/vocab.md`。

## 分层架构

`orrery/` 由下往上共十一层，上层可以用下层，反过来不行：
- `kb/`：原语素材库等纯数据（假设与目标的词表已改为代码里的类声明）。
- `infra/`：外部封装，LLM 客户端与 ProVerif 二进制。
- `services/`：与领域无关的地基，事件、留痕、原子落盘与版本化、并发。
- `modules/`：领域能力，文档集、pv 文本读写、词表 accessor、LIB schema、
  verdict 切分。
- `checks/`：检查层，检查注册表、逐节点规则、独立复核。
- `agent/`：agent 循环与工具层，零领域判断。
- `nodes/`：各个节点，外加 realizers（施加假设）与 injectors（注入目标），
  提示词也在这里。
- `pipeline/`：编排，节点表、场景并发、断点重入、gap 回退、修正执行。
- `expert/`：面向用户的长会话问答与修正计划。
- `api/` ：面向前端的读写接口，Host、词表渲染、配置读写、run 目录、语料输入解析。
- `web/`：web 控制台，FastAPI + 静态页，只依赖 api。
- `utils/`：只有命令行够得着的开发者工具，引擎内部无人 import。一个：
  `utils/prompts`（`orrery prompt`）调用各节点自己的 `build_prompt`，渲染出的就是
  run 真正发出去的字节，所以不会漂。

## 两个版本号

都写在 `orrery/version.py`，都是人工更新，互不牵连。

- **项目版本号** `PROJECT_VERSION`（现 2.0.0）：软件版本，和 `pyproject.toml`
  保持一致。代码、realizer、提示词的迭代算它。
- **词表版本号** `VOCAB_VERSION`（现 2.0.0）：显式改了词表设计就手动升。LIB 每份
  JSON 带 `vocab_version`，装载时只比相等，不等就响亮报错——升了它，
  VerdictBench 全部 json 随即失效，直到把各文件的版本号也显式改过来。
  档位：轴内改动 = 小版本，增删轴 = 中版本，词表重构 = 大版本。

## ground truth lib 库

LIB 库（VerdictBench）是所有协议的源文档、标准形式化代码，以及安全目标和假设的
ground truth。**本机路径见 `CLAUDE.local.md`。**

## 大小协议认知口径

LIB 库里的协议分两类，别名表把每个别名映射到 `(协议目录, 显示名, 版本/变体)`：

- **小协议**（`academic/` 下）：经典学术协议，如 NSPK、NSSK、Denning-Sacco、
  Neuman-Stubblebine、Otway-Rees、wide-mouth-frog、Yahalom、Kao-Chow。一个协议
  对应一份文档、一份 ground truth，没有版本分支。
- **大协议**（`rfc/` 下）：工业级标准协议，如 EDHOC、IKEv2、TLS13、OAuth-2.0、
  EAP-AKA-prime、Kerberos-V5、PKINIT、QUIC、SSHv2。同一协议常有多个
  版本/draft 变体（例如 TLS13 的 draft18/draft20/draft21/8446，OAuth-2.0 的
  draft22/6749）。短别名（如 `EDHOC`、`TLS13`）指向该协议的默认/常用版本；
  带完整路径的别名（如 `rfc/TLS13/8446`、`rfc/OAuth-2.0/6749`）指向具体版本，
  互不共享 ground truth。

## 本地运行

**正式实验一律在远程服务器上跑，见 skill `experiments`。**本地 `a_runs` 只是开发
调试，结果不作为任何指标。

下面 `$PY` 是本机 Python、`$LIB` 是 VerdictBench 路径，两者都在 `CLAUDE.local.md`。

命令行是 `orrery/main.py`（click 命令组），**唯一入口是装好包之后的 `orrery`**
（`pip install -e .`）。不带子命令直接起 web 控制台；`--config` 放在子命令前后都认。
协议名是 `--name`，run 目录名是 `--run-name`。

```bash
# 完整跑一个协议
orrery --config config.yaml run --name NSPK --dir $LIB/academic/NSPK

# 跑到 flow 就停（--to-node 跑完该节点即结束；新 run 由程序自动分配名字）
orrery run --name NSPK --dir $LIB/academic/NSPK --to-node extract_flow

# 从 flow 开跑（在原 run 里就地重入，--from-node 指定的节点自身也重跑，
# 它和它之后的旧产物先密封进各自目录的槽位带）
orrery run --name NSPK --dir $LIB/academic/NSPK --run-name NSPK01 --from-node extract_flow

# 保留原 run、另开一个新 run 接着跑（--fork-from 把上游产物拷过来）
orrery run --name NSPK --dir $LIB/academic/NSPK --fork-from NSPK01 --from-node extract_claims

# 词表（--yaml 出 YAML，--out x.html 出网页）与生效配置（key 脱敏）
orrery kb
orrery config

# 控制台（不带子命令）。没填 key 也能开：默认就是 recorded 回放模式
orrery --port 8000
```

跑批是另一条链路、另一份配置，见 skill `experiments`：三个命令一个参数，
`python -m experiments.batch {run,status,stop} {main,claims,baseline}`，
配置在 `experiments/config.yaml`（和根目录那份互不相干）。

## 按需读取的文件

规程和参考资料放在 `.agents/skills/`，**两个 agent 都自动加载**：codex 从当前目录
一路向上扫到仓库根的 `.agents/skills/`，Claude Code 扫 `.claude/skills/`，后者每一项
都是软链指向前者，所以永远是同一份。**加新 skill 时记得补一条软链。**
`CLAUDE.md` 同样软链到本文。

自动触发不了时，照下面的路径直接读：

- 正式实验：远程启动、命名口径、批次管理、读结果与追根因
  → `.agents/skills/experiments/SKILL.md`（远端环境、词表、协议的坑、baseline
  都在它的 `references/` 下）
- 控制台前端（选型、状态模型、布局视觉、白屏排查）
  → `.agents/skills/web-console/SKILL.md`
- 写／改流水线提示词
  → `.agents/skills/prompts-writing/SKILL.md`
- LLM 接口层、中转网关实测、结果侧验证
  → `orrery/infra/llm/README.md`
- 代码欠账与未裁的设计问题
  → `TODO.md`
- 本机路径与实验环境
  → `CLAUDE.local.md`（不入库；codex 用户把它写进 `~/.codex/AGENTS.md`）

## 协作约定

- 始终用中文回答。
- 用户喜欢简短的提示词、干净的工程设计，最终以提取效果和实验指标为准。
- **不要自己改 AGENTS.md。**用户没有明确要求时，不主动增删这份文件——包括"顺手补一
  句"、"把刚学到的写进去"。发现该记的东西，写进对应的 skill、节点 docstring 或
  `TODO.md`，或者先问。
- 协议级的坑写进 `.agents/skills/experiments/references/protocols.md`，
  按协议分节，过时的直接删。
- 无用户授权不要更新本 md 文件。

## 对话风格

1. 先给一句清晰简洁的结论，让人一下明白当前情况。
2. 解释用平实的句子，少用复杂句式和项目内部术语，用词简洁明确。
3. 讲协议建模问题时优先给 ProVerif 示例代码对比（标准写法与生成写法），在注释里
   解释差异。

## 代码编写铁律
1. 显式报错原则：任何违反预期的输入，都显式报错，出现异常的点位，均直接报错，不要静默吞错误；
2. 不需向前兼容：在建立新架构、新代码时，不要为了旧代码、旧产物做任何向前适配，以架构完整性为主，除非用户显式指定。
