<document>
{{ document }}
</document>

<task>
你是密码协议形式化分析专家。上面是这个协议的文档。用户消息里给了协议的参与方、每一方
开跑前持有什么，以及已经从这份文档抽出来的 ProVerif flow model。

识别形式化分析专家应当对这个协议提出的**安全目标**，用 submit 工具提交。结合文档和
flow model 理解：文档给出安全语义，flow 给出这些语义所对应的模型 identifier、方向、
派生值和协议位置。

一条目标说的是应当分析什么——这个值保持机密、这一方能确信自己是在跟那一方说话——
用下面的封闭词表表达。把词表说明当成语义指南，自己判断 flow 中哪些 identifier 应当进入
每条目标。

文档里一条宽泛的安全描述，可以按不同值、方向、阶段或接受点展开成多条形式化目标；多段描述
也可以共同说明一条目标。文档句子和输出目标之间没有一一对应关系，由你自己选择有用的形式化拆分。

在调用 submit 的同一次回复里附一个 ```quotes 围栏块，写出支撑你理解的相关段落。引文与目标
不需要一一对应。不要输出目标是否成立；结论由后续运行模型得出。
</task>

<vocabulary>
封闭词表。你可以指名的每个类型和每个子类型都在下面；不在这份清单里的名字会在提交时被
关卡拒掉。

{{ reference }}
</vocabulary>

<constraints>

1. 只用上面词表里的类型和子类型。
2. 标为 NOT IMPLEMENTED 的子类型绝不能选。
3. `values` 是用户消息里那份 flow model 中的名字，拼写与模型完全一致。模型自己造出来的
   会话密钥（`new CK`）和运行前语义清单里的长期密钥一样是正当的值——要紧的是名字在 .pv 里。
4. `parties` 按类型所列的形状写：讲一个值的机密性用 `holders`（一个列表），讲一方对另
   一方的相信用 `asserter` 和 `subject`。两种形状不要混。
5. `id` 用 lower_snake_case 且唯一。让它说清楚自己是什么：`secrecy_CK`、`auth_A_B_CK`。
6. subtype 按文档陈述的保证本身选。以事后妥协或攻击者能力为前提的保证有它自己的
   subtype——长期密钥事后妥协下过往会话秘密仍安全是 `forward_secrecy`，低熵秘密抗
   离线猜测是 `weak_secret_guessing_resistance`——保证所预设的妥协由后续步骤声明，
   不参与这里的选择。`basic` 只覆盖普通机密性。

</constraints>

<example>
参考形态（取自另一个协议；用当前文档的目标和当前 flow 的名字）：

```json
{
  "properties": [
    {
      "id": "secrecy_ck",
      "type": "Secrecy",
      "subtype": "basic",
      "values": ["CK"],
      "parties": {"holders": ["A", "B"]}
    },
    {
      "id": "auth_b_a_ck",
      "type": "Authentication",
      "subtype": "injective_agreement",
      "values": ["A", "B", "CK"],
      "parties": {"asserter": "B", "subject": "A"}
    }
  ]
}
```

- `secrecy_ck`：flow 自己造出的会话密钥（`new CK`）不落入攻击者之手，在两个 holder 处观测。
- `auth_b_a_ck`：B 完成一次运行时，A 确实在与 B 运行，且两方对整个 values 向量一致，
  跨运行一一对应。
</example>
