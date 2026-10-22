<task>
在 target 指名的有向链路上编码 **channel.confidential**。

要构建的世界：攻击者读不到这条链路上经过的任何内容，却可以把自己选定的内容放上去。
诚实方发送的东西保持隐藏；接收方接受的东西可以来自任何人。

它的形态：链路的信道声明变为 private，并在 main process 的并行组里加入一个带复制的转发器，
从公开信道读入、写到链路上。发送方和接收方继续使用原有信道名；攻击者在公开信道上组装的
任何内容经转发器进入链路。
</task>

<constraints>
1. 把目标链路声明为 `[private]`。
2. 在 main 并行组中加入转发器分支 `!in(c, x: bitstring); out(<link>, x)`。
3. 修改作用于 target 指名的方向；反方向保持它自己的假设。
</constraints>

<example>
参考形态（取自另一个协议；照这个结构和位置写，用当前模型里的名字）：

```proverif
(* before -- 链路是普通公开信道 *)
free channel_A_B: channel.

process
  ( !processA(...) | !processB(...) )

(* after -- private 声明藏起诚实方放上链路的一切；转发器是攻击者写入链路的通道。
   两端进程继续使用同一个信道名 *)
free channel_A_B: channel [private].

process
  ( !processA(...) | !processB(...)
  | !in(c, x: bitstring); out(channel_A_B, x) )
```
</example>
