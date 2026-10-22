<task>
你是密码协议形式化分析专家。系统上下文里是当前的 ProVerif 模型；把安全假设
**data.leaked_after_correct_session** 编码进去，提交锚定编辑；框架会把你的编辑拼进文件。

要构建的情形：指名的长寿秘密到达攻击者，但只在一个**正确完成**的会话之后——弱前向安全
（wPFS）前提。那个完成会话的每条消息都是在秘密仍然安全时交换的；泄漏只存在于发生过正确完成
的世界里。

它的形态：两件东西，都归这条假设所有。
1. 完成记录：声明一张 table，在持有方角色正确完成的那个点——最后一个协议检查通过、最后一次
   协议发送完毕——向它 insert 一个常量记号。
2. 门控泄漏：main process 并行组里加一个不带复制的新分支
   `| phase <N>; get <table>(x) in out(c, K)`，`<N>` 是 target 指名的相位。table 的行
   跨相位边界持久存在，所以泄漏恰好只在记录过正确完成的世界里发生。
</task>

<constraints>
1. 完成记录只写在成功路径上：角色最后一个协议检查和最后一次协议发送之后。
2. 泄漏同时被相位边界和 table 读取把门：`phase <N>; get <table>(x) in out(c, K)`。
3. table 的行只装一个常量记号；秘密只出现在门控分支的 `out(c, K)` 里。
</constraints>

<example>
参考形态（取自另一个协议；照这个结构和位置写，用当前模型里的名字）：

```proverif
(* before -- 角色尾部：最后的检查通过，进程体结束 *)
let processB(B: host, K: key) =
  ...
  if h = hash(Nb) then
  out(c, senc(ack, CK));
  0.

process
  ( !processA(...) | !processB(...) )

(* after -- (1) 尾部的完成记录；(2) main 里的门控泄漏。
   table 的行跨相位边界持久存在，所以 K 恰好只在有会话正确完成的世界里泄漏 *)
table session_done(bitstring).
const done_tok: bitstring.

let processB(B: host, K: key) =
  ...
  if h = hash(Nb) then
  out(c, senc(ack, CK));
  insert session_done(done_tok);
  0.

process
  ( !processA(...) | !processB(...)
  | phase 1; get session_done(x) in out(c, K) )
```
</example>
