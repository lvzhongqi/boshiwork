<task>
你是密码协议形式化分析专家。系统上下文里是当前的 ProVerif 模型；把安全假设
**primitive.weak_member** 编码进去，提交锚定编辑；框架会把你的编辑拼进文件。

要构建的情形：`target.family` 指名的族，其协商空间里含有一个协议仍可能合法选中的弱成员。
会话选中它时，这个族的标志性保证作废；会话选中强成员时，一切照旧成立。攻击者通往弱成员的
路径就是协商本身——公开网络上它可以引导或篡改被提议的参数，所以"协商值可被篡改"是这条
假设经普通网络的自然行使，不是另一条假设。

所有族共用一个惯用写法（TLS-lib 形态），三件东西：
1. 为这个族声明一个算法类型，带 Weak 和 Strong 两个常量。
2. 把原语改成按算法参数化：强分支保持理想行为；弱分支承载该族的标志性失效——
   - **hash**（SLOTH）：弱成员的输出碰撞——`hash(WeakHash, x) = collision`，指向单一的
     `const collision`，而 `hash(StrongHash, x)` 保持理想。
   - **DH group**（Logjam）：弱群上的指数运算返回一个固定可预测的元素——
     `dh_exp(WeakDH, e, x) = BadElement`，强分支保持理想。
   - **AEAD**（Lucky13/RC4 一类）：弱成员既可锻造又泄露——一个仍解密回 `p` 的
     `aead_forged(p, aead_enc(WeakAE, ...))`，加一个
     `aead_leak(aead_enc(WeakAE, k, n, ad, x)) = x` 析构子。
   - **PKE**（Bleichenbacher/DROWN）：弱解密在攻击者构造的输入上成功、强解密失败，
     交给攻击者一个 oracle。
   - 失效方式不同的族照同一拆分办：强 = 理想，弱 = 该族有文献记载的破绽。
3. 把协商出的算法穿进原语的每一处已有调用，并在会话选定它的位置发出事件
   （`event ServerChoosesHash(..., h)` 或当前模型的对应写法），让目标侧能把弱选择指名为
   它允许的例外。模型里没有协商值时，就在这里补上：做选择的角色在首次使用前从网络接收
   算法（`in(c, halg: hash_alg)`）——网络就是协商面——随后同样穿进各调用、发出同一个事件。
</task>

<constraints>
1. 弱成员经协商可达，而不是被强制。两个常量都存在，会话可以任选其一；处处硬写弱成员验的是
   一个坏掉的协议，不是一个带弱选项的敏捷协议——那个世界是 `primitive.broken`。
2. 只有弱分支失效。强分支保持理想行为；两个分支一起塌掉，就抹掉了这条假设所关心的区分。
3. 在算法被选定的位置把这个选择发成事件。目标侧的例外析取项以这个事件为键；漏掉它，
   `true` 判定就承载不了"或者该会话选了弱成员"这层读法。
</constraints>

<example>
hash 族的参考形态（TLS13-lib 惯用写法；用当前模型里的名字和当前的族）：

```proverif
(* before -- an ideal hash *)
fun hash(bitstring): bitstring.
...
  let th = hash(transcript) in ...

(* after -- an agile hash with a colliding weak member *)
type hash_alg.
const StrongHash, WeakHash: hash_alg [data].
const collision: bitstring [data].
fun hash_ideal(bitstring): bitstring.
fun hash(hash_alg, bitstring): bitstring
reduc forall x: bitstring; hash(WeakHash, x) = collision
otherwise forall x: bitstring; hash(StrongHash, x) = hash_ideal(x).
...
  let th = hash(h, transcript) in ...      (* h is the negotiated algorithm *)
  event ServerChoosesHash(cr, sr, h);
```
</example>
