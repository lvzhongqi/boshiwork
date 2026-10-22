<task>
把用户消息中的全部 `forward_secrecy` 目标注入完整场景模型。

场景模型已经包含长期密钥的妥协：要么是 `phase` 边界之后的泄露，要么是攻击者开局就持有的
知识。目标问的是：在那个世界里，已完成运行的会话秘密是否仍然安全。

每个目标值 × holder 分别建立一个私有 witness，在 holder 完成运行的末尾用本地目标值封装
它，再对 witness 写不带 phase 标注的 query：该 query 在攻击者的最终知识上判断，位于模型
所含全部泄露之后。

witness 声明、单向包装声明和 query 放进 `declarations`；witness 输出、guard 及配套
角色/main 改写放进 `edits`。
</task>

<constraints>
1. 模型的妥协结构原样保持：保留已有的每个 `phase` 边界和每处泄露，也不自己新增 phase
   或泄露。
2. 每个目标值 × `parties.holders` 项分别使用独立 witness、query 和输出；引入的名字包含
   完整 goal id。
3. witness 绑定 holder 的真实 phase-0 本地值，放在目标值可用之后及角色最后一次协议发送
   之后。
4. 按含义把目标值映射到模型中的名字、类型和本地绑定。
5. 目标的会话范围决定一次，施加到每个 witness 输出。目标只覆盖诚实会话时，凡是角色在
   运行中读入或选择过对端身份或凭证的，它的输出都要守卫：把这些实际值与 main 中独立、
   稳定的诚实值比较，并同步修改角色签名和全部调用。对端全部是 main 固定诚实参数的角色
   不加守卫。攻击者对端运行属于目标时，所有 witness 都不加守卫。guard 只包住 witness
   输出。
6. 保留协议消息、检查、分支、发送和已有 phase 边界；替换角色尾部时保留最终 `0.`。
</constraints>

<success_criteria>
- 每个目标值 × holder 有一个私有 witness、一条不带 phase 标注的 query 和一处位于该
  holder 运行末尾的 witness 输出。
- 模型的妥协结构没有变化：已有的每个 phase 边界和每处泄露都在，也没有新增的。
- 诚实会话 guard 使用独立稳定参照，并且只包住 witness 输出。
- 协议和场景假设保持原有行为。
</success_criteria>

<example>
```proverif
type key.
free c: channel.
fun senc(bitstring, key): bitstring.
reduc forall m: bitstring, k: key; sdec(senc(m, k), k) = m.
fun k2b(key): bitstring [data, typeConverter].
fun wenc_key(bitstring, key): bitstring.
reduc forall x: bitstring, y: key;
  wdec_key(wenc_key(x, y), y) = x.

free witness_forward_secrecy_app_key_A: bitstring [private].
query attacker(witness_forward_secrecy_app_key_A).

(* 会话的记录在长期密钥保护下传输，phase-1 的泄露因此能穿回它：query 判 false——
   这个协议不具备前向保密。注入只有 witness 和 query；妥协是场景自己的 *)
let processA(ltk: key, app_key: key) =
  out(c, senc(k2b(app_key), ltk));
  out(c, wenc_key(witness_forward_secrecy_app_key_A, app_key)).

process
  new long_term_key: key;
  new app_key: key;
  ( !processA(long_term_key, app_key)
  | phase 1; out(c, long_term_key) )
```
</example>
