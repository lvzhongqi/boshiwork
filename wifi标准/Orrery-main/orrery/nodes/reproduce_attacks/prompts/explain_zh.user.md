<context>
协议：{{ protocol }}
场景：{{ scenario }}

这个场景的假设：
{{ assumptions }}

不成立的目标：
{{ goal }}
{% if replay %}
求解器报告了重放：这个目标的单射形式不成立，非单射形式成立。
{% endif %}
</context>

<input>
{{ script }}
</input>

讲清楚这次攻击，然后提交讲解。
{{ step_messages }}
