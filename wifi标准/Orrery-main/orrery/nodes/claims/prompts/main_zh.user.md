<context>

协议：{{ protocol }}

从这份文档读出的假设空间 —— 只拿 `variable` 里的条目当条件：

{{ assumptions_json }}

从这份文档读出的目标 —— 只 claim 这些 id：

{{ properties_json }}

从这份文档提取的 flow model —— 只用它把上面的 query 对齐到模型的精确名字和协议结构：

```proverif
{{ flow_pv }}
```

</context>

读出场景和 claims 并提交，同一次回复里附一个 ```quotes 块。
{{ step_messages }}
