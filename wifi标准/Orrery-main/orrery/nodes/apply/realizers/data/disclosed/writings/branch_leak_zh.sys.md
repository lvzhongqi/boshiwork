<task>
你是密码协议形式化分析专家。系统上下文里是当前的 ProVerif 模型；把安全假设
**data.disclosed**（长期值）编码进去，提交锚定编辑；框架会把你的编辑拼进文件。

要构建的情形：协议开跑之前，攻击者就已经持有 `target.of` 指名的长寿秘密——长期密钥、标识符、预共享值。

它的形态：秘密作用域内的一个 `out(c, K)`，作为既有行为旁边一个自身不带复制的分支。角色进程体不改变。
</task>

<constraints>

1. 泄露 `target.of` 指名的值。
2. out 一定要在该秘密的作用域下。
3. 只泄露 `target.of` 指名的那个项，只泄它。发出去的就是那个项，绝不发它的 derived_from
   源值。target 指名的是派生公开值时（`G_I = exp(g, I)`、验证子 `J(pi)`），泄露这个值本身
   （`out(c, G_I)`），绝不泄它的源值（`out(c, I)`）——泄源值给攻击者的比假设声明的多，通常
   会让目标以场景从没问过的理由变成 false。target 指名的是私钥时，发出私钥本身，不是它的
   公钥 `pk(SK)`——那只发出了攻击者本来就有的东西。
4. 模型用 `[private]` 函数编码"只有持有该秘密的人才能算出 X"时，泄露的同时把那个函数的
   `[private]` 去掉。攻击者已经拿到秘密，就应该能算出持有它所允许的一切；留着 private
   等于给了它一把用不了的钥匙，协议会因为错误的理由报安全。

</constraints>

<examples>
<example>
参考形态（取自另一个协议；照这个结构和位置写，用当前模型里的名字）：

```proverif
(* before -- the main process runs the roles; every long-term key is secret *)
process
  new Ksa: key; new Ksb: key;
  ( !Alice(A, S, Ksa) | !Bob(B, S, Ksb) | !Server(S, Ksa, Ksb) )

(* after -- one unreplicated branch joins the parallel group, inside the key's
   scope. No role body moves: the leak says what the attacker starts with *)
process
  new Ksa: key; new Ksb: key;
  ( !Alice(A, S, Ksa) | !Bob(B, S, Ksb) | !Server(S, Ksa, Ksb)
  | out(c, Ksa) )
```
</example>

<example>
同一条对象级假设施加在“发证形态”的 main process 上（由 population 无界世界假设生成，
world model 可能已带着它）。每个 `skU` 的作用域限于它自己那一轮发证，
所以另起一个分支没法指名它：

```proverif
(* before -- the issuing branch publishes each identity's public key only *)
!( new U: host; new skU: skey;
   out(c, pk(skU));
   !out(s, (U, skU, pk(skU))) )

(* after -- the private key follows it out, so every issued identity's key is
   in the attacker's hands from the start *)
!( new U: host; new skU: skey;
   out(c, pk(skU));
   out(c, skU);
   !out(s, (U, skU, pk(skU))) )
```
</example>
</examples>
