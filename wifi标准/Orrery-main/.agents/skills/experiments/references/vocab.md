# 对象级假设词表（五轴）与世界假设

判断实验产物对错时的词表参考。`AGENTS.md` 里只有概要，细节在这里。

词表 = realizer 类声明（`nodes/apply/realizers/<axis>/<subtype>/`），五根轴，每轴
问一个对象上的一个中性事实问题，档位弱→强、每轴一个 noop 档为流态默认。

## data（对象：值，instance_key=`of`）

攻击者**是否/何时拿到**该值。

```
chosen(stub) < disclosed < leaked_after_session < leaked_after_correct_session
             < none < assumed_secure
另有分支：disclosed < leaked_in_other_instances < none
```

协议定义的基线公开值（身份、公钥、公开参数等）用 fixed `data.disclosed` 表达；私有值
不因为"不是 public"而自动补 `data.none` 或 `assumed_secure`。

寿命由 `pvtext/lifetime` 判定：`disclosed` 仍按寿命选择主进程分支泄露/生成即泄露；
三个受限泄露档是独立语义，两个 after-session 档只接受长寿值，other-instances 档
只接受每会话值。

"P 可能 malicious"不是档位，是宏：展开为 P 每个长寿秘密的 disclosed。

## key_reuse（同对象，另一个问题，instance_key=`of`）

该密钥的协议外第二用途给攻击者什么：

```
oracle < observed < separated
```

攻击者驱动第二用途的输入 / 只旁观其输出（应用用同一把钥保护自己的新鲜载荷）/
没有第二用途。

它与 data 是两根轴而不是一根的判据就是**能共存**——EDHOC 的 skV 同时"会话后泄露"
与"被复用于第二用途"；一根梯子的档位互斥，能同时成立的就是两个问题。
**data 管持有，key_reuse 管使用。**

## channel（链路，instance_key=`link`）

```
public < {authentic ∥ confidential} < secure_nonbinding < secure
```

## admission（身份准入域，instance_key=`scope`）

攻击者能否在 flow marker 指名的身份 scope 中取得自己的合法参与信息：

```
open < closed
```

一张共享登记表或共享信任关系就是一个 scope；客户端与服务器使用独立身份机制时，
flow 写成两个 scope，它们才能分别 open/closed。方向由 scope 的消费者决定，认证目标
自己的方向仍由 property 表达。

flow 遇到身份、公钥、CA 或凭证语义时调用 `lookup_identity_modeling`，从 KB 返回的
1–3 个互斥方法中选择一个，把机制和 `@orrery-idiom` 标记一同写进封闭模型；验收同时
检查"候选确实返回过、每个 scope 只选一个、标记与 table/provisioning/certificate
结构相符"。

open 不再预先按这些机制分 writing：一个 sighted apply 会话阅读完整 PV，追踪
target.scope 的合法参与信息如何产生、传递、校验和消费，并完成所有必要改动。语义只
规定最终能力——攻击者取得自己的合法信息且所有 scope 消费者接受；可以改声明、角色和
main，也可以同时打开生产端与消费端的具名 gate，但不得冒充诚实主体、泄露其秘密、
删除无关检查或影响其他 scope。

## primitive（密码对象，instance_key=`family`）

```
broken < weak_member < ideal
```

全序。broken 覆盖可逆 DH/KEM 与低熵可穷举值；weak_member 是各家族的降级设定。

## 一个对象一个答案

轴的子类型是关于**同一个对象实例**的互斥答案，实例由 `instance_key` 指名
（data/key_reuse=`of`，channel=`link`，primitive=`family`，admission=`scope`）。

同一 (轴, 实例) 只准有一条声明——`validate_assumptions` 在声明层拒绝，claims 关卡
`reject_double_answers` 在每个场景的 fixed ∪ conditions 上再拒一次。这条规则取代了
旧的"反向承诺冲突声明"：唯一性比冲突表更早、更普适，且不会漏。

`validate_assumptions` 还有对称于 world 段的多余键检查——target 带一个没有任何
subtype 接收的字段，立刻报错，而不是静默随行、读起来像有意义。

**分析产物时重点查这条**：同一个值上并存"泄露"与"公理安全"，ProVerif 不会拒绝，
它只是把泄露发生的轨迹全部丢弃，verdict 顶着泄露场景的名字描述了一个无泄露的世界。
唯一性键曾经打在整个 target 上，`{holder:A, of:Kas}` 与 `{holder:AS, of:Kas}` 被当成
两个对象，同一把 Kas 上就能并存"泄露"与"公理安全"。修法是键改打在 `instance_key` 上，
并从词表删掉 `holder` 字段（2026-08-24，语料里 154 处一并清掉）。

## 世界段写的是世界假设

role_binding / population / session_multiplicity 三根轴在 `assumptions.json` 的
`world` 段（词表是 `nodes/world/builders/` 的类声明），由 extract_assumptions 读出、
build_world 恰一次施加，永不出现在场景条件里（`Point.from_ref` 指名拒绝）。

世界假设跟 fixed 条目形状完全一样——有 id、有 axis、有 target、有 subtype——区别
只有两条：没有 variable 对应物（一个 run 固定一组世界假设，换世界假设是换 run），
以及先于所有对象级假设施加。

判据是层级而不是"是不是假设"：

- **对象级假设是既定世界中对象上的谓词**：挂在模型指名的一个对象上——一个值、
  一条链路、一个身份 scope、一个密码族。
- **世界假设约束整个分析世界**：有哪些东西、谁能演什么角色、跑几轮。

参与信息靠什么机制被认可**不在世界声明里**：那是当前协议模型的全局语义，由
admission.open 的 sighted apply 会话读取。

旧的 21 轴词表（ltk_reveal 等按对象展开、世界轴混在假设里）已在 2026-08 收敛为本
设计；旧每对象名保留为提取触发词。
