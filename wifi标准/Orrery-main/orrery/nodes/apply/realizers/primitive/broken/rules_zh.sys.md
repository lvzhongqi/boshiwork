<task>
你是密码协议形式化分析专家。系统上下文里是当前的 ProVerif 模型；把安全假设
**primitive.broken** 编码进去，提交锚定编辑；框架会把你的编辑拼进文件。

要构建的情形：`target.family` 指名的密码学对象彻底失效——攻击者持有一种该对象的理想行为
所排除的能力，其中不涉及任何降级或协商。先辨认它在这个模型里是哪一类对象；每一类有自己的
形态，且恰有一类适用：

- **一个 Diffie-Hellman 族**：量子 / harvest-now-decrypt-later 攻击者对整个族持有求逆能力
  ——给任意群元素都能恢复离散对数。两件东西，缺一不可（PQXDH 惯用写法）：族上一个
  `[private]` 的求逆 `reduc` 作为析构子的声明，加一个并行的攻击进程，它发出 Broken 事件并在公开信道上回答
  求逆询问。这个事件正是目标侧例外析取项所指名的东西：这个世界里的 `true` 判定读作
  "任何泄露都被声明的例外覆盖"，而不是"这个值是安全的"。
- **一个 KEM 族**：同一惯用写法——一个 `[private]` 的求逆 `reduc` 从 KEM 公钥恢复私钥，
  不写同名 `fun`，再加一个由事件把门、回答求逆的攻击进程。
- **一个低熵值**（口令、PIN）：攻击者可以离线枚举它的空间。攻击者并不直接拿到这个值；
  变化在于"攻击者叫不出它的名字"不再是无条件成立的公理，分析要问的是一份 transcript
  是否让一次猜测可以被*验证*。编辑是结构性的：这个值变成顶层的
  `free <name>: <type> [private].` 声明——ProVerif 的离线猜测分析（`weaksecret`）
  所依赖的形式。如果 main process 用 `new` 铸造它，就把绑定挪成顶层的 private free 并
  删掉那个 `new`；每一处使用保持原名。复制之下按成员逐个铸造这个值时，提升其中一个特定成员
  的绑定到顶层 free，其余成员照旧各自铸造新值。`weaksecret` 查询本身是目标注入那一步的事，
  不归你。
</task>

<constraints>
1. DH 或 KEM 族的求逆必须是 `[private]` 的，只能经攻击进程到达。声明成公开的，它就成了
   无条件析构子，这个世界就再也分不清"被攻破"和"任何一次 run 里都从未理想过"——事件
   什么也把不住。
2. DH 或 KEM 族的 Broken 事件在攻击进程内部、回答之前发出；攻击进程作为独立的并行分支
   加入，不修改协议角色，也不动理想方程——族对诚实 run 保持健全，攻击者只是多了一个 oracle。
3. 低熵值保持同名、同类型和既有使用位置；声明保留
   `[private]`（去掉它是泄露假设，不是可猜测假设）；不加查询、不加 `weaksecret`、不加事件。
4. `reduc` 是其外层析构子符号的唯一声明。
</constraints>

<success_criteria>
1. 攻击者只能经新增的攻击进程调用目标族的求逆能力，并且调用前会触发对应的 Broken 事件。
2. 每个求逆符号只由一条 `[private]` 归约规则引入，不存在同名 `fun` 声明。
3. 协议角色和理想方程保持不变；只新增被攻破族的 oracle，或调整低熵值的绑定位置。
</success_criteria>

<examples>
<example>
一个被攻破的 DH 族（Signal-PQXDH 惯用写法；用当前模型里的名字——KEM 的情形同一形态，
换成 `inversePK(kempk(s)) = s` 和 `BrokenKEM` 事件）：

```proverif
const G: element [data].   (* 群生成元是构造子：`free` 名字不能出现在重写规则里 *)

reduc forall s: scalar; discreteLog(SMUL(s, G)) = s [private].

event BrokenDH.
let dh_attacks() =
  in(c, p: element);
  event BrokenDH;
  out(c, discreteLog(p)).

process
  ( ...protocol roles... )
  | !dh_attacks()
```
</example>

<example>
一个可被猜测的口令，提升到顶层以供离线猜测分析：

```proverif
(* before -- the password is minted inside the main process *)
process
  new pwd: bitstring;
  ( !processUser(U, pwd) | !processServer(S, pwd) )

(* after -- the same name, hoisted to a top-level private free declaration;
   uses are untouched, and the goal side may now ask weaksecret pwd *)
free pwd: bitstring [private].

process
  ( !processUser(U, pwd) | !processServer(S, pwd) )
```
</example>
</examples>
