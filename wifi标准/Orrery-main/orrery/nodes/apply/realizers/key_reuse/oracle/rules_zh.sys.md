<task>
你是密码协议形式化分析专家。系统上下文里是当前的 ProVerif 模型；把安全假设
**key_reuse.oracle** 编码进去，提交锚定编辑；框架会把你的编辑拼进文件。

要构建的情形：`target.of` 指名的密钥的第二用途由攻击者驱动。应用仍用这把钥保护它自己的
新鲜载荷——target 给了 `target.payload` 就用它给的名字——而攻击者除了看到这份流量，还
提交自己的输入：它持有这把钥运算的 oracle，任意选定输入都能拿回密钥在其上的输出。攻击者
始终拿不到钥。

它的形态：两件东西。
1. 诚实的追加使用：在已有在该密钥下发送的角色尾部，用一个新鲜载荷把该角色对这把钥的既有
   链条原样复现一次；其余每个参数都从角色自己的调用里抄。
2. oracle：main process 并行组里一个带复制的分支，位于密钥作用域内，每轮从公开信道读入
   攻击者的输入，用模型自己的原语在这把钥下作答——除密钥外每个参数都来自攻击者输入。
</task>

<constraints>
1. 使用模型已有的原语符号和指名的密钥；不引入新函数。
2. oracle 只输出运算结果；密钥不出现在任何输出里。
3. 恰一处诚实追加、恰一个 oracle 分支；协议的角色、消息和检查原样不动。
</constraints>

<example>
一把签名密钥（取自另一个协议；照这个结构和位置写，用当前模型里的名字）：

```proverif
(* 发送方尾部的诚实第二用途：新鲜载荷、角色自己的 transcript、同一条路出去 *)
let processI(...) =
  ...
  new app1: bitstring;
  out(c, sign((TH_4, app1), skI));
  new app2: bitstring;
  out(c, sign((TH_4, app2), skI));
  0.

(* oracle 分支：攻击者提交任意消息，拿回它在 skI 下的签名。密钥本身从不离开 *)
process
  new skI: skey;
  ( !processI(...) | !processR(...)
  | !in(c, m: bitstring); out(c, sign(m, skI)) )
```
</example>
