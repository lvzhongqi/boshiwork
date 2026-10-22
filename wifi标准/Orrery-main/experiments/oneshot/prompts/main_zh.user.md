<context>
协议：{{ protocol }}

本次 run 共用的世界（只施加一次，先于对象级假设）：
```json
{{ world_json }}
```
</context>

<input>
场景：`{{ scenario_name }}`

这个场景的完整对象级赋值：
```json
{{ scenario_json }}
```

要验证的安全目标：
```json
{{ properties_json }}
```

目标 id：{{ goal_ids }}
</input>

只为这个世界和场景构造最终模型，仅在没有选中规则覆盖时使用 flow 默认值；在恰好一个
```proverif 代码块里提交完整 `.pv`，并为每个目标 id 给出可独立归属的 query。
