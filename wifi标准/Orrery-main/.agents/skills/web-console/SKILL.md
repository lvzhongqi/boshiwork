---
name: web-console
description: Orrery 控制台前端（orrery/web/）：选型硬约束、状态模型、布局与视觉规矩、后端配套。改控制台、加面板、调样式、排查白屏时使用。
---

# web/ — 控制台前端

无构建、无框架脚手架。Vue 3 ESM + 一个 `App` 模板字符串 + 手写 CSS,浏览器直接跑
`static/js/*.js`。改完刷新即生效。

```
server.py       FastAPI:REST + SSE
static/js/
  stream.js     SSE 订阅 + 所有 fetch
  store.js      账本 → 页面状态(fold),纯函数,不碰 DOM
  main.js       setup + 整个模板(一个模板字符串)
  replay.js     攻击复现的播放器组件(读 msc.json 自己画 SVG;定义框随行高排布)
  i18n.js       中英两份词典,必须成对
  app.css       全部样式
```

起法(不带 `--config` 就用项目根的 `config.yaml`):

```bash
orrery --port 8733
```

配置没填完也能起——读一个 run 不需要模型和 solver,那是**提问**才需要的
(`server.py::_configured_work_root`)。只监听 `127.0.0.1`,不做鉴权。

---

改这个模块之前读完本文。踩坑排查(白屏、改了不生效、i18n 对不上)见
[references/troubleshooting.md](references/troubleshooting.md)。

---

## 选型的硬约束(别推翻)

**同进程、同一个 event loop 持有所有 run。**`infra/gates` 的并发闸是 per-loop 的
信号量单例(`_GATES` 的键含 `id(asyncio.get_running_loop())`),一个 run 一个进程会让
`max_concurrency` 直接失效。这条排除了 Flask / Django 的同步模型,也排除了
Streamlit / Gradio——它们自己掌管执行模型,而 `confirm` 要求停下来等人回答。

**事件走 SSE,命令走 POST。**没有一处需要双向长连。SSE 自带重连并携带
`Last-Event-ID`,而信封里已经有 `seq`,直接拿来当 SSE 的 `id:`,重连就是补 `seq > N`。

**不引 React/TS。**这个前端的难点全是时序与状态(`seq` 幂等、重连补历史、滚动粘底、
事件洪水下的内存),类型检查一条都防不住;而构建产物进 git 是一坨压缩 diff,忘记重新
构建则是静默失败。穷尽性用运行时检查换:后端权威清单 `KNOWN`
(`services/events/__init__.py`)经 `GET /api/meta/event-types` 吐出,前端启动时拿自己的
`HANDLED` 比一遍,缺哪个就在页面上挂横幅。

## 状态的四条规矩

1. **状态 = 事件流的一次折叠,只有这一条路。**没有 snapshot 端点:首连从 `seq=0`
   回放整本账本,重连从 `Last-Event-ID` 续,三种情况走同一个 `applyEvent`,第一行就是
   幂等判断 `if (ev.seq <= state.lastSeq) return`。未知类型不崩也不装瞎:原样进 feed,
   由启动时对 `KNOWN` 的比对负责报警。
2. **命令不乐观更新。**点"中断"不改本地状态,只等事件回来。界面显示的永远是后端真的
   发生了什么。唯一例外是 expert 里用户自己那条消息。
3. **大文本不进 state。**thinking 全文、pv 全文、ProVerif 输出只在打开时 fetch,关掉
   就丢。state 必须有界。
4. **流式片段是第二条、临时的输入,不参与折叠。**`ModelDelta` 追加进
   `state.drafts[unitKey]` 草稿区（`state.live` 是 /tree 给的阶段索引，两者不能同名），durable 事件一到就覆盖。**片段还可能整条链路都没有**:
   openai_compatible 后端收下 `on_delta` 但 `stream=False`,走 bltcy 那类通道一个片段
   都不会来——**界面上任何进度语义都不许依赖片段**。

列表 key 用稳定标识(场景名 / 单元路径 / 轮号)而不是下标。排序只信 `seq`:`ts` 是
`timespec="seconds"` 的本地时间,同秒多条很常见且没有时区。

## 布局

**Expert 栏默认收起。**运行页两列,右边那列折成边上一条竖条(`.cols.folded`),
点开才占宽度。读者来看的是这次 run 的面板,提问是少数时候的事。开合状态存在
`localStorage`(`orrery.expert`),读写都包了 try/catch——隐私窗口里会抛,取不到就按默认
(收起)走。

**能无限长的东西,必须放在滚动容器里面。**会话时间线、事件流没有上限。放在
`.main-col`(唯一的滚动列)外面,它就把 flex 行的高度吃光:页面不动、旁边的 Expert
栏被挤没。

**上限只限制"画多少",不限制"存多少"。**事件流曾经在 store 里砍到 500 条,后面的
到达即丢弃——一个记了 598 条事件的 run,第一行显示的是第 99 条,而且什么也不说。
现在 store 全留(`store.js`),窗口开在 view(`main.js::FEED_WINDOW`,默认 300),
并且**明说没画的那些**("上面还有 N 条 —— 点开")。静默截断是 bug。

**grid 用 `auto-fit` 不是 `auto-fill`。**`auto-fill` 会保留空轨道——11 个格子排进
13 条轨道,右边空两格顶不到头。

**`minmax(0, auto)` 和 `auto` 不一样。**`auto` 不会低于自己的 min-content,所以一段
长文本能把旁边的列挤到 0 宽,短标签就被 `overflow-wrap: anywhere` 拆成一字一行。
谁必须可读,谁就要有 `minmax(<下限>, 1fr)`。

**非弹性轨道按内容定宽,最大值只是上限。**`minmax(0, 30rem)` 内容不够就停在内容宽度,
留半列空白;要它真占满写死 `30rem`。

**同一个 class 名不要给两种东西用。**顶栏返回箭头和时间线的"回退"标记都叫 `.back`,
两条规则里只有一条设了 `cursor: help`,返回箭头就变成了问号。**该显式写的属性要写**:
它之前"正常"只是因为没人跟它抢。

## 视觉

**三条阶梯管住一切,不在阶梯上的值就是 bug。**字号 11 / 12.5 / 13.5 / 14.5 / 16 /
20 px(`--t-xs` … `--t-xl`,用 px 是为了不随嵌套漂);间距 4 / 8 / 12 / 16 / 22 / 30 px
(`--s-1` … `--s-6`);圆角 5 / 8 / 12;深度四层地面 `--bg` → `--panel` → `--raised`
→ `--hi`,不设第五层。

**字体自己带**(Inter + JetBrains Mono,vendored 进 `static/vendor/fonts/`):本地工具
没有理由联网,而静默回退会把整条阶梯废掉。**Pico 是加法,不是地基**——留着当 reset 和
表单控件,它的 130 个变量全部指向上面的阶梯;标签选择器特异度最低,随便一个类就赢;
整个不要就删掉那行 `<link>`,我们自己的样式一行都不用动。代价是标记即样式:写了
`<table>` 就一定是 Pico 表格,所以事件流那个长滚动列表不要用 `<table>`。锁版本,不
自动升级。

**用色四条:**

1. **主色和判定色分家。**`--v-ok` / `--v-warn` / `--v-bad` 说机器是否正常(完成 /
   未过 / 失败);判定 `false` 是答案不是故障,用不在红绿灯上的 `--v-neg`,已复现
   攻击的格子用它画一道左边线——底色留给「与语料是否一致」,那是更响的问题,
   实底既盖掉它,又比不一致的红更抢眼。这些都不许拿去当装饰;"可交互 /
   进行中"归 Pico 主色;攻击动画里的攻击者用自己的 `--atk`。用自己的前缀而不是
   覆盖 `--pico-*`。
2. **状态双编码:形状 + 颜色。**只靠颜色的看板在截图里、在色觉障碍下都会失效。
3. **等宽体是语义不是装饰。**机器认得的确切字符串一律等宽:节点名、单元路径、事件
   类型、API 路由、文件名;散文用 Inter。
4. **数字对齐用 `font-variant-numeric: tabular-nums`。**

**深色优先**,亮色一套也写全(`[data-theme="light"]`)。三种主题态都要写全——任何一个
色值只写在媒体查询里,未标记态就会拿亮色文字配暗色底。

## 信息设计

**错误原因是整行里最该被读的字,不能当附注。**曾经只画 `findings[0]`、挤在旁边那列被
截断、还是灰色,三重损失叠在一起,结果就是"知道失败了,不知道为什么"。要全部列出、
占满宽度换行、用阅读色。

**图标说"谁做的",不是"这是哪类行"。**一个会话里有三个演员轮流上场:

```
◎  Orrery 发的      提示词
✳  模型答的        回复
◈  模型调工具      submit
▣  Orrery 处理了   拼接 / 冻结 / 交给求解器
✓/✗ Orrery 的判定  —— 必须跟着结果变
●  ProVerif        求解器
```

颜色说谁,形状说做了什么。**固定图标会说谎**:检查没过时前面挂着绿勾,就是这么来的。

**"通过"不等于"没事发生"。**`goals_typecheck` 按规矩只判语法,超时也算过,绿勾会让人
以为验过了。这种情况要黄色 + 一句"过了,但超时,什么也没验证到"。

**长活儿要先说再做。**ProVerif 一跑就是几分钟。事件发在动作**之后**,账本就会静默整整
那么久,读的人分不清"在跑"和"死了"。所以:交给求解器之前发一行、每个 cell 开检查之前
发一行。同一条道理适用于任何 await 前面。

## 后端配套

**请求永远要回答。**没有超时上限的等待 = 按钮回不来 = 用户眼里的"卡死"。服务端给上限
并返回可读的 409,客户端也给一个稍长的 `AbortSignal.timeout`,再加一个兜底定时器清
状态。

**一个挂起的请求不该锁死整页。**`canRetry = !retrying` 这种写法会让一次卡住的请求藏掉
所有按钮。

**错误路径本身不能再错。**`new Error((await r.json()).detail)` 在非 JSON 响应上会二次
抛错,屏幕上出现的是解析器的抱怨(`Unexpected token 'I', "Internal S"`),既不说哪个
请求也不说什么毛病。先读 text,再试 JSON,**状态码永远进消息**。

**寻址逻辑只留一份。**重试的地址由后端 `steps.resolve` 解析,前端原样把画出来的那行
路径发回去(编号都不用剥)。前端再实现一遍,就多一份会走偏的规则。

## 地址与命名

- **场景阶段的目录没有序号**:`apply / scenario.pv / inject / solve` 四段。
- **`base` 不是场景的一个阶段**,它是 `build_root` 这一步,在场景开始前跑完。
- **`root` 不是场景。**`build_root` 的施加会话把 `ROOT_IDENT` 放在信封的 `scenario`
  字段(那个字段装的是会话身份),它没有 world 也没有 verdict。所有列场景的地方都走
  `scenarioLabels()` 过滤掉它,另给一个 Root model 面板。
- **证据链接是路径拼接。**`unit` 就是会话目录相对于所属步骤的路径(`apply/03_x`、
  `inject/Secrecy`),所以 `<步骤目录>/<unit>/<文件名>` 是精确地址。这比模糊匹配更要紧:
  封存改成原地改名之后,`03_z0_model.pv` 和现役的 `z0_model.pv` 躺在同一个目录里,
  任何按后缀匹配的规则都会两个都命中。
- **步骤目录号不写死。**序号是某一次 run 的事实(run 目录保留它跑时那张表的编号),
  所以 `stepDir(node)` 从 `/tree` 报的真实文件树里读前缀。

## i18n

默认英文,**一个字典两份语言**(`i18n.js`),不是两套模板——两套模板会在有人改其中
一套的当天就漂。每个 key **必须恰好出现两次**:

```bash
python3 - <<'PY'
import re, pathlib
from collections import Counter
s = pathlib.Path("orrery/web/static/js/i18n.js").read_text()
c = Counter(re.findall(r"^  ([A-Za-z_][A-Za-z0-9_]*):", s, re.M))
print(sorted(k for k, n in c.items() if n != 2) or "ok")
PY
```

由此多一条规矩,是状态四条的延伸:**状态里只放事实,不放说法。**泳道相位函数返回
`{at, kind, a, b}` 而不是句子,否则切语言时旧字符串留在状态里切不干净。着色规则两种
语言都要认(`未过` 和 `did not pass` 都标红)——账本是一条流,页面可能用任一语言读。

## 攻击面板

第 13 步的产物由 `GET /api/runs/{name}/attacks`(`api/attacks.py`)合成一份索引:
每个 false 格的决定(自动 / 待复现 / 跳过)和结果,以及总结。页面把它放在
`main.js` 的 ref 里,不进 state;账本上 `attack_status` 折叠成
`state.reproductions`,比索引新,两者由 `store.reproOf` 合成格子的样子。某格的
`msc.json` / `explanation.json` 只在它的播放器打开时读,关掉就丢。

步骤内有多个会话的节点(reproduce_attacks 每格一个讲解会话),事件的 `unit` 是
会话目录相对于步骤目录的路径,`store.unitDir` 按它拼地址;只有一个会话的节点
`unit` 就是节点名,地址是步骤目录本身。run 结束后应人要求产生的会话(`_attacks/`
下的手动复现与重新总结)不在步骤树里,`unit` 是相对 run 根目录的路径,以下划线
开头,`unitDir` 原样返回。

手动复现走 `POST /api/runs/{name}/attacks`、`/attacks/stop`、`/attacks/summary`:
请求立刻返回,格子的"排队中/复现中/已复现"只以事件为准,不做乐观更新;多选的
选择集只在页面上,不进账本。索引里的 `queue` 是队列里正在做和等着的格子,账本
上"在做"的状态只有在队列(或这一步本身)确实还在做时才算数,进程被杀后留下的
`running` 不会让格子一直转圈。

## 删干净

删掉一个面板,它的 CSS 规则、i18n 词条、store 里的导出函数一起删。留着描述不存在
东西的规则,下一个人会以为它还在用。
