<context>

协议：{{ protocol }}

语义参与方与运行前值（description 是语义证据，不是预制的 ProVerif 进程签名）：

{{ knowledge_json }}

声明参考：

{{ reference }}

</context>

<input>
# 骨架（信道和诚实运行探针固定；在各标记处补声明、每个角色和 main process）
```proverif
{{ template }}
```
</input>

补全模板并提交完整的 .pv；提交时框架会检查它并把发现返回给你。
{{ step_messages }}
