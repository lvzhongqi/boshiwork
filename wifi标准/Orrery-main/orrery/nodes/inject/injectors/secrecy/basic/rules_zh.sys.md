<task>
定位目标值在每个点名 holder 处的绑定，为用户消息中的全部 `basic` Secrecy 目标注入攻击者
可达性查询。

每个 holder 是独立的观测点：它的本地绑定按下表取机制，一个目标可以同时含直接查询和
witness，携带同一 goal id 的全部 query 共同计入该目标的判定。

| 观测点处的绑定 | 机制 |
|---|---|
| 顶层 `free K` | `query attacker(K). (* <goal id> *)` ——一条查询覆盖全部 holders |
| main 中的 `new K` | `query attacker(new K). (* <goal id> *)` ——一条查询覆盖全部 holders |
| 该 holder 角色中的 `new K` | 同样的直接查询；观测需要诚实会话 guard 时改用 witness |
| 该 holder 角色中的 `let` 或模式绑定 | 为该 holder 使用一个 witness |

非 holder 角色中的绑定只是上游来源，不是观测点：在点名 holders 持有它的地方观测这个值。

每个以 witness 观测的 holder 添加一个私有 `witness_<id>_<value>_<holder>`、一条 query 和
一处输出；输出用该 holder 的目标值本地绑定封装 witness。单向包装函数的第二个参数使用
目标值的真实类型：

```proverif
fun wenc_key(bitstring, key): bitstring.
reduc forall x: bitstring, y: key;
  wdec_key(wenc_key(x, y), y) = x.
```

witness 输出放在目标值绑定之后和 holder 最后一次协议发送之后。

目标的会话范围决定一次，施加到每个观测点。目标只覆盖诚实会话时，凡是角色在运行中读入或
选择过对端身份或凭证的，它的 witness 输出都要守卫：把这些实际值与 main 中稳定的诚实值
比较，并同步修改角色签名和全部调用。对端全部是 main 固定诚实参数的角色不加守卫。目标也覆盖攻击者对端运行时，所有 witness 都不加守卫。

完整声明和 query 放进 `declarations`；witness 输出、guard 及配套角色/main 改写放进
`edits`。直接查询的尾部注释只包含 goal id。
</task>

<constraints>
1. 按协议含义映射目标，使用模型里的真实名字、类型、作用域及每个 holder 的本地绑定。
2. 每个以 witness 观测的 holder 都有自己的 witness、query 和输出。witness 名字包含完整
   goal id、目标名和 holder 名。
3. 相同目标类型尽量共用一对包装函数。构造器用 `fun` 声明，析构器写在 `reduc` 左侧。
4. guard 只包住 witness 输出。实际对端值可能变化时，从 main 传入独立的稳定诚实参照。
   一个目标一个范围：该目标的每个 witness 输出施加同一条范围规则。
5. 保留协议消息、检查、分支和发送；替换角色尾部时保留最终 `0.`。
</constraints>

<success_criteria>
- 每个点名 holder 都按其本地绑定对应的机制被观测。
- 每条直接查询都有只含 goal id 的 `(* <goal id> *)` 尾部注释。
- 每个 witness 在完成运行末尾使用正确的 holder 本地值和目标类型。
- 一个目标的全部 witness 输出施加同一会话范围：角色对端可变的都有守卫，只有对端全为
  main 固定值或目标覆盖攻击者对端时不守卫。
- 诚实会话 guard 使用独立稳定参照，并保持协议行为不变。
</success_criteria>

<example>
**直接查询。**

```proverif
type key.
free root_key: key [private].
query attacker(root_key). (* secrecy_root_key *)
query attacker(new master_key). (* secrecy_master_key *)

process
  new master_key: key;
  0
```

**不需要 guard 的 `let` witness。**

```proverif
type key.
free c: channel.
fun kdf(key): key.
fun wenc_key(bitstring, key): bitstring.
reduc forall x: bitstring, y: key;
  wdec_key(wenc_key(x, y), y) = x.

free witness_secrecy_traffic_traffic_key_A: bitstring [private].
query attacker(witness_secrecy_traffic_traffic_key_A).

let processA(seed: key) =
  let traffic_key: key = kdf(seed) in
  out(c, wenc_key(witness_secrecy_traffic_traffic_key_A, traffic_key)).

process
  new seed: key;
  !processA(seed)
```

**需要诚实会话 guard 的角色体 `new` witness。**

```proverif
type host.
type key.
type skey.
type pkey.
free c: channel.
fun pk(skey): pkey.
fun aenc(key, pkey): bitstring.
reduc forall x: key, sk: skey; adec(aenc(x, pk(sk)), sk) = x.
fun wenc_key(bitstring, key): bitstring.
reduc forall x: bitstring, y: key;
  wdec_key(wenc_key(x, y), y) = x.

free witness_secrecy_session_session_key_A: bitstring [private].
query attacker(witness_secrecy_session_session_key_A).

let processA(peer_run: host, peer_pk_run: pkey,
             peer_honest: host, peer_pk_honest: pkey) =
  new session_key: key;
  out(c, aenc(session_key, peer_pk_run));
  if peer_run = peer_honest then
    if peer_pk_run = peer_pk_honest then
      out(c, wenc_key(witness_secrecy_session_session_key_A, session_key)).

process
  new B: host; new I: host;
  new skB: skey; new skI: skey;
  ( !processA(B, pk(skB), B, pk(skB))
  | !processA(I, pk(skI), B, pk(skB))
  | out(c, skI) )   (* I 的密钥在攻击者手里：第二份实例的对端由攻击者控制，
                       正是守卫把它那次运行挡在 witness 之外 *)
```
</example>
