<task>
你是密码协议形式化分析专家。系统上下文中是一份完整的 ProVerif 场景模型，用户消息包含一个 `weak_secret_guessing_resistance` 目标。为目标指名的每个值注入 ProVerif 离线猜测查询。

这个目标问的是：公开 transcript 是否给攻击者提供了验证低熵秘密猜测的方法。它不是普通的可推导性；私有口令可能满足 `query attacker(password)`，但 transcript 仍可能暴露离线验猜方法。ProVerif 用 `weaksecret password.` 表达这里真正的问题。

低熵假设已经把每个目标值表示为顶层 private `free` 名字。为每个目标值提交一条完整的
`weaksecret <值>.` 声明；该目标只需要声明。
</task>

<constraints>
1. 按含义对应每个目标值，使用模型中的准确名字。
2. 对 `values` 中每个值，使用其已有的顶层 private `free` 绑定添加一条
   `weaksecret <值>.`。
3. 所有语句放进 `declarations`，`edits` 提交空列表。
</constraints>

<success_criteria>
- 每个目标值恰有一条 `weaksecret` 声明，并使用对应的顶层 private free 名字。
- `edits` 为空，协议行为没有变化。
</success_criteria>

<example>
```proverif
free password: bitstring [private].
weaksecret password.
```

在 `declarations` 中提交 `weaksecret password.`，并提交空的 `edits` 列表。
</example>
