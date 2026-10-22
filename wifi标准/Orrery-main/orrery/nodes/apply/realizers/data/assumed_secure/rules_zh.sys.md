<task>
要构建的情形：攻击者永远得不到 target 指名的值——分析把这一点当作前提持有。这个前提是受校验的：与它矛盾的模型会响亮报错，而不是给出判定。

形态：顶部声明中的一行 `not attacker(...)`。完全不改进程：不动角色体、不动签名、不动 main process。
</task>

<constraints>
1. 在 `target.of` 指名的现有 term 上声明前提。
2. `new` 绑定使用 `not attacker(new K).`，顶层 `free` 值使用 `not attacker(K).`。
</constraints>

<example>
参考形态（取自另一个协议；照这个结构和位置写，用当前模型里的名字）：

```proverif
(* before -- CA 私钥在 main process 里创建，其机密性由协议自己决定 *)
process
  new caSK: skey;
  ...

(* after -- 顶部声明中的一行把它变成前提。`new` 绑定的名字写 `new caSK`；
   `free` 声明的名字直接写名字本身。进程不做任何修改 *)
not attacker(new caSK).

process
  new caSK: skey;
  ...
```
</example>
