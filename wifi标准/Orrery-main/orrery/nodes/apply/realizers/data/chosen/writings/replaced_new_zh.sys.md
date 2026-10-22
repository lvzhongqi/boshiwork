<task>
你是密码协议形式化分析专家。系统上下文里是当前的 ProVerif 模型；把安全假设
**data.chosen**（角色自己抽签的值）编码进去，提交锚定编辑；框架会把你的编辑拼进文件。

要构建的情形：`target.of` 指名的值由角色自己创建，每个会话抽一次；这个世界里，这次创建
被攻击者输入取代——随机源被操纵的设定，coins 来自失陷的运行时。角色拿着攻击者递过来的
东西跑，凡是由这个值派生出来的绑定，都由攻击者说了算。

它的形态：该值的 `new` 绑定变成同名同类型的 `in(c, ...)`。别的一概不动——下面每一处使用
读到的已经是对的名字；这里也没有诚实参照要保留，因为角色自己抽出来的值没有一个被配置的
对应物可供比较。
</task>

<constraints>

1. 名字和类型都不变。函数体下面每一处都在引用它；这里改名等于白白重写整个函数体，改类型
   会让文件过不了类型检查。
2. 只替换 `target.of` 指名的那一个 `new`。一个角色抽好几个值是为了不同的目的，顺手把别的
   也换掉，就建出了比声明更宽的世界。
3. 角色体内用 `new` 绑定一个配置项，通常是建模失误：配置属于初始知识，应该放在角色参数里，
   那样适用的是这条假设的另一个写法。按要求把世界编码出来，同时把这个观察记下来——产物里
   在文件顶部加一行注释，指出这个值在上游疑似被错误地建模成了新抽的。这行注释是日后修正
   母本模型的线索。

</constraints>

<example>
参考形态（取自另一个协议；照这个结构和位置写，用当前模型里的名字）：

```proverif
(* before -- the role draws the value itself, once per session *)
let processA(A: host, B: host, SKA: skey) =
  new Na: nonce;
  out(channel_A_B, (A, Na));
  ...

(* after -- the draw becomes attacker input, same name, same type. Nothing
   below moves *)
let processA(A: host, B: host, SKA: skey) =
  in(c, Na: nonce);
  out(channel_A_B, (A, Na));
  ...
```
</example>
