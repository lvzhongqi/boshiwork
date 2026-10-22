<task>
你是密码协议形式化分析专家。系统上下文里是当前的 ProVerif 模型；把安全假设
**data.leaked_in_other_instances** 编码进去，提交锚定编辑；框架会把你的编辑拼进文件。

要构建的情形：这个协议的其他会话已经跑完，并交出了它们那份指名的每会话值——一把会话密钥
连同该会话产出的凭证，或一段从内存里读出的中间状态——这些副本都在攻击者手里。每个在跑
会话自己那份副本仍须达成目标。这是 known-key / state-reveal 的设定：旧 run 的密钥被密码
分析恢复、被换出的进程留下的状态被提走。

它的形态：一个带 `!` 复制的残留进程加入 main process 的并行组；已有的一切——包括会话组
的复制——原样保持。残留进程每一轮创建一个与 `target.of` 指名的值同类的值并公布它，同时
公布协议为这类值包装的凭证——同样的消息形态、用模型自己的长期密钥。它不执行任何协议
步骤，也不从任何信道读取：一个跑完的会话留下的只是一个值和一份凭证，没有任何活动的部分。
</task>

<constraints>
1. 残留进程是一个只创建、只输出的独立进程：不含协议步骤，不读信道，不引入 `phase`。
2. 每个残留物用模型自己的材料构造：同一批长期密钥、同一凭证与消息形态。
3. main process 现有结构原样保持，会话组的复制在内；残留分支是唯一的改动。
</constraints>

<example>
一把会话密钥，连同它那个会话产出的票据（取自另一个协议；照这个结构和位置写，用当前模型里的名字）：

```proverif
(* before -- the main process runs one replicated session group *)
process
  !( Alice(A, B) | Bob(A, B) | Server(A, B) )

(* after -- 复制的残留进程加入并行组；会话组本身原样不动。用模型自己的 KB 封起来的
   票据那一行才是泄露的力量所在：协议没绑定到任何东西的值，交出去也不会给攻击者
   它没有的东西 *)
let otherSessionLeftovers(A: host, B: host, KB: key) =
  new CK_old: key;
  out(c, CK_old);                    (* the finished session's key *)
  out(c, senc((CK_old, A), KB));     (* its ticket -- B cannot tell old from new *)
  0.

process
    !( Alice(A, B) | Bob(A, B) | Server(A, B) )
  | !otherSessionLeftovers(A, B, KB)
```
</example>
