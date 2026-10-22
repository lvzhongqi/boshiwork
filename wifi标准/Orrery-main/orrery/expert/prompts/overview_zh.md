<run_state>
这是这次 run 此刻的状态，为这条消息从磁盘读出。它是一份摘要，不是证据：引用要引产物、会话或文档，
绝不要引这个块。

- run: {{ run_name }} | protocol: {{ protocol }}{% if subprotocol %}（子协议 {{ subprotocol }}）{% endif %}
- status: {{ status }}{% if status == "running" %} —— 流水线还在往这个目录里写，所以产物缺失可能是"还没到"，而不是"出错了"{% elif status == "check_failed" %} —— 某一步跑完了但它的检查说不通过（与 ground truth 的交叉检验不一致）；那一步的产物在磁盘上，它之后的步骤从未运行{% elif status == "failed" %} —— 某一步没能跑完，run 就停在了那里；失败之后的步骤从未运行，所以它们本该产出的东西是"不存在"，而不是"空"{% endif %}
{% if from_node %}- 重入自：{{ from_node }}（它之前的步骤沿用了上一次尝试的结果）
{% endif %}- 步骤：{{ steps }}
{%- if scenarios %}

各场景及其判定：
{% for line in scenarios %}- {{ line }}
{% endfor %}{%- endif %}
{%- if answers %}

最终答案（results.json）：{{ answers | join(", ") }}
{%- endif %}
{%- if gaps %}

{{ gaps }}
{%- endif %}
{%- if facts %}

已为这次 run 的各步骤归档的消息（步骤（来源）：正文）：
{% for line in facts %}- {{ line }}
{% endfor %}不要提出重复其中某一条的修正；直接说这件事已经提过，并报告那一步拿它做了什么。
{%- endif %}
{%- if sessions %}

可用 read_transcript / read_prompt 读取的会话：
{% for name in sessions %}- {{ name }}
{% endfor %}
{%- endif %}
</run_state>
