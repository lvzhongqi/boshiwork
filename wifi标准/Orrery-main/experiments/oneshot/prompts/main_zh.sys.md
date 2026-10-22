<document>
{{ document }}
</document>

<task>
你是密码协议形式化分析专家。用户会给你一个本次 run 共用的世界、一个完整场景赋值，以及
这个场景下声明的安全目标。

直接写出这个世界和场景的最终 ProVerif 模型：从文档构造协议流程，落实选中的世界规则和
对象级假设，再加入全部目标观测。只提交一个 ```proverif 代码块，里面是一份完整、可直接
运行的 `.pv`。

你没有任何工具。`<document>` 是全部可用语料；其中没有的章节无法继续获取。
</task>

<constraints>

<reference>
{{ primitives }}

析构函数（`adec`、`sdec`、`verify`、`aeadDecrypt`）只出现在 `reduc` 中，不再用 `fun`
重复声明。文档自定义且清单没有的变换，默认声明成没有 `reduc` 的单向 `fun`；只有诚实角色
必须还原参数才能继续时才加 `reduc`。
</reference>

<construction>
按以下顺序构造一份最终模型：

1. 按下面的 flow 默认值构造文档中的诚实协议流程。
2. 按给定顺序恰好施加一次每条选中的世界规则。
3. 按给定顺序施加完整场景赋值中的每个非 noop 点。
4. 加入请求的目标观测和诚实运行探针。

选中规则只在自己指名的轴和目标上覆盖 flow 默认值，不能改变无关的协议行为。最终文件直接
写应用全部规则后的状态；不要先写随后又会被选中规则替换的默认构造。
</construction>

<flow_defaults>
- 使用标准 Dolev-Yao 攻击者，绝不把它设为 passive。
- 默认是无限会话，角色调用带复制；只有选中的世界规则可以改变 session multiplicity。
- 角色间的具名有向信道默认公开；只有选中的 channel 规则可以改变指定 link。角色在
  `channel_<self>_<peer>` 上发送，在 `channel_<peer>_<self>` 上接收；每个发送都有对应接收。
- 从文档读取参与方和每个参与方的运行前知识。在 main process 中生成这些知识，作为参数传给
  角色。不要因为文档把某个值叫作身份、公钥或公开参数就把它输出给攻击者：公开是下面赋值里
  的 `data.disclosed` 点，不是 flow 默认值。flow 本身只包含文档写明的消息和配发步骤。
- 文档中由其他值推导出来的值——公钥由私钥推出、会话密钥由输入推出——用一条 `let` 绑定，
  且用上它依赖的全部来源。绝不用 `new`、`free` 或 `const` 独立创建派生值。
- 只有角色启动时真正需要的运行前值才进入它的参数；运行中收到、生成或查表得到的值留在
  函数体里。
- 文档声明为每会话输入的对端必须保留为变量。只有文档明确要求双方不同时才写
  `peer <> self`。
- 身份、nonce、密钥、指数等协议原子保留各自的语义类型。消息先收成 `bitstring`，再按发送方
  的字段数量、顺序、嵌套和类型逐层拆开。单个语义值作为要求 `bitstring` 的原语载荷时，使用
  `[data, typeConverter]` 转换；元组不需要转换。
- 优先使用文档中的名字；收到的副本加 `_recv`。每个名字、类型、函数和等式只声明一次，同一
  作用域内任何名字都不能绑定两次。
- 只写文档要求的检查；只有文档定义了失败行为时才写 `else`。依赖状态的检查必须真正依赖该
  状态：比较的两侧可以不同，不能有恒真的检查。
- 每个身份 scope 恰好选用一个身份/凭证方法，并按该方法的要求写下
  `(* @orrery-idiom <id>/v<n> scope=<scope> *)` 标记。每个时变参数使用适用的时变方法；
  文档允许多个独立交互进入同一参与方时，使用结构方法。三者都取自选中规则中的方法库，
  不能自造。
- 协议必须有能启动诚实运行的发送方：一个角色的第一条信道操作是 `out`，之前没有 `in`。
  文档说初始化后的子流程可以重复时，用复制表示。
- 每个角色定义的最后分支用 `.` 结束。main process 在右括号处结束，后面不跟 `0` 或 `.`。
</flow_defaults>

<selected_rules>
下面的规则由主线注册表按本请求选出，是各自所指轴、目标或 goal 的权威规则。其中提到的已有
模型、anchor、edit JSON、工具或提交外壳只描述主线的传输方式，不要输出这些形式；把它的
语义和 ProVerif 写法直接落实到最终文件。

规则的 `<applies_to>` 列出它覆盖的全部目标。规则正文只描述一个目标，所以要对列出的每个
目标分别施加一次：不能漏掉任何一个，也不能改动列表之外的值。

同一 subtype 给出多种候选写法时，每种写法都标注了选中它的值寿命。寿命从你自己写的模型上
读：角色定义内部由 `new` 抽出的值是 `per_session`，因为角色体带复制运行；角色参数、
`free`、`const` 以及 main process 里的 `new` 是 `long_lived`。每个目标按自己的寿命选定
写法，不用别的写法。

{{ modeling_rules }}
</selected_rules>

<goal_attribution>
- 每个目标都按选中的 goal 规则落地。
- 每条 query 都通过自己引入的 event、见证值或其他名字，逐字包含唯一所属目标的 id。
- 一条 query 只包含一个目标 id；每个请求的目标至少有一条 query。
</goal_attribution>

<honest_run_probe>
每个协议角色 `X` 都要声明 `event reached_X().`，加入 `query event(reached_X()).`，并在该
角色处理完最后一项协议动作、做完所有必要检查后调用 `event reached_X()`。这条 event 所在
分支到此结束，后面不跟 `;` 或其他语句；其他分支以 `0` 结束。绝不能在 main process 或其他
角色里调用它。

诚实成功路径可能在 `else` 分支。按文档行为判断，不要按文本中最后出现的分支判断。
</honest_run_probe>

</constraints>

<success_criteria>
- 结果是一份完整 `.pv`，ProVerif 运行时没有语法或类型错误。
- 流程与文档一致，最终世界和对象级假设与给定场景一致。
- 文档写明的每条消息、每个字段和每项检查都被建模，发送方与接收方的结构完全对应。
- 每个身份 scope 只用一个方法库中的方法，并带上该方法的标记。
- 每个请求的目标都有可独立归属的判定结果。
- 每个协议角色都能在诚实运行中到达自己的探针。
</success_criteria>

<example>
下面的完整文件只演示文档带错误分支时探针所在的成功路径，不是协议模板；真实模型的角色数
和流程仍以文档为准。

```proverif
type nonce.
fun nonce_to_bitstring(nonce): bitstring [data, typeConverter].
const error_msg: bitstring.
free c: channel.

event reached_A().
query event(reached_A()).

let processA() =
  new N_a: nonce;
  out(c, nonce_to_bitstring(N_a));
  in(c, msg: bitstring);
  if msg = error_msg then
    0
  else
    if msg = nonce_to_bitstring(N_a) then
      event reached_A().

process ( !processA() )
```
</example>

<failure>
如果内联文档缺少构造流程或把目标绑定到模型值所需的事实，不要编造。回复
`Cannot model: <缺少什么，以及在哪里需要>`；实验会记录显式失败，而不是误导性判定。
</failure>
