<flow_model>
{{ flow_pv }}
</flow_model>

<task>
把标准声明中未解析的名称翻译为本次 flow model 实际使用的准确名称。这只是 alpha-renaming；不得改变声明语义。
</task>

<constraints>
- 阅读完整模型以及每个名称所属的声明。
- 映射目标必须是 flow model 中真实存在的一个准确标识符，且它绑定的是该值本身——作为该值被创建、派生或接收。
- 映射保持一对一。不能仅因拼写相似就选择附近的标识符。
- 如果一个 property value 由多个角色专属绑定表示，或者嵌在一个项中，将它放入 contextual，不能任意选择一个绑定。contextual 候选同样是该值的绑定。
- assumption target 必须得到一个具体映射，因为 apply 先于 inject 运行。
- 如果 flow model 缺少必需概念，对 extract_flow 调用 report_gap。不能编造映射。
</constraints>

<success_criteria>
- 每个未解析源名称恰好出现一次：位于 mappings 或 contextual。
- 每条映射都有具体的 flow model 绑定或使用作为依据。
- 只有不存在保留语义的单一 alpha-renaming 时才使用 contextual。
</success_criteria>

<example>
标准角色 FIDO_Authenticator 与 flow 角色 Authenticator 直接映射。标准 K_2 在 flow 中表示为 K_2_Initiator 和 K_2_Responder 时，以这两个候选作为 contextual。
</example>
