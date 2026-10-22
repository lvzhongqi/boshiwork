<task>
在完整 ProVerif 模型中为 `target.scope` 编码 **admission.open**。

攻击者取得属于自己的合法参与信息。阅读完整模型，按照模型已有的认可语义连接生产者、
凭据、绑定、检查、角色运行和全部消费者。

攻击者用自己持有的材料从公开网络发出它自己的协议动作；诚实角色实例只为诚实主体运行，
并可把攻击者的参与者选作或接受为对端。
</task>

<constraints>
1. 完整开放 `target.scope` 从生产者到消费者的能力。
2. 为攻击者建立其自身的新身份、凭据和秘密。
3. 保留认可路径中的格式、密码学有效性和绑定检查。
4. 在攻击者合法参与者需要被选作或被接受为对端的位置，统一扩展声明、角色、辅助结构、
   登记机制和 main 调用。main 里的每个角色实例仍为诚实主体运行；攻击者自己的动作来自
   网络。
5. 按照模型的会话数量开放这项能力。
</constraints>

<success_criteria>
1. 攻击者能够构造或取得一套完整的自身参与信息，并通过目标 scope 实际执行的准入逻辑。
2. 目标 scope 的每个消费者都通过认可诚实信息的同一套逻辑认可这套新增信息。
3. 具名诚实参与者保留原有信息。
4. 在目标 scope 允许选择对端的位置，诚实角色能够与攻击者自己的合法参与者运行。
5. main 里的每个角色实例都为诚实主体运行；攻击者的参与经由网络、用它自己被认可的材料完成。
</success_criteria>

<example>
下面示例分别展示登记、凭据签发以及生产者与消费者联合开放的机制。

**登记表。** closed model 中只有诚实记录，消费者查询这些记录：

```proverif
table recognised(host, key).
...
insert recognised(A, KA);
insert recognised(B, KB);
(...)
```

开放准入时，可以增加一个复制的入口，让攻击者提交自己控制的记录，同时保留诚实记录和现有 `get` 消费者：

```proverif
insert recognised(A, KA);
insert recognised(B, KB);
( ...
| (! in(c, (attacker_id: host, attacker_key: key));
     if attacker_id <> A && attacker_id <> B then
       insert recognised(attacker_id, attacker_key)) )
```

**证书签发。** 若消费者已经接受任意正确签名的 subject/key 绑定，开放准入可以在现有可信机构下为攻击者选择的 subject 和公钥凭据增加签发路径。机构秘密仍然保密，攻击者只得到生成的合法凭据。

```proverif
| (! in(c, (attacker_id: host, attacker_pk: pkey));
     if attacker_id <> A && attacker_id <> B then
       out(c, cert(attacker_id, attacker_pk, caSK)))
```

**生产者与消费者 gate 的组合。** 模型可能已经签发合法凭据，但仍把凭据 subject 限制为一个具名诚实值：

```proverif
let (cert_id, cert_pk) = validate_certificate(cert_recv, trusted_root) in
if verify(payload_signature, cert_pk) = payload then
let (payload_id, rest) = payload in
if cert_id = payload_id then
if payload_id = HonestID then
  accept
```

开放准入可能既要签发攻击者自己的合法凭据，也要开放具名 subject 的准入 gate。证书验证、签名验证和 `cert_id = payload_id` 都应保留；只修改使合法参与仅限于 `HonestID` 的限制。模型还有其他接受检查时，也应保留，除非它们本身就在定义封闭的准入集合。
</example>
