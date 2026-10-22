<input>
产物类型：{{ kind }}

候选符号：{{ candidate_symbols }}
语料符号：{{ gold_symbols }}

候选产物：
{{ candidate }}

语料产物：
{{ gold }}
</input>

给出候选名字到语料名字的 alpha 重命名。

<output_format>
只输出一个符合以下 schema 的 JSON 对象，不要输出其他内容：
{{ schema }}
</output_format>
