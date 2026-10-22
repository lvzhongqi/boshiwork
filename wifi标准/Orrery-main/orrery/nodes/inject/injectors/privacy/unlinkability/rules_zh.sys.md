<task>
把唯一的 `Privacy.unlinkability` 目标注入为 ProVerif biprocess。

运行两次相同协议。左投影的两次选定会话都使用原 subject；右投影的第一次使用原 subject，
第二次使用一个同类型的新备选 subject。对 `parties.subjects` 中每个主体，把代表它的身份和
长期身份凭证作为一套一致切换。

备选 subject 声明放进 `declarations`；biprocess main 改写和精确标记
`(* @orrery-unlinkability <goal id> *)` 放进 `edits`。observational equivalence 结果就是
该目标的 verdict。
</task>

<constraints>
1. 为该目标建立一个双会话 biprocess；两个投影只在选定的第二次会话属于哪个 subject 上
   不同。
2. 把 `choice[original,alternative]` 放在携带 subject 的角色/会话参数及其一致的长期身份
   凭证组上。
3. 按替换点类型为每个备选 subject 声明顶层私有名字；引入的名字包含完整 goal id。
4. 两个投影保留相同的公开消息、会话新鲜值、角色体、密码运算、检查、信道和场景假设。
5. 精确 goal marker 出现一次；该目标使用 observational equivalence，不使用可达性 query。
</constraints>

<success_criteria>
- 模型含一个 goal marker 和一处左右项不同的 `choice[left,right]`。
- 两个投影都运行两次相同协议，唯一区别是第二次选定会话的 subject。
- 每个 subject 的身份和身份凭证一致切换。
</success_criteria>

<example>
```proverif
free alternate_unlink_alice: host [private].

(* @orrery-unlinkability unlink_alice *)
process
  ( Session(A)
  | Session(choice[A, alternate_unlink_alice]) )
```
</example>
