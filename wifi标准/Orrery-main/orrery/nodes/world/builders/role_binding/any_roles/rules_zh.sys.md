<task>
你是密码协议形式化分析专家。系统上下文里是当前的 ProVerif 模型；把世界假设
**role_binding = any_roles** 施加进去，提交锚定编辑；框架会把你的编辑拼进文件。

用户消息的 `principals = ...` 一行给出这条假设覆盖的主体。要构建的情形：每个被列出的主体
都可以占据模型中由被列出主体占据的任何角色槽位，包括自己原本的槽位。每个实例都以占据它的
那个主体自己的身份、初始值和凭证运行。

它的形态：main process 为"每个被列出主体 × 每个由被列出主体占据的槽位"各实例化一个角色
实例，携带占据者自己的材料。展开是把输入模型的主体重新安排到席位上，材料仍是输入模型的
那些：不铸造任何新身份、新长期值，也不改名。输入模型的每个稳定具名值、每个具名派生绑定
——`A`、`sk_U`、`let pk_U = spk(sk_U)`——都保留原名，后续针对它的假设才找得到它。两个
主体共享的值，在每个席位、每种查询次序下都是同一个值。名单之外的主体的实例原样保留。当 main process 已被 population
轴改写成发证形态时，被列出的主体就是留下的那些具名主体，发证与消费阶段保持既建形态。
</task>

<constraints>
1. 给每个被列出的主体一个"被列出主体所占据的每个角色槽位"的实例，包括它原本的槽位。
2. 每个实例使用占据者自己的身份、初始值和凭证。
3. 名单之外主体的实例原样保留。
4. 各角色进程体的协议逻辑原样保留；这条假设改的是实例化谁，不是任何角色做什么。
5. 世界的存在清单就是输入模型的身份和长期值，每个都用输入里的原名——`let pk_U = spk(sk_U)`
   这类具名派生绑定逐字保留，绝不换成匿名成员的 `pk_P`。共享值放在按序对为键的表里时，
   补上的另一次序的行装同一个值。
</constraints>

<success_criteria>
- 每个被列出的主体都有"被列出主体所占据的每个角色槽位"的实例，包括它原本的槽位。
- 每个实例与运行它的主体一致。
- 名单之外主体的实例没有变化。
- 模型在放宽后的角色指派下运行同一个协议。
- 世界恰好持有输入模型的身份和长期值；配对共享值在两种次序下读回同一个。
</success_criteria>

<example>
当 `principals = A, B` 时，两个主体都能运行两个角色槽位：

```proverif
(* 修改前 *)
type identity.
type skey.

free c: channel.
free A: identity.
free B: identity.

let processInitiator(self: identity, sk_self: skey) =
  new nonce: bitstring;
  out(c, (self, nonce));
  0.

let processResponder(self: identity, sk_self: skey) =
  in(c, (=self, nonce: bitstring));
  0.

process
  new skA: skey;
  new skB: skey;
  ( !processInitiator(A, skA)
  | !processResponder(B, skB) )

(* 修改后：A 和 B 都可以运行发起方和响应方槽位 *)
process
  new skA: skey;
  new skB: skey;
  ( !processInitiator(A, skA)
  | !processInitiator(B, skB)
  | !processResponder(A, skA)
  | !processResponder(B, skB) )
```
</example>
