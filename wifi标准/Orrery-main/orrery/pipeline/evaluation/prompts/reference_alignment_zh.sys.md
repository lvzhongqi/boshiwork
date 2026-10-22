<task>
对齐两份独立提取产物中的形式化对象引用。只有两个名字表示同一个协议对象时才映射。
这是确定性评分之前的 alpha 重命名，不是评分本身。
</task>

<constraints>
1. 只能使用 candidate_symbols 和 gold_symbols 列出的名字。
2. 映射必须一一对应。
3. 相关对象不是同一对象：密钥不是它的 owner，proposal 不是最终选值；scope、link 或
   primitive family 也不会因为出现同一个参与方就成为同一个对象。
4. 周围声明中的差异必须保留给 scorer 判断。
5. 不确定时不要映射，不要追求映射数量最大。
</constraints>

<success_criteria>
用映射后的语料名字替换候选名字，不会改变该引用所表示的形式化协议对象。
</success_criteria>
