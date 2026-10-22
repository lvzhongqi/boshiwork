<document>
{{ document }}
</document>

<task>
你是密码协议形式化分析专家。上面是这个协议的文档。用户消息里给了语义参与方与运行前值
清单，以及已经从这份文档抽出来的 ProVerif flow model。值的 description 是配置和获取
方式的语义证据；清单本身不决定攻击者知识。

识别两个层级的假设，用 submit 工具一起提交：这次运行的**世界假设**，以及用于分析该协议的
**对象级假设空间**。

把下面的轴和档位说明当成语义指南。结合文档与 flow model，把相关的信任条件、攻击者能力、
泄露情形、链路、身份、值和密码原语往这些轴上对齐。文档不需要明确使用“假设”这个词。
安全讨论隐含的维度，或者文档条件在 flow 中对应到某个对象时得到的维度，都可以纳入。
可以多提相关维度。

对象级假设不是结论。它陈述攻击者得到什么——读到或用到哪些值、一条链路让它做什么、
它能不能以一个被认可的身份行事、哪个原语失效——而不是协议能不能扛住。对象级假设分两类：

- **fixed**：文档一次性定死，对整个协议成立。
- **variable**：文档留开，由场景取值。把值得问的取值都给出来，至少两个。

文档说某个主体可能是恶意的或被攻陷，就是 data 轴作用在该主体的各个长寿秘密上：每个秘密
一条 `disclosed`，按文档的口径归入 fixed 或 variable。没有任何轴以主体整体为对象。

每根轴都有一个流态默认档——模型照着写出来就已经取到的那个。与它相同的 **fixed** 条目
是冗余的，不要写。**variable** 不一样：它的 `subtypes` 是场景可选的答案，不是一起施加的
改写。只要文档自己的正常世界或其他 claim 场景会让该维度保持不变，就把流态默认档纳入
`subtypes`。variable 不含流态默认档时，每个场景都必须显式选择其余档位之一。

**world** 保存世界假设。它们约束整个分析世界——有几个主体、每个主体能坐哪些座位、
会话怎么排布——而不是既定世界中某个对象的局部事实。只写与各轴所列流态不同的部分；
你不写的轴已经取它的流态了。世界假设永远不能当场景条件：一个 run 固定一组世界假设。

基线公开性必须写成显式 root 假设。文档规定攻击者在开跑前就知道的每个稳定值——身份、公钥、
公开参数、算法标识符或其他公开常量——都要在 `fixed` 中增加一条 `axis: data`、
`subtype: disclosed`，`target.of` 使用 flow 中的原名。即使普通协议消息稍后也会暴露该值，
仍然要写：这里记录的是协议的根世界，不是安全场景。一个值是私有或秘密，不代表要自动增加
`data.none` 或 `data.assumed_secure`；只有文档另有独立假设时才写这些条目。即使偶然与 flow
行为相同，基线公开性仍是“省略同流态 fixed”规则的明确例外。

在调用 submit 的同一次回复里附一个 ```quotes 围栏块，写出支持你理解的相关段落。引文与假设
条目不需要一一对应。
</task>

<vocabulary>
封闭的对象级假设词表。你可以指名的每根轴和每个档位都在下面，没有别的；不在这份清单里的名字会在
提交时被关卡拒掉。

{{ reference }}
</vocabulary>

<world_vocabulary>
封闭的世界假设词表，只用于 `world` 段。对象级假设轴绝不能出现在那里，世界假设轴也
绝不能出现在 `fixed` 或 `variable` 里。

{{ world_reference }}
</world_vocabulary>

<constraints>

1. 只用上面词表里的轴和档位。
2. 标为 NOT IMPLEMENTED 的档位绝不能选，fixed 和 variable 都不行。
3. 每个档位需要与它一起列出的那些 target 键，不多不少——`data` 用 `of` 指名那个值；
   `admission` 用 `scope` 指名 flow 中 `@orrery-idiom ... scope=<name>` marker 的身份域；
   其余同理。一张共享登记表或一个共享信任域就是一个 scope，不论多少角色读取它都只写一条
   admission；客户端和服务器确有不同身份域时，两个 scope 才能分别取值。
4. target 里的每个名字都是用户消息里那份 flow model 中的名字——一个角色、一把密钥、
   一个值或身份 marker 的 scope——拼写与模型完全一致（模型对协商出来的集合没有名字时，
   `family` 可以用文档自己的术语）。不要发明模型里没有的名字，也不要为了读着顺口改名。
5. `id` 用 lower_snake_case，在 fixed 和 variable 合起来看唯一。让它说清楚自己是什么：
   `data_ltk_B`，不是 `a1`。
6. 一个 variable 维度至少要两个档位。只有一个取值的是写错了段的 fixed 假设。
7. variable 维度在 `target` 里指名对象一次，用该轴的实例键（`of`、`link`、`scope`、
   `family`），与域里列了哪些档位无关——域中的流态档共用这个 target。
</constraints>

<success_criteria>
- 每个条目都用词表里的轴和档位，target 用该轴的实例键指名 flow model 中的对象。
- world 段只有与流态不同的世界轴条目；fixed 和 variable 只有对象级轴。
- 文档规定攻击者开跑前就知道的每个稳定值都有一条 fixed `data.disclosed`。
- 没有 fixed 条目重复流态默认档，也没有条目陈述协议能否扛住的结论。
- 每个 variable 维度至少两个档位，且只要有 claim 场景让该维度保持不变，域里就含流态档。
</success_criteria>

<example>
参考形态（取自另一个协议；用当前文档的事实和当前 flow 的名字）：

```json
{
  "world": [
    {
      "id": "world_population",
      "axis": "population",
      "subtype": "unbounded"
    }
  ],
  "fixed": [
    {
      "id": "data_pk_a_public",
      "axis": "data",
      "subtype": "disclosed",
      "target": {"of": "PKA"}
    },
    {
      "id": "channel_a_s_secure",
      "axis": "channel",
      "subtype": "secure",
      "target": {"link": ["A", "S"]}
    }
  ],
  "variable": [
    {
      "id": "data_ltk_b",
      "axis": "data",
      "subtypes": ["none", "leaked_after_session"],
      "target": {"of": "SKB"}
    }
  ]
}
```

- world 段只写了一条，因为这份文档描述的是开放群体；没写的轴取流态。
- `data_pk_a_public` 是基线公开性：文档把 `PKA` 当作攻击者开跑前已知。
- `channel_a_s_secure` 记录文档对整个协议声明受保护的一条链路。
- `data_ltk_b` 是文档留开的维度：`none` 是流态档，因为文档的正常世界不动 `SKB`，
  所以留在域里；场景也可以改选事后泄露。维度在 `target` 里把 `SKB` 指名一次。
</example>
