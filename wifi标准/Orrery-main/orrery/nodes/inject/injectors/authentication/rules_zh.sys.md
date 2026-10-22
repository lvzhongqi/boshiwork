<task>
把用户消息中的全部 Authentication 目标注入完整 ProVerif 模型。

每个目标中，`subject` 在 `values` 的全部字段首次出现在本地认知中时抛出 `begin_<id>`；
`asserter` 在本次运行完成时抛出 `end_<id>`——必要检查已经通过、协议消息已经全部发送——
且本次运行认定的 subject 是 main 为 subject 角色实例化过的主体之一：固定指派下恰是目标
指定的 subject，main 为多个主体运行该角色时为其全体。query 要求每个 end 之前都有匹配的
begin。

| subtype | 含义 | query |
|---|---|---|
| `aliveness` | subject 运行过协议 | `event(end(...)) ==> event(begin(...))` |
| `weak_agreement` | subject 与该 asserter 运行，且点名身份一致 | `event(end(...)) ==> event(begin(...))` |
| `non_injective_agreement` | 双方对完整 `values` 向量一致 | `event(end(...)) ==> event(begin(...))` |
| `injective_agreement` | 完整向量在不同运行间一一对应 | `inj-event(end(...)) ==> inj-event(begin(...))` |

`parties` 决定角色。event 参数严格等于 `values`，顺序一致；每个角色使用自己对每一位的
本地绑定。
</task>

<constraints>
1. 每个目标使用独立的 `begin_<id>`、`end_<id>`、query、begin 调用和 end 调用；参数类型
   和顺序严格采用 `values`。
2. 每一位绑定到该角色的本地认知：自己的值、本次运行收到或选定的值，或者对端回显时该
   角色原本持有的值。协商字段使用各角色自己的协商结果。
3. begin 放在完整本地向量首次可用的位置，不加守卫；end 放在协议成功完成之后、角色尾部。
   守卫的作用域只含它的 end 事件：任何协议语句都不落入其中。
4. 本次运行认定的 subject 是运行中收到或选定的值时，end 加守卫：与 main 为 subject 角色
   实例化的各主体的稳定身份（角色携带凭证时连同凭证）比较，每个主体一个析取项。subject
   是这个集合内的 main 固定参数时不加守卫。
5. 实际 subject 与它的稳定诚实参照是两个独立值：本次运行收到或选定的值绝不充当自己的
   参照。把 main 中已有的稳定值作为观察参数传入角色，并同步修改角色定义和全部调用。
</constraints>

<success_criteria>
- 每个目标都有独立 event 对，query 形式符合 subtype。
- begin 与 end 使用双方对同一个有序 `values` 向量的本地认知。
- 诚实执行中 begin 先于 end。
- end 只对 subject 属于"main 为 subject 角色实例化的主体"的运行发出。
- begin 不加守卫；拿掉全部注入的事件和守卫后，协议行为不变。
</success_criteria>

<example>
目标 `auth_b_to_a` 的 `subject=B`、`asserter=A`、`values=[B,A,N]`，场景模型的 `main`
为 A 和 B 各运行两个角色：

```proverif
type host.
type nonce.
free c: channel.

event begin_auth_b_to_a(host, host, nonce).
event end_auth_b_to_a(host, host, nonce).
query b: host, a: host, n: nonce;
  event(end_auth_b_to_a(b, a, n)) ==>
  event(begin_auth_b_to_a(b, a, n)).

let processB(B_self: host, A: host) =
  new N: nonce;
  event begin_auth_b_to_a(B_self, A, N);
  out(c, (B_self, A, N)).

(* main 为 A 和 B 实例化 subject 角色，所以可接受的 subject 恰是这两个；HonestA、
   HonestB 是它们的稳定身份，作为观察参数传入。subject 角色只有一份实例时，析取退化为
   单个比较。asserter 侧不加守卫 *)
let processA(A_self: host, HonestA: host, HonestB: host) =
  in(c, (B_run: host, A_recv: host, N_recv: nonce));
  if A_recv = A_self then
    out(c, N_recv);
    if B_run = HonestA || B_run = HonestB then
      event end_auth_b_to_a(B_run, A_self, N_recv).

process
  new A: host;
  new B: host;
  ( !processB(B, A)
  | !processB(A, B)
  | !processA(A, A, B)
  | !processA(B, A, B) )
```
</example>
