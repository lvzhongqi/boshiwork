# 远程实验服务器

> 路径占位符（`$SRV`、`$EXP_MAIN`、`$RSRC`、`$RLIB`、`$SRC`、`$LIB` 等）在
> `CLAUDE.local.md` 里定义——本机配置，不入库。

大批量实验统一在高性能服务器 `$SRV` 上执行。远端目录固定为：

- Orrery：`$RSRC`
- VerdictBench：`$RLIB`
- 实验产物根目录：`$EXP`
- 主线实验：`$EXP_MAIN`
- claims 提取实验：`$EXP_CLAIMS`
- baseline 实验：`$EXP_BASELINE`

## 唯一真相与同步规则

- **正式实验必须在远程服务器运行，并直接写入指定实验目录。**凡是用于回归、指标、
  对比或论文数据的运行，都必须把 `paths.work_root` 设为
  `$EXP/{baseline,main,claims}` 中对应的一项；主线实验
  固定写入 `$EXP_MAIN`。本地 `a_runs` 只允许临时调试，
  其中的结果不能作为正式实验指标。若误在本地生成正式 run，必须按远端现有编号连续
  追加迁移到对应目录，并以远端副本为准。
- **源码和 VerdictBench 只允许在本地修改。**服务器是执行端，不在远端直接改代码或
  ground truth；需要变更时先改本地，再重新同步。
- 同步方向永远是本地 → 服务器，禁止反向 rsync。同步代码不得包含服务器实验产物。
- 实验输出只能写入 `$EXP/{baseline,main,claims}`，
  不能写进远端 Orrery 或 VerdictBench，从而避免后续同步覆盖或删除产物。
- 默认同步不加 `--delete`。确需清理远端陈旧源码时，必须先用 `--dry-run --delete`
  检查目标，并明确排除配置、凭据和实验目录；绝不能对 experiments 使用 `--delete`。
- 密码和 API key 不写入 `AGENTS.md`、脚本或版本库。交互登录可临时输入
  密码，长期运行应使用 SSH key。

标准同步命令（从本地执行）：

```bash
rsync -az --exclude '.git/' --exclude '__pycache__/' --exclude '*.pyc' \
  $SRC/ \
  $SRV:$RSRC/

rsync -az --exclude '.git/' --exclude '__pycache__/' --exclude '*.pyc' \
  $LIB/ \
  $SRV:$RLIB/
```

## 远端环境

远端唯一 Python 运行环境名为 `orrery`。ProVerif 直接用 OPAM 安装当前最新版本，不在
项目内下载源码或手工构建。首次安装执行：

```bash
ssh $SRV
sudo apt-get update
sudo apt-get install -y opam
opam init -y
opam install proverif -y
sudo ln -sfn $ROPAM/proverif /usr/local/bin/proverif
conda create -n orrery python=3.12 -y
conda run -n orrery python -m pip install -e $RSRC
conda run -n orrery orrery --help
proverif --help 2>&1 | head -n 1
```

`/usr/local/bin` 是所有普通登录用户的默认 PATH；系统级链接使任何用户登录后都能直接
运行 `proverif`，同时链接仍跟随 xiaonan 的 OPAM 安装更新。

远端运行配置必须满足：

```yaml
prompt_lang: en
paths:
  work_root: $EXP_MAIN
  lib_root: $RLIB
proverif:
  executable: /usr/local/bin/proverif
```

## batch 与实验目录

`experiments/` 下四样东西，各答一个问题：`batch/` 是通用跑批能力（一批协议、一个并发度、跑起来），不并入 Orrery 引擎，也不
认识任何一个实验；`batches.py` 是三个实验各自的设置（代码里的 dict）和各自由谁跑；
`protocols.yaml` 是协议目录和选择列表；`oneshot/` 是 baseline 的实现。三个 batch
共用一个入口 `python -m experiments.batch`，用名字指定，不是目录路径。

**配置只有一份，而且不是根目录那份**：`$RSRC/experiments/config.yaml`（不入库，
第一次跑批时自动从 `experiments/config.example.yaml` 拷出来）。它只准放四样：
`llm`、`proverif`、`paths`、`max_runs_concurrency`——多写一个键直接报错，因为实验
含义写在 `batches.py` 里，任何配置文件都不该能改它。根目录的 `config.yaml` 管
单跑和控制台，两份互不读取：子进程拿到的是 `--config experiments/config.yaml`，
`--config` 是整层替换，所以根 config 根本不会被打开。

**要确认它的 `paths.work_root` 指向实验根**（`/home/xiaonan/lab/orrery/experiments`）：
batch 名会被追加上去。每条命令启动时打印两行——`batch X: runs -> …` 和实际
生效的模型（和论文的 `gpt-5.6-sol` 不一致时当场说出来），对不上就是配置没设对。

启动前的完整性检查在拉起第一个子进程之前做（`preflight`）：key 没填就报一次，
不会 104 个子进程各报一遍；ProVerif 跑不起来、`paths.lib_root` 或 `protocols.yaml`
里的目录不存在，也在这一步拒绝启动。`status` / `stop` 不需要凭据，照常能答。

`protocols.yaml` 是完整协议定义和 `selected_protocols` 选择列表的唯一真相；
main / claims / baseline 读取同一份选择，batch 不按母本是否存在静默过滤协议。
只跑其中一个协议在命令行上加协议名（`run main NSPK`）；要改整批就改这份选择列表，
不要为此另开一份抄本——抄本一定会过期。

## 批次管理命令

以下命令必须在 `$RSRC` 下执行。**一共四个，各带一个 batch 名**：

```bash
python -m experiments.batch run    main         # 启动（加协议 id 只跑那一个）
python -m experiments.batch status main         # 每个协议的状态和 run 名
python -m experiments.batch stop   main         # 给整批发干净中断：先停调度器，再扫无主的子进程
python -m experiments.batch resume main NSPK --from-node extract_flow   # 在批次设置下原地接续
```

claims 和 baseline 只是把最后那个名字换掉，命令一模一样——哪个 batch 由哪个
runner 跑写在 `experiments/batches.py::RUNNERS` 里，不用记。

`run` 是启动一批，不是修一批：**只要有协议手里攥着一个没跑完的 run，它就停下来报错，
一个子进程都不起**，并把那些协议列出来。接续用 `resume <batch> <protocol>
--from-node <node>`，它在批次自己的实验设置下原地重入（`status` 给 run 名，被中断的
run 自己也把节点名打进了日志）；Orrery 自己的 `--run-name` / `--from-node` 拿不到
这些设置，别用。不想接续就把那个 run 目录删掉，再 `run` 就会重新起。判据是**磁盘上
的 run 目录**，不是 `_batch/` 里的状态文件——产物才是实验事实。

单个协议的日志直接看 `_batch/logs/<协议>.<次数>.log`，或者那个 run 自己的 `run.log`。

状态文件和 batch 日志位于对应实验目录的 `_batch/`，例如 main 在
`$EXP_MAIN/_batch/`；不要手工修改这些状态文件。
