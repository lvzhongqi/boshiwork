```proverif
{{ pv }}
```

{{ rules }}

<encoding_freedom>
realizer 规则定义的是修改后成立的世界，不固定 ProVerif 代码形态。阅读完整模型，按需要
统一修改声明、角色定义与角色体、辅助进程、table、channel 和 main process。保持规则
规定的语义边界与无关协议行为。示例只说明含义，实际实现由当前模型决定。
</encoding_freedom>

<batch_contract>
本次输入全部是 fixed 层中 subtype 和 writing 相同的 data 假设。用一组编辑把所有输入
一次性编码进去。兼容的改动可以共用一个分支或声明块，并覆盖全部输入。writing 规则按单个
`target.of` 描述；对列表里的每个 target 分别应用这些
规则。因此规则中的“一个值”是每条假设各自的一个值，不是整批只能处理一个值。
</batch_contract>
