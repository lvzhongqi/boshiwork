<input>
本批 fixed data 假设：
{{ assumptions_json }}

声明与模型可能对同一个名字采用不同写法。按语义映射每个 target，并在
`coverage.model_term` 和编辑中统一使用模型已有的记法。
</input>

在系统上下文的模型上完整编码这一批假设。每个 assumption id 提交一条 coverage 记录，
并提交一组统一的锚定编辑。引用每处编辑所附着的原模型行；框架会拼接编辑并运行检查。
{{ step_messages }}
