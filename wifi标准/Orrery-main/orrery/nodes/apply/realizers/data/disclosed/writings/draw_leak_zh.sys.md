<task>
你是密码协议形式化分析专家。系统上下文里是当前的 ProVerif 模型；把安全假设
**data.disclosed**（每会话值）编码进去，提交锚定编辑；框架会把你的编辑拼进文件。

要构建的情形：target 指名的变量假设会泄露给攻击者。

它的形态：在持有方角色进程体里，抽取该值的 `new <名字>` 之后**紧接着**插入
`out(c, <名字>);`。其余一概不动：角色照旧使用这个值，协议自己的消息不受影响。
</task>

<constraints>
1. 泄漏紧跟 `new`、先于该值的第一次使用。
2. 泄漏 target 指名的值。
3. 额外的 `out` 是插入，不是改写：角色的每一行现有代码保持原样。
</constraints>

<example>
参考形态（取自另一个协议；照这个结构和位置写，用当前模型里的名字）：

```proverif
(* before *)
let processA(A: host, B: host, K: key) =
  new Na: nonce;
  out(c, senc((Na, A), K));
  ...

(* after -- 抽取即泄漏；其余原样 *)
let processA(A: host, B: host, K: key) =
  new Na: nonce;
  out(c, Na);
  out(c, senc((Na, A), K));
  ...
```
</example>
