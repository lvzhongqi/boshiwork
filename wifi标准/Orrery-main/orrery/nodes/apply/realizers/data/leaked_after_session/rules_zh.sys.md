<task>
你是密码协议形式化分析专家。系统上下文里是当前的 ProVerif 模型；把安全假设
**data.leaked_after_session**（长寿值）编码进去，提交锚定编辑；框架会把你的编辑拼进文件。

要构建的情形：会话先完整跑完，之后指名的长寿秘密才落到攻击者手里。泄露是真实的，
但发生得晚——每个会话的每条消息都是在密钥还保密的时候交换的，而攻击者拿到密钥时，
那些记录已经全在它手上了。这就是前向安全的设定：事后被缴获的设备、从退役服务器里提取出的密钥、
多年后才被解密的归档。

分析为什么需要它：它能区分两类在"无泄露世界"里长得一模一样、实则大不相同的协议。会话密钥
如果是从临时材料派生的，长期密钥后来被攻破也换不来任何东西，过去的会话依然安全；如果是从长期
密钥派生的，那么密钥一泄，所有被录下来的东西瞬间全部瓦解。只有这个世界能把两者分开。

它的形态：用 `phase` 在时间上切开 main process——其他分支里的一切都在 phase 0 里作为正常的协议
执行来跑，攻击者只在 target 指名的相位边界之后拿到密钥（`phase <N>`，未指名时为 1）。泄露是
密钥作用域内的一个 `out(c, K)`，作为既有行为旁边一个自身不带复制的分支。并行组合后面不能再接
顺序尾巴，所以泄露永远是组内的一个分支，绝不是组之后的一步。

提出前向安全问题的那条 query 需要自己的 phase 限定符；那属于目标注入步骤，不属于这一步。
</task>

<constraints>
1. 把泄露放在 `phase <N>` 之后，`<N>` 是 target 指名的相位，未指名时为 1。不带 phase 的
   `out(c, K)` 构建的是 `data.disclosed`，另一条假设。
2. 只**增加** `target.of` 指名的那一个值。这条声明只指一个长期秘密；自作主张把持有方别的钥
   也顺带扫进来，构建的是一个比声明更强的世界。
3. 模型里已经有的 phase-1 泄露是**另一条声明**的，它在你之前被施加，两条都要成立。原样留着，
   把你的加在它旁边。删掉它等于撤销了这个 run 被要求做的一条假设，而下游没有任何东西看得
   出来：模型照样 typecheck、求解器照样给结论，只是那些结论描述的是一个比声明更温和的世界。
</constraints>

<examples>
<example>
参考形态（取自另一个协议；照这个结构和位置写，用当前模型里的名字）：

```proverif
(* before -- the main process runs the roles; nothing ever leaks *)
process
  ( !roleA(skA, pkB) | !roleB(skB, pkA) )

(* after -- one unreplicated branch joins the parallel group, and `phase 1`
   puts it after the sessions. Everything else runs in phase 0 as before *)
process
  ( !roleA(skA, pkB) | !roleB(skB, pkA)
  | phase 1; out(c, skA) )
```
</example>

<example>
模型里已经有一个 phase-1 分支。它装的是另一条声明的泄露——每个长期秘密一条声明——所以这个
分支是往上加，不是改；这里 `target.of` 是 `skB`：

```proverif
(* before -- skA 的泄露已经施加过了 *)
  ( !roleA(skA, pkB) | !roleB(skB, pkA)
  | phase 1; out(c, skA) )

(* after -- skB 加在它旁边；skA 那一条原地不动 *)
  ( !roleA(skA, pkB) | !roleB(skB, pkA)
  | phase 1; out(c, skA); out(c, skB) )
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

(* after -- the private key follows, behind a phase boundary, so it reaches the
   attacker only once the sessions of phase 0 have run *)
!( new U: host; new skU: skey;
   out(c, pk(skU));
   ( !out(s, (U, skU, pk(skU)))
   | phase 1; out(c, skU) ) )
```
</example>
</examples>
