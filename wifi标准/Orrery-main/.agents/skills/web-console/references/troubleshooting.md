# 控制台排查

页面不对劲时查这里。日常规矩在 [SKILL.md](../SKILL.md)。

## 改完必须到浏览器里看一眼 console

**`node --check` 看不见模板字符串里的东西。**整个 Vue 模板是 `main.js` 里的一个 JS
模板字面量,里面的表达式对它就是普通字符串。下面三种全都语法检查通过、运行时白屏,
console 里的报错原文就是索引:

- `SyntaxError: Unexpected identifier '$'` —— 模板里写了反引号做插值,一个反引号就把
  整个模板字面量提前结束了。**模板里只能用字符串拼接。**
- `t.retryTip is not a function` —— `t` 是 `computed`,模板里自动解包,
  **setup 里必须写 `t.value.xxx`**。
- `Cannot access 'X' before initialization` —— `const` 声明在 setup 靠后,但某个
  `immediate` 的 watcher 在前面读它(TDZ)。**状态一律声明在它的消费者之前。**

白屏时不要猜,先看 console。另外两条:前端异常会让整页消失,**看起来像后端死了**,
先 `curl` 一下 API 再下判断;改完 JS/CSS 必须 **Cmd+Shift+R 硬刷新**,而且刷完等一下
再点——加载途中的点击不生效,会误以为功能坏了。
