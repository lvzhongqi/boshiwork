<task>
在 target 指名的有向链路上编码 **channel.authentic**。

要构建的世界：接收方从这条链路接受的每条消息，都是具名发送方在这条链路上发出的——来源和
内容都是确定的。攻击者读得到链路上经过的一切，却放不上任何东西；伪造和重放都在这个世界之外。

它的形态：链路的信道声明变为 private，链路上的每次发送后跟一份 `c` 上的公开副本。
发送方和接收方继续使用原有信道名。
</task>

<constraints>
1. 把目标信道声明改为 private。
2. 在每个 `out(<link>, m)` 后加入 `out(c, m)`。
3. 修改作用于 target 指名的方向；反方向保持它自己的假设。
</constraints>

<example>
参考形态（取自另一个协议；照这个结构和位置写，用当前模型里的名字）：

```proverif
(* before -- the link is an ordinary public channel, and the sender just sends *)
free channel_A_B: channel.

let processA(A: host, B: host, SKA: skey, PKA: pkey, PKB: pkey) =
  new I_A: bitstring;
  out(channel_A_B, aenc((I_A, A), PKB));
  ...

(* after -- the channel is private, so the attacker cannot write to it, and a
   public copy follows every send on the link, so the attacker still reads it *)
free channel_A_B: channel [private].

let processA(A: host, B: host, SKA: skey, PKA: pkey, PKB: pkey) =
  new I_A: bitstring;
  out(channel_A_B, aenc((I_A, A), PKB));
  out(c, aenc((I_A, A), PKB));
  ...

(* the receiver is untouched: it goes on reading the same channel name *)
let processB(B: host, A: host, SKB: skey, PKB: pkey, PKA: pkey) =
  in(channel_A_B, msg1: bitstring);
  ...
```
</example>
