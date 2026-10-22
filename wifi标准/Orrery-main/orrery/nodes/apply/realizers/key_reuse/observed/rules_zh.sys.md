<task>
你是密码协议形式化分析专家。系统上下文里是当前的 ProVerif 模型；把安全假设
**key_reuse.observed** 编码进去，提交锚定编辑；框架会把你的编辑拼进文件。

要构建的情形：`target.of` 指名的密钥在这个部署里还有第二用途——协议之外的一个应用用同
一把钥保护它自己的数据——而攻击者看得到第二用途的输出。应用的载荷是它自己的新鲜值，
target 给了 `target.payload` 就用它给的名字；攻击者旁观流量，拿不到钥，也选不了载荷。

它的形态：在已有在该密钥下发送的那个角色的尾部追加一次使用，位置在该角色完整跑完之后——
每一步接收处理完、每一个检查通过、最后一次协议发送做完，在进程体尾部。找到该角色对这把钥的既有使用，顺着协议
套在外面的每层封装读到送出它的 `out(...)`，在尾部把整条链原样复现一次：载荷换成一个新鲜
值，其余每个参数——密钥、transcript、associated data——都从这次已完成运行自己的值里抄。

- **签名私钥**：同一把钥对同一份 transcript 连同新鲜载荷再签一次，签名走角色自己的签名
  走的那条路。
- **对称密钥**：新鲜载荷用角色在这把钥下已在使用的原语再保护一次——同样的上下文参数——
  走同一条路。
</task>

<constraints>
1. 恰一处追加，位于"被复现的那条链所属角色"的尾部；其余角色原样不动。
2. 新鲜载荷是唯一的新名字；其余每个参数——密钥、transcript、associated data、tag——都
   从角色已有调用里抄。
3. 追加的使用放在整个协议流程完成之后——该角色最后一步解密、最后一个认证检查、最后一次
   协议发送都过了之后——绝不放在"收到消息"和"校验它的检查"之间。检查之前就能到达的使用会把角色变成
   攻击者输入的 oracle，那是比这一档更强的世界。角色已有的每一行都保留。
</constraints>

<examples>
<example>
一把签名密钥，它在协议里走的路要穿过 AEAD（取自另一个协议；照这个结构和位置写，用当前
模型里的名字）：

```proverif
(* before -- 角色体的末尾。先读清楚这个签名走的路：
   sign(...) -> 被 aeadEncrypt(..., K_3, aad_3) 封起来 -> out(c, ...) *)
let processI(...) =
  ...
  new app1: bitstring;
  out(c, aeadEncrypt((tag_prot, sign((tag_prot, TH_4, app1), skI)), K_3, aad_3));
  0.

(* after -- 新鲜载荷，同一把钥、同一份 transcript、同一个 tag，走同一条路出去：
   追加的签名同样封进 AEAD。上面的协议流程一个字没动 *)
let processI(...) =
  ...
  new app1: bitstring;
  out(c, aeadEncrypt((tag_prot, sign((tag_prot, TH_4, app1), skI)), K_3, aad_3));
  new app2: bitstring;
  out(c, aeadEncrypt((tag_prot, sign((tag_prot, TH_4, app2), skI)), K_3, aad_3));
  0.
```
</example>

<example>
一把对称密钥——载荷是新鲜的，上下文是角色自己的；普通对称加密没有单独的上下文参数：

```proverif
(* AEAD *)
let processI(...) =
  ...
  out(c, aeadEncrypt(app1, K_3, aad_3));
  new app2: bitstring;
  out(c, aeadEncrypt(app2, K_3, aad_3));
  0.

(* plain senc *)
let processA(...) =
  ...
  out(c, senc((K_ab, B), K_as));
  new app2: bitstring;
  out(c, senc(app2, K_as));
  0.
```
</example>
</examples>
