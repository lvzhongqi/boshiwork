<task>
你是密码协议形式化分析专家。系统上下文里是当前的 ProVerif 模型；把世界假设
**session_multiplicity = single_session** 施加进去，提交锚定编辑；框架会把你的编辑拼进文件。

要构建的情形：世界里每个角色恰好运行一个会话。这是一次性设定——只发生一次的配对或
开通仪式——跨会话交错不在威胁模型内。流程模型写的是无界并发会话（会话组上一个 `!`）；
这条假设去掉那层复制。

它的形态：去掉 main process 里会话组前面的 `!`，让每个角色只跑一次。角色进程体不变——
变的只是 main process 启动它们多少次。
</task>

<constraints>
1. 只剥会话组的复制。每个 `new`、每个角色进程体、每条消息原样不动；这条假设只关乎跑
   多少个会话，别无其它。
2. 如果 main process 是发行形态（身份在私有信道上、由它自己的 `!` 发放），那层发行复制
   是 population 轴的，不是这一条——剥消费会话组的 `!`，绝不剥发行分支的。
3. 去掉复制，不是门控它。`phase` 或计数器都不能让世界变成单会话；只有去掉 `!` 才行。
</constraints>

<example>
参考形态（取自另一个协议；照这个结构和位置写，用当前模型里的名字）：

```proverif
(* before -- 无界并发会话 *)
process
  new K: key;
  !( initiator(A, B, K) | responder(B, A, K) )

(* after -- 每个角色一个会话；进程体不动 *)
process
  new K: key;
  ( initiator(A, B, K) | responder(B, A, K) )
```
</example>
