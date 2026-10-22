# 密码协议攻击分类：文献、工具能力与语料实证

调研日期 2026-09-16。范围：密码协议攻击的分类学文献（1978–2023）、自动化形式验证工具反例中可观测的信号（ProVerif 2.05 实测，Tamarin 文档对照）、以及 VerdictBench 语料的全量统计。

本文只报告调研与实证结果，不含任何词表设计方案。

## 0. 摘要

密码协议攻击分类学的文献有清晰的两个阶段。

1994–2003 年出现了一批**按攻击手法**划分的分类学：Carlsen 的七类缺陷、Syverson 的重放二维分类、Clark & Jacob 的六类、Gritzalis & Spinellis 的六类两层、Boyd & Mathuria 的十类平列清单。这批分类学有一致的通病：类目公开重叠、层级关系在作者之间直接冲突、清单自认不完备、类目外延随工具能力漂移，同一个攻击在不同体系里有不同名字（Lowe 对 NSPK 的攻击有四个）。

2001 年后领域转向**按敌手能力**做维度化。Basin & Cremers (TISSEC 2014) 沿三个维度分解安全定义，得到七条规则、96 个可区分模型，并把 PFS、wPFS、UKS、KCI 拆成「基本性质 × 敌手模型」二元组。TLS 降级领域的 Alashwali & Rasmussen (2018) 独立采用了同样的形态：四根轴，每轴一个问句。两者都放弃了树形结构。最直接的一处印证是 Boyd & Mathuria 自己：第 1 版 §1.6 叫 "Types of Attack on Protocols"，第 2 版改名为 §1.4 "Adversary Capabilities"，十个条目一字未动。

仓库与工具层面没有受控词表。SPORE 的 LaTeX `attacks` 环境零参数，AVISPA 的 `CLASSIFICATION` 字段挂的是 G1–G20 目标码而 `ATTACKS` 是自由文本，ProVerif 与 Scyther 的示例库按安全属性组织。三十年里没有任何仓库或工具为攻击类型开过字段，却全都为目标开了。

把工具反例自动归类的工作基本不存在，且做过的人都退回到人工。USENIX Security 2023 的一条脚注说得最直白：先前工作能自动发现 attack pattern，是因为那些 pattern 只限定在对抗能力这一层；一旦要求 pattern 描述攻击本身，就只能手工。

ProVerif 2.05 的反例里，能机械判定的攻击特征只有四族：重放（工具自己给的判词）、猜测（weaksecret）、攻击者动作形状（输入配方的语法形态）、会话拓扑（副本标记）。中间人、反射、冒充在短轨迹里分不开，需要程序点到角色与身份的映射；KCI、前向安全、post-compromise 三者的输出完全同形，差别纯属场景元数据；观察等价类查询永远不会给出 `is false`。

VerdictBench 语料 106 个协议 1247 个格，616 个 false，其中只有 32 个（5.2%）被标注为已知攻击。616 个 false 的成因四分：削弱假设导致 367、基线就 false 148、削弱前已 false 的重复格 88、无基线对照 13。而 148 个基线 false 里有 60 个属于「协议的运行前提被置为最弱档」，不宜计为协议缺陷。

## 1. 方法与核实口径

本文由三路并行调研加本机实测汇总。核实标记：

- ✅ 取得原文（PDF / PostScript / 扫描本全文检索）并逐字比对。
- ⚠️ 只取得二手转述，转述者已注明。
- **未核实** 未能取得来源，单列于附录 B。

本机实测部分（第 9、11 章）全部可复现：ProVerif 2.05 位于 `/Users/fy222/Documents/lab/aiformal/proverif/proverif2.05/proverif`，实验输入输出在临时目录，语料与本地 run 路径见各节。

两处对常见说法的纠正，先行列出：

- **Bhargavan et al. (S&P 2016) 里没有 downgrade 分类表。** 全文只有 Figure 1–14，零张 Table。流传的「按被降级对象分类」一半来自 Wagner & Schneier (1996)，一半来自 Alashwali & Rasmussen (2018)。
- **Diffie–van Oorschot–Wiener (1992) 的 misbinding 攻击不是打在 STS-MAC 上的。** 打 STS-MAC 的是 Blake-Wilson & Menezes (1999)。DvOW 打的是「签名不用会话密钥加密」的变体。

## 2. 手法分类学（1994–2003）

### 2.1 Carlsen 1994

> Ulf Carlsen. Cryptographic protocol flaws: know your enemy. CSFW-7, Franconia NH, 1994-06-14/16, pp. 192–200. IEEE CS Press. DOI 10.1109/CSFW.1994.315934.

**原文未核实**：Unpaywall 返回 `"is_oa": false, "oa_status": "closed", "has_repository_copy": false`。archive.org、Open Library、CORE、CiteSeerX 均无副本。以下分类全部是二手转述。

✅ 摘要逐字（IEEE 摘要经 OpenAlex 索引）：

> "Flaws are introduced at every stage of the protocol development cycle. … The first step is to gain an understanding of the different flavours of cryptographic protocol flaws, i.e. get to know the enemy. This paper provides a classification of protocol flaws, including two new flaws in an application of the mental poker protocol, and discusses appropriate countermeasures for relevant flaw-categories."

✅ 当场会议纪要（SRI CSL，1994）独立确认了三个小节标题：

> "Ulf Carlsen (Telecom Bretagne, France) on 'Cryptographic Protocols Flaws' where flaws in protocol design were grouped (e.g., under the headings of **elementary flaws, oracle flaws, and type flaws**) and counter-measures discussed."

⚠️ 七类的完整重建来自 Clark & Jacob 1997 注释书目条目 [31]（pp. 80–82），用词是 Clark & Jacob 的：

| # | 类别 | 转述定义 | 协议例子 |
|---|---|---|---|
| 1 | Elementary flaws | 只提供边际保护的协议，例如明文传口令，或 Nessett 对 BAN 的反例 | Nessett 反例、CCITT X.509 |
| 2 | Password guessing flaws | 口令用于生成密钥，实际取值空间允许有偏的暴力搜索 | — |
| 3 | Freshness flaws（原文误拼 "Freshless"） | 某一方无法判断消息是不是新近产生的 | Denning–Sacco 对 NSSK 的攻击、Andrew Secure RPC |
| 4 | Oracle flaws | 某一方无意中充当了攻击者的解密代理。分 single-role 与 multi-role | RSA 三遍协议（mental poker） |
| 5 | Type flaws | **oracle flaws 的子类**：除了把协议片段当预言机，还利用至少一方无法把一个词与特定协议的特定状态关联起来。可混淆的"类型"有五种：cryptographic protocol / protocol run / transmission step / message (sub) components / primitive types | Neuman–Stubblebine、Otway–Rees |
| 6 | Internal flaws | 某一方没有正确执行必需的内部动作（例如漏做检查） | 三遍协议第 3 步 |
| 7 | Cryptosystem related flaws | 协议与所用密码方法交互产生 | — |

**这是全部文献里唯一把 type flaw 明确定为 oracle flaw 子类的一家**，与 Clark & Jacob 把两者并列直接冲突。

⚠️ Carlsen 另有一套正交的三分法，按缺陷来源（Gritzalis & Spinellis §1 转述，其 [1] = Carlsen CSFW'94，[2] = Carlsen ACSAC'93）：

> "**functional specification flaws** occur due to a logical flaw in the protocol's high level specification, **implementation-dependent flaws** appear when a protocol's specification can result in implementations of which at least one exhibits the flaw and at least one other does not, and **implementation flaws**, are those faults that occur when a correct specification is incorrectly implemented."

**重要纠错。** 网上流传的这句——"Carlsen divides possible flaws … into elementary protocol flaws, password/key guessing flaws, stale message flaws, parallel session flaws, internal protocol flaws, and cryptosystem flaws"——✅ 经核对，真正出处是 Gritzalis & Spinellis 论文摘要里讲他们**自己**的分类：

> "In this paper **we divide** possible flaws based on the flaw pathology and the corresponding attack method, into …"

"stale message flaws" 是 Gritzalis & Spinellis 的用词；Carlsen 的对应类别按 Clark & Jacob 叫 freshness flaws。"parasite flaws" 一词与 Carlsen 相关的任何来源中都未找到证据。

同场 CSFW VII 上，紧挨着 Carlsen 之前的是 Syverson 的重放分类学（pp. 187–191）——两份 taxonomy 同场发表。

### 2.2 Syverson 1994

> Paul Syverson. A Taxonomy of Replay Attacks. CSFW-7, 1994, pp. 187–191. DOI 10.1109/CSFW.1994.315935.

**原文未核实**（DTIC 403，IEEE 付费墙）。页码注意：Clark & Jacob 的书目条目写作 pp. 131–136，IEEE DOI 记录与 Gritzalis & Spinellis 的参考表都是 pp. 187–191，后者是对的。

⚠️ 结构由三处独立来源一致印证（Clark & Jacob 1997 [108]、Gritzalis & Spinellis 1997、Toorani 2016）。Clark & Jacob 的逐字转述：

> "This paper presents a taxonomy of replay attacks; or rather, **two taxonomies**: an origination taxonomy (based on the protocol run of origin of replayed message) and a destination taxonomy (based on the recipient of the replayed message relative to its intended recipient). Origination splits replays into **run-external** attacks … and **run-internal** … Run-external attacks are further divided into **interleavings** (requiring contemporaneous protocol runs) and **classic replays** (not necessarily requiring contemporaneous runs). Within the origination taxonomy can be placed the destination taxonomy: **deflections** (message is sent either to a sender —a **reflection**— or to a third party) and **straight replays** (intended recipient receives the message but it is delayed)."

**这是 3×3 叉乘，不是树**：origination 三个叶子 × destination 三个叶子 = 9 格，destination 子树在每个 origination 叶子下原样重复。

作者自己的两条限定（同一转述）：

> "The taxonomy actually applies to **message fragments** rather than messages. **In practice it may be necessary to use more than one type of replay to mount a successful attack.**"

### 2.3 Clark & Jacob 1997

> John Clark and Jeremy Jacob. A Survey of Authentication Protocol Literature: Version 1.0. University of York, 1997-11-17. 第 4 章 "Attacking Authentication protocols", pp. 23–36. ✅ 原文已读。

| 节 | 类名 | 原文定义 |
|---|---|---|
| 4.1 | Freshness Attacks | "A freshness attack occurs when a message (or message component) from a previous run of a protocol is recorded by an intruder and replayed as a message component in the current run of the protocol." |
| 4.2 | Type Flaws | "A type flaw arises when the recipient of a message accepts that message as valid but imposes a different interpretation on the bit sequence than the principal who created it." |
| 4.3 | Parallel Session Attacks | "A parallel session attack occurs when two or more protocol runs are executed concurrently and messages from one are used to form messages in another." |
| 4.3 内嵌 | oracle attacks | "A is said to act as an oracle (because he always provides the correct answer) and attacks of this form are often called oracle attacks." |
| 4.4 | Implementation Dependent Attacks | "…the implementation approach adopted may severely affect the actual security of a protocol that conforms to the description and implementation-dependent attacks are possible." |
| 4.5 | Binding Attacks | "there must be a verifiable binding between a public key and the corresponding agent. In some authentication protocols, this has not been achieved." |
| 4.6 | Encapsulation Attacks | "In a great many protocols a principal A may arrange for a second principal B to encrypt some data chosen by A. As a rule such data should be regarded as 'user data' …" |
| 4.7 | Other Forms of Attack | 兜底节：cryptanalysis、timing、代数性质攻击、Carlsen 的 elementary flaws |

✅ 值得注意：全书正文里 **"man-in-the-middle" 与 "interleaving" 一次都没出现**（对 4.1–4.8 正文 grep 确认）。Lowe 1996 的 NSPK 攻击在参考文献 [75] 里，但没有对应类目。

作者自承类目边界任意（§4.7，谈 Carlsen 的 elementary flaws）：

> "**It is a matter of opinion as to when a flaw is considered elementary and the choice is somewhat arbitrary.**"

对 Syverson 论文的评语（书目 [108]）：

> "The paper is worth a read. **There is little startling but that is the way with taxonomies.**"

### 2.4 Gritzalis & Spinellis 1997

> S. Gritzalis and D. Spinellis. Cryptographic Protocols over Open Distributed Systems: A Taxonomy of Flaws and related Protocol Analysis Tools. SAFECOMP '97, Springer, pp. 123–137. ✅ 原文已读。

自述依据："we propose the following more detailed taxonomy of these flaws based on **the flaw pathology and the corresponding attack method**"。

六大类两层：

1. Elementary protocol flaws
2. Password/key guessing flaws — 三子类：detectable on-line / undetectable on-line / off-line
3. Stale message flaws — 3.1 Message origin attacks（run external / run internal）、3.2 Message destination attacks（reflection / straight replay / deflection）
4. Parallel session flaws — 4.1 Single role / 4.2 Multi-role
5. Internal protocol flaws
6. Cryptosystem flaws

**这家把 Syverson 的整个二维分类学原样塞进了自己第 3 类的第二层**，是「一套分类学被当作另一套的子节点」的直接证据。它还把 Carlsen 的 oracle flaws 改了名：§2.4 开头是 "Parallel session attacks (or oracle session attacks, multi-role flaws) …"。

### 2.5 Boyd & Mathuria 2003 / 2020

> Colin Boyd and Anish Mathuria. Protocols for Authentication and Key Establishment. Springer, 2003. 第 2 版 2020，加 Douglas Stebila。

✅ 目录经德国国家图书馆印刷本扫描件两次独立逐字核实。第 1 版 §1.6 "Types of Attack on Protocols"（p. 23），十个小节：

| § | 类名 | 页 |
|---|---|---|
| 1.6.1 | Eavesdropping | 24 |
| 1.6.2 | Modification | 25 |
| 1.6.3 | Replay | 25 |
| 1.6.4 | Preplay | 25 |
| 1.6.5 | Reflection | 25 |
| 1.6.6 | Denial of Service | 27 |
| 1.6.7 | Typing Attacks | 28 |
| 1.6.8 | Cryptanalysis | 29 |
| 1.6.9 | Certificate Manipulation | 30 |
| 1.6.10 | Protocol Interaction | 31 |

✅ Table 1.3 "Types of protocol attack"（p. 24）十条逐字定义，经 Internet Archive 藏本 `protocolsforauth0000boyd` 全文检索、十条首尾相接互相重叠的查询连成链逐字验证：

| Attack type | Definition |
|---|---|
| Eavesdropping | "The adversary captures the information sent in the protocol." |
| Modification | "The adversary alters the information sent in the protocol." |
| Replay | "The adversary records information seen in the protocol and then sends it to the same, or a different, principal, possibly during a later protocol run." |
| Preplay | "The adversary engages in a run of the protocol prior to a run by the legitimate principals." |
| Reflection | "The adversary sends protocol messages back to the principal who sent them." |
| Denial of Service | "The adversary prevents or hinders legitimate principals from completing the protocol." |
| Typing Attacks | "The adversary replaces a (normally encrypted) protocol message field of one type with a (normally encrypted) message field of another type." |
| Cryptanalysis | "The adversary gains some useful leverage from the protocol to help in cryptanalysis." |
| Certificate Manipulation | "The adversary chooses or modifies certificate information to attack one or more protocol runs." |
| Protocol Interaction | "The adversary chooses a new protocol to interact with a known protocol." |

⚠️ 源是扫描本 OCR，只修复了四处显然的 OCR 错误（跨行连字符三处，以及 Replay 末尾 `protocol Tun.` → `protocol run.`）。最后这处是全表证据最弱的一个词。

✅ §1.6 引言里两句关键的话：

> "It should be noted that there are other ways to classify attacks; an alternative list, with examples, is given by Carlsen [83]."

> "Before doing so we should sound a couple of notes of caution. Firstly, for many protocols the list will not be complete."

**第 2 版的框架转向。** ✅ 经第 2 版印刷本目录扫描件逐字读出：

```
1.4 Adversary Capabilities .............................   14
    1.4.1 Eavesdropping      15     1.4.6 Denial of Service        17
    1.4.2 Modification       15     1.4.7 Typing Attacks           18
    1.4.3 Replay             16     1.4.8 Cryptanalysis            20
    1.4.4 Preplay            16     1.4.9 Certificate Manipulation 20
    1.4.5 Reflection         16     1.4.10 Protocol Interaction    22
1.5 Goals for Authentication and Key Establishment .....   22
```

**节标题从 "Types of Attack on Protocols" 改成 "Adversary Capabilities"，位置从 §1.6 移到 §1.4，十个条目的名称、数量、顺序完全不变。** 同一批东西，第 1 版叫攻击类型，第 2 版叫对手能力。第 2 版对应汇总表的表号与定义有无改动 **未核实**（Springer 付费墙），引用时不要假设仍是 Table 1.3。

另一处结构事实：这本书把攻击和目标分在两处。第 1 版攻击在 Ch.1 §1.6，目标独立成 Chapter 2，其中 §2.4 "Goals Concerning Compromised Keys" 下是 §2.4.1 Forward Secrecy、§2.4.2 Key Compromise Impersonation。**KCI 与前向保密在这本书里不是攻击类型，是目标。** 全文检索 `"goals of the adversary"` / `"adversary capabilities"` 在第 1 版 0 命中，独立的「对手目标」清单 **未核实（倾向于不存在）**。

### 2.6 Toorani 2016

> M. Toorani. Security Protocols in a Nutshell. arXiv:1605.09771. ✅ 原文已读。

自承不完备（§2.1）：

> "In this section, we present a **non-exhaustive** list of standard attacks on protocols. … **The list is incomplete because there are unlimited ways for an adversary to interact with one or more (e.g. parallel) protocol executions.** … **Security against a list of attacks does not guarantee the security of a protocol.**"

同一篇里，平级条目之间公开重叠：

- MITM：*"It is a variant of the impersonation attack"*
- UKS：*"It is a variant of the impersonation attack in AKE protocols"*
- Reflection：*"a special case of the replay attack, may be considered as an oracle attack"*
- Replay：*"It can be considered as a combination of eavesdropping and modification attacks"*

该文也确认了 chosen protocol attack 与 multi-protocol attack 的同一性：

> "This attack is sometimes referred to as the **multi-protocol attack**."

## 3. 维度化转向（2001–2018）

### 3.1 Basin & Cremers 2014

> David Basin and Cas Cremers. Know Your Enemy: Compromising Adversaries in Protocol Analysis. ACM TISSEC 17(2), 2014. ✅ 原文已读。

出发点的批评（§2.2）：

> "Security models such as the eCK model are **complex, monolithic definitions that are hard to disentangle** … in general, **any two computational models are incomparable** due to (often minor) differences not only in the adversary notions, but also in the definition of matching threads, the execution models, and security property specifics."

> "our aim is to **factor and generalize** the adversarial capabilities given by AKE models."

三个维度（§3.5 逐字）：

> "They factor the security definitions from the cryptographic protocol literature along **three dimensions of adversarial compromise: which kind of data is compromised, whose data it is, and when the compromise occurs**."

七条规则分两组。长期密钥组（维度：谁的 × 何时）：

| 规则 | 语义 |
|---|---|
| `LKRothers` | 学到任何非 test 线程预期伙伴的长期密钥。"the adversary capability used in the symbolic analysis of security protocols since Lowe's man-in-the-middle attack on the Needham-Schroeder protocol" |
| `LKRactor` | 学到执行 test 线程者本人的长期密钥。"This rule allows the adversary to attempt so-called Key Compromise Impersonation attacks" |
| `LKRafter` | 只允许在 test 线程结束后泄露 → 满足即为 PFS |
| `LKRaftercorrect` | 额外要求存在已完成的伙伴线程 → 满足即为 wPFS |

短期数据组（维度：谁的 × 哪类数据）：

> "We differentiate between **three kinds of local data: randomness, session keys, and other local data** such as the results of intermediate computations."

`RNR`（random number reveal，源自 eCK）、`SKR`（session-key reveal，源自 BR93）、`SR`（state reveal，源自 CK2001）。

> "Because we assume that local data does not exist before or after a session, **we can ignore the temporal dimension**."

模型数量：

> "The rules in Figure 4 give rise to **2⁵ × 3 = 96 models** with distinct sets of reachable states."

**Table I「Decomposing security properties」是整篇最关键的一处**：

| Security property | Basic property | Adversary model |
|---|---|---|
| Perfect Forward Secrecy | Secrecy | `{LKRafter}` |
| Weak Perfect Forward Secrecy | Secrecy | `{LKRaftercorrect}` |
| Known-Key Security & Unknown-Key Share | Secrecy of session key | `{SKR}` |
| Key Compromise Impersonation | Authentication/Secrecy of sess. key | `{LKRactor}` |

四行里基本性质栏只有两个不同的值，真正区分它们的是敌手模型栏。历来被当作「攻击类型」的名字，在这里是「目标 × 假设」空间里被历史命名过的若干个点。

Table II 把文献里的整套模型摊平到同一组规则上（`Adv_EXT`、`Adv_INT`、`Adv_CA`、`Adv_AFC`、`Adv_AF`、`Adv_BR93`、`Adv_BR95`、`Adv_BPR00`、`Adv_CKw`、`Adv_CK`、`Adv_eCK-1`、`Adv_eCK-2`）。Table III 是 21 个协议 × 10 个敌手模型的攻击矩阵，**没有「攻击类型」这一列**——一个发现的全部身份就是它出现在哪个敌手模型下。Lowe 的 NSPK 攻击在这套语言里是「NS 在加入 `LKRothers` 后被证伪」。

一个尖锐的案例（§5.3）：HMQV 在 `Adv_CKw` 下是否安全，完全取决于 "local state" 被定义成什么。

> "This example shows how analysis with respect to our models can help **sharpen protocol implementation requirements**."

相关的模型不可比结论另见 Cremers (AsiaCCS 2011)：

> "We show first that the CK, CK-HMQV, and eCK security models are **formally incomparable**. Second, we show that these models are also **practically incomparable** … Third, our analysis enables us to find **previously unreported flaws in protocol security proofs** from the literature."

不可比的根源不在攻击手法，而在 partnering / matching sessions 的定义差异。

### 3.2 Alashwali & Rasmussen 2018

> E. Alashwali and K. Rasmussen. What's in a Downgrade? A Taxonomy of Downgrade Attacks in the TLS Protocol and Application Protocols Using TLS. SecureComm 2018. arXiv:1809.05681. ✅ 原文已读。

自称 "first taxonomy of TLS downgrade attacks"，四根轴、每轴一个问句：

> "four vectors: **element** (to answer: What has been downgraded?), **vulnerability** and **method** (to answer: How is it downgraded?), and **damage** (to answer: What is the impact of the downgrade?)."

- Element：Algorithm / Version / Layer
- Vulnerability：Implementation / Design / Trust-Model
- Method：Modification / Dropping / Injection
- Damage：Broken Security / Weakened Security

15 个真实攻击的映射（两份 PDF 独立复现一致）：

| # | Attack | Element | Vulnerability | Method | Damage |
|---|---|---|---|---|---|
| 01 | SSL 2.0 Ciphersuite rollback | Algorithm | Design | Modification | Broken |
| 02 | SSL 3.0 Version rollback | Version | Design | Modification | Broken |
| 03 | SSL 3.0 key-exchange rollback | Algorithm | Design | Modification | Broken |
| 04 | DHE key-exchange rollback (Mavrogiannopoulos) | Algorithm | Design | Modification | Broken |
| 05 | SLOTH | Version | Design | Modification | Broken |
| 06 | POODLE version downgrade | Version | Implementation | Dropping | Broken |
| 07 | FREAK | Algorithm | Implementation | Modification | Broken |
| 08 | DROWN | Algorithm | Trust-model | Modification | Broken |
| 09 | Forward Secrecy rollback | Algorithm | Implementation | Dropping | Weakened |
| 10 | Logjam | Algorithm | Design | Modification | Broken |
| 11 | SMTPS to SMTP | Layer | Design | Modification | Broken |
| 12 | Proxied HTTPS | Layer | Trust-model | Injection | Broken |
| 13 | TLS 1.3 Version rollback | Version | Design | Modification | Broken |
| 14 | TLS 1.3 Downgrade-dance fallback | Version | Implementation | Dropping | Broken |
| 15 | TLS 1.3 HelloRetry downgrade | Algorithm | Design | Injection | Weakened |

DROWN 被归到 trust-model 而非 design/implementation：

> "Sharing RSA keys among servers is a **trust-model vulnerability** that allows the key sharing, **rather than a protocol design nor implementation**."

**这是文献里唯一显式把「成因」与「后果」分成不同轴的分类学。** 在只有单一手法轴的分类学里（Clark-Jacob、Boyd-Mathuria），DROWN 无处安放。

## 4. 三条专题线

### 4.1 type flaw 的定义之争

**根**：Thayer Fábrega, Herzog, Guttman, Strand Spaces, JCS 7(2,3), 1999, §2.4 "Freeness Assumptions", pp. 10–11。✅ 原文已读。他们把 "type flaw attack" 一词的出处归给 Carlsen：

> "Attacks that might exist if there are terms that may be 'read' as having more than one form are referred to as **type flaw attacks [4]**. Some type flaw attacks seem implausible—in the sense that most implementations would not be vulnerable to them—while others are more troublesome."

（其 [4] = Carlsen CSFW 1994。**这是 Carlsen 与 type flaw 文献之间唯一一条可直引的、经核实的连线**，且这个定义比后来的都宽。）

同文两条公理：Axiom 1（free encryption）`{m}_K = {m′}_{K′} ⟹ m = m′ ∧ K = K′`；Axiom 2.1（串接唯一可分解）`m₀ m₁ = m₀′ m₁′ ⟹ m₀ = m₀′ ∧ m₁ = m₁′`。作者自承这只是单向保守的：

> "if a protocol property fails for strands over A₀, then the same protocol property fails for A. However, the converse is not true… The problem remains to determine which relations among the elements of the free algebra A₀ will preserve a protocol correctness result. This is a hard problem, which will doubtless require much future work"

**Heather, Lowe, Schneider 2000/2003**（CSFW 13, pp. 255–268；JCS 11(2), 2003）。✅ 原文已读（作者自存预印本）。

> "A type flaw attack on a security protocol is an attack where a field that was originally intended to have one type is subsequently interpreted as having another type."

（注意："…is one in which a field that…" 是 Meadows 的句式，两者极易混。）

标签文法 `Tag ::= agent | nonce | public | ... | pair | enc Tag* Tag` —— `pair` 与 `enc` 本身是 tag。**他们自己的引导例子就是「二元组冒充单字段」**（JCS 预印本 p. 2，NSPK 改造版）：

> "This is the first message A receives, and so A interprets it as the start of a new protocol run, taking the field (Nb, B) to be an agent's identity, and so believes this message came from (Nb, B)."

真正的边界在这条假设上（p. 2）：

> "we assume that the tag for a pair contains enough information to allow an honest agent to decompose the message correctly (for example, the tag might contain a representation of the number of bits in each component)."

**这一句用公理排除了「比特串重新切分」这一类攻击**，它是 HLS 与后来批评者的分水岭，也正是 Strand Spaces 的 Axiom 2.1 的对应物。

他们自己声明的唯一局限（§4.1，"that have distinct tags" 原文斜体）：

> "The central theorem guarantees that using the tagging scheme will prevent attacks that rely on type confusion between two types *that have distinct tags*. Different tagging schemes distinguish different types, resulting in different guarantees about what type flaw attacks will be prevented."

✅ 对两版全文 grep contentious / debate / disagree / controvers / arguable / "some authors" **零命中**：**「HLS 承认其定义有争议」的说法不成立**。能写的是"HLS 明确指出其保证相对于所选标签方案而定"。

**Meadows, FCS'02**（Identifying Potential Type Confusion in Authenticated Messages, pp. 75–84）。✅ 原文已读。

> "A type confusion attack is one in which a principal accepts data of one type as data of another."

三层分级（§1）：

> "The most simple type confusion attacks are ones in which fields of one type are confused with fields of another type … but it is also possible to imagine attacks in which fields of one type are confused with a concatenation of fields of another type … or even attacks in which pieces of fields of one type are confused with pieces of fields of other types."

对 HLS 的批评，以及那条几乎无人引用的脚注 1：

> "…it is not been shown [sic] that this technique will work for more complex type confusion attacks, in which tags may be confused with data, and terms or pieces of terms of one type may be confused with concatenations of terms of several other types.¹"
>
> 脚注 1："We believe that it could, however, if the type tags were augmented with tags giving the length of the tagged field, as is done in many implementations of cryptographic protocols."

**Meadows 自己承认：标签带上长度信息，HLS 的技术就够了。而 HLS §1 恰恰已经明文假设 pair 标签含长度信息。** 这场"分歧"相当程度上是读法之争。

她的形式化定义（§3, Definition 3.9）判据是**比特串相等**且两个序列长度可以不同；HLS 的判据是**项结构上的标签匹配**。**Meadows 在比特层，HLS 在项代数层——这才是两套定义分开的地方，不是"原子 vs 复合"。**

**Gao, Bodei, Degano, AMAST 2008**（A Formal Analysis of Complex Type Flaw Attacks on Security Protocols, LNCS, pp. 167–183）。✅ 原文已读。（**纠正**：该文作者不是 Malladi。）

> "We say that a complex type confusion attack happens when a concatenation of fields in a message is interpreted as a single field."

⚠️ 但他们所谓的 complex type flaw 正是 HLS 自己的 NSPK 引导例子（见上）。**"HLS 只管 simple、不覆盖 complex"这个划界与 HLS 原文不符**，引用时不要跟着这么说。他们真正的贡献是在 LySa 进程演算里把这件事建模出来。

**Malladi & Lafourcade**（arXiv:1003.5385）不属于这场定义之争：两份全文 grep "simple/complex type flaw attack" 零命中。他对 HLS 的限定是**代数性质**，不是类型边界：

> "Heather et al.'s work only considered a basic protocol model with a free message algebra and perfect encryption. Operators such as Exclusive-OR and ciphers such as CBC possess algebraic properties that violate these assumptions."

**Snekkenes 1992**（Roles in cryptographic protocols, IEEE S&P 1992, pp. 105–119）主题是 **multirole flaw**，不是类型混淆；它早于 HLS 八年，不可能是对 HLS 的批评。Meadows 把"单字段与串接相混淆"归功于 Snekkenes，但该文正文 **未核实**。该文也是 Carlsen 1994 的参考文献之一，这解释了 Carlsen 的 oracle flaws 为什么分 single-role / multi-role。

### 4.2 misbinding / UKS / KCI

**Diffie, van Oorschot, Wiener 1992**（Designs, Codes and Cryptography 2(2):107–125, §5.1 "Removing encryption on signatures"）。✅ 原文已读。

> "Suppose that in the last message of the protocol, an enemy Eve substitutes her own signature on the exponentials for Alice's signature. … This may not seem like a serious attack, as **Eve does not know the exchanged key**. However, if Bob were a bank, Eve could get credit for a deposit Alice might make. Interestingly, **even though Bob has been misled here, Alice is the party who may be hurt**."

判据是 Definition 1 第二条："The exchanged key accepted by Alice is known to someone other than the party whose identity Alice accepted."

**原文没有给这个攻击命名。** 命名链条：HAC 1996 §12.54 叫 source-substitution attack；Blake-Wilson 等 1997/1999 叫 unknown key-share；Krawczyk SIGMA 2003 命名为 identity misbinding。

**Krawczyk, SIGMA (CRYPTO 2003)**：

> "We will refer to this attack against the consistency requirement of KE protocols as an **identity misbinding attack**. … **Avoiding this form of attack and guaranteeing a consistent binding between a session key and the peers to the session is a central element in the design of SIGMA.**"

> "Note that this attack **does not result in a breach of secrecy of the key** … but it does result in a severe breach of authenticity."

修法的方向性判据（§3.3）："the essential binding here needs to be done between the signature and the **recipient's identity** (the ISO protocol) or between the DH key and the **sender's identity** (the SIGMA protocol)."

**Blake-Wilson & Menezes, PKC '99**（Unknown Key-Share Attacks on the STS Protocol）。✅ 原文已读。

> "An unknown key-share (UKS) attack on a key agreement protocol is an attack whereby an entity A ends up believing she shares a key with B, and although this is in fact the case, B mistakenly believes the key is instead shared with an entity E ≠ A."

> "if an AK or AKC protocol succumbs to a UKS attack in which E is a dishonest entity …, then this **does not contradict the implicit key authentication property** of the protocol."

三类 UKS 都走证书注册通道，真正的轴是 CA 在注册时检查了什么：

| 类 | 攻击者做什么 | 被什么防住 |
|---|---|---|
| public key substitution | 把 A 的公钥注册成自己的 | proof of possession |
| on-line DSKS（该文新贡献） | 看到 `sA` 后现算 `(PE,SE)` 使 `sA` 也是 E 的合法签名，当场向在线 CA 注册 | proof of possession 防不住；须把身份与流水号签进消息 |
| off-line 无效公钥 | 注册 `PE=(p,0,0)` 这类未验证 ElGamal 公钥 | public-key validation |

> "possession of the duplicate-signature key selection property **does not constitute a weakness of the signature scheme**."

**KCI**，术语出自 Blake-Wilson, Johnson, Menezes 1997：

> "**key-compromise impersonation.** Suppose i's secret value is disclosed. Clearly an adversary that knows this value can now impersonate i … **However, it may be desirable that this loss does not enable an adversary to impersonate other entities to i.**"

Krawczyk HMQV (CRYPTO 2005) 的框架用词是 "reverse impersonation"；eCK (LaMacchia et al. 2007) 最简版："the adversary reveals a long-term secret key of a party and then impersonates others to this party."

**边界**：Krawczyk HMQV Definition 20 的形式化只谈谁被腐化、哪些会话 clean，**完全不描述任何消息行为**。在 eCK 里 KCI 甚至不是一条独立性质，只是 freshness 没有禁止 `Long-Term Key Reveal(A)` 单独出现的副产品。

**UKS 与 misbinding 是同一现象的两个名字**（非子类关系）。Krawczyk HMQV §3.2：

> "An unknown-key share (UKS) attack (**also known by the more informative terms 'source-substitution' or 'identity misbinding' attacks**) is a particular form of impersonation attack … This attack, first discovered by Diffie, van Oorschot and Wiener, has since become a basic attack under which key-exchange protocols are validated."

### 4.3 cross-protocol / multi-protocol / chosen-protocol

**Kelsey, Schneier, Wagner 1997**（Protocol Interactions and the Chosen Protocol Attack, Security Protocols Workshop）。✅ 原文已读。

> "Let P and Q be two different protocols, both of which use the same key material, but which do different things. These protocols are said to **interact** whenever some information derived from P allows an attacker to successfully mount some attack on Q."

> "The '**chosen-protocol attack**' is an attack in which some attacker convinces one or more intended victims to accept and start using a new, tailor-made protocol …"

**单协议攻击是协议交互的退化情形**（§2，这是全线最有力的一句）：

> "When P = Q, the possible protocol interactions reduce to a subset of possible attacks on the protocol. A replay attack (replaying messages from one instance of a protocol to attack another instance of the same protocol) is an example of an interaction between a protocol and itself, as is a standard man-in-the-middle attack."

他们自己的定位（§7）："The chosen-protocol attack resonates with a fairly common theme in security: security does not necessarily compose."

**Cremers, ARES 2006** 给出唯一的形式化定义，且是极小性定义：

> "**Definition 1** A Multi-Protocol Attack is a tuple (ps, c) … iff: |ps| > 1 ∧ attack(ps, c) ∧ ∀ps′ ⊂ ps : ¬attack(ps′, c)"

**三个名字是同一件事**，Bergsma, Dowling, Kohlar, Schwenk, Stebila (CCS 2014) 直接陈述：

> "re-use or sharing of keys across multiple primitives or protocols can potentially be insecure; this is **variously called a chosen protocol attack, cross-protocol attack, or multi-protocol attack**."

文献里唯一的显式细分（Jager, Schwenk, Somorovsky, CCS 2015），轴是「跨越哪层边界」：cross-ciphersuite → cross-ciphersuite-family → cross-protocol-version → cross-protocol。

**术语在文献内部冲突**：Mavrogiannopoulos 2012 自称 "cross-protocol" 指跨密钥交换方法（同协议内）；DROWN 与 Bergsma 把同一类攻击改叫 "cross-cipher suite attack"；Bhargavan et al. 2016 用 "cross-protocol" 指同协议内跨模式。而 Alashwali & Rasmussen 的表里，Mavrogiannopoulos 那条（#04）被归为 downgrade——**同一个攻击，两套体系、两个名字、两个位置**。

**组合性这条线把它定位成范围问题，不是新手法。** Cremers 2004/2006 的 "closed world" 论述：

> "the formal models assume what we call a closed world. This means that the agents in the system do not exhibit any other behaviour than is specified in the protocol."
> "This closed world assumption does not hold for most applications."
> "we set out to **enlarge this closed world**, and improve the scalability of the existing formal methods."

Guttman & Thayer (CSFW 2000) 定义的不是攻击，而是独立性：

> "One protocol (called the primary protocol) is **independent** of other protocols … **if the question whether the primary protocol achieves a security goal never depends on whether the secondary protocol is in use**."

Andova, Cremers, Gjøsteen, Mauw, Mjølsnes, Radomirović (Inf. & Comp. 2008) 那篇 57 页的论文里，"multi-protocol attack" 一词**只出现在参考文献中，正文一次都没用**。

ALPACA (USENIX Security 2021) 的措辞：

> "**each component (browser, web server, and application server) functions as expected and the security violation is an emergent property due to the attacker's ability to recombine the components in an unintended way.**"

Lowe 1997 自己也是这么框的："This raises the question of interaction between protocols … **In this paper we mainly restrict our attention to systems running a single protocol**"。

### 4.4 downgrade

**Wagner & Schneier, Analysis of the SSL 3.0 Protocol, USENIX EC 1996** —— 真正的「按被降级对象」三分源自这里，三个小节标题即 Ciphersuite rollback attacks / Key-exchange algorithm rollback / Version rollback attacks。

**Bhargavan, Brzuska, Fournet, Green, Kohlweiss, Zanella-Béguelin, Downgrade Resilience in Key-Exchange Protocols, IEEE S&P 2016** —— ✅ 无分类表，只有形式化定义：

> "**Definition 6 (Negotiation correctness):** The protocol negotiation is correct if, whenever a session π … completes, there exists a peer configuration cfg_r̄ such that π.mode = Nego_r(cfg_r, cfg_r̄)."

> "**Definition 7 (Downgrade security):** A session π is **downgraded** when π.complete = true and there is a partnered session π′ such that DP(π.cfg, π′.cfg) holds, but **π.mode ≠ Nego_{π.role}(π.cfg, π′.cfg)**."

其中 `Nego` 是"无主动攻击者时会协商出什么"。他们划定的可证边界：

> "downgrade security concerns situations in which one participant can save the other, even if the latter supports broken cryptography. … **Conversely, if both participants enable (among others) a mode that is entirely insecure, then there is no cryptographically sound way to prevent an attacker from downgrading their connection.**"

实现错误破坏的是 Definition 6 而非 7："**the FREAK attack stems from TLS clients that do not offer export ciphersuites but still accept export-grade RSA keys**."

值得对照的是 AVISPA 把降级写成了**目标**：G11 "Secure capabilities negotiation (Resistance against Downgrading and Negotiation Attacks)"（见 §7.2）。

## 5. 横向对照

### 5.1 类目对齐

| 概念 | Clark & Jacob 1997 | Carlsen 1994 | Gritzalis & Spinellis 1997 | Syverson 1994 | Boyd & Mathuria 2003 | Toorani 2016 | Basin & Cremers 2014 |
|---|---|---|---|---|---|---|---|
| 重放旧消息 | Freshness Attacks | Freshness flaws | Stale message flaws | 整篇的论域 | Replay (1.6.3) | Replay | 表为 `{SKR}` 等 |
| 消息来源/去向细分 | 无 | 无 | §3.1 / §3.2（直接借 Syverson） | origination × destination (3×3) | Reflection (1.6.5) 单列 | Reflection = replay 的特例 | 无 |
| 并发会话 | Parallel Session Attacks | 含在 oracle flaws 的 multi-role | Parallel session flaws | interleavings（origination 一档） | 无 | 无 | 无 |
| 借受害者做运算 | oracle（内嵌于 parallel session） | Oracle flaws（顶层类） | 吸收进 parallel session | 无 | 无 | 视为 oracle attack | 无 |
| 类型混淆 | Type Flaws（顶层，与 oracle 并列） | Type flaws（oracle 的子类） | 无 | 无 | Typing Attacks (1.6.7) | Type flaw attacks | 无 |
| 实现/密码学交互 | Implementation Dependent | Cryptosystem related flaws | Cryptosystem flaws | 无 | Cryptanalysis (1.6.8) | Cryptanalysis | 无 |
| 漏做检查 | 无 | Internal flaws | Internal protocol flaws | 无 | 无 | Internal action flaws | 无 |
| 公钥/身份绑定 | Binding Attacks | 无 | 无 | 无 | Certificate Manipulation | UKS | Table I: `{SKR}` |
| 协议间交互 | 无 | 无 | 无 | 无 | Protocol Interaction (1.6.10) | Chosen protocol attack | 无（属组合性文献） |
| 口令猜测 | 4.7 提及 | Password guessing flaws | 三子类 | 无 | 无 | Offline/Online dictionary | 无 |
| 「太弱了」 | 4.7 提及 | Elementary flaws | Elementary protocol flaws | 无 | 无 | 无 | `Adv_EXT` |
| 可用性 | 无 | 无 | 无 | 无 | Denial of Service | DoS | 无 |
| 被动窃听 | 无 | 无 | 无 | 无 | Eavesdropping | Eavesdropping | `Adv_EXT` |
| 长期密钥泄露 | 无 | 无 | 无 | 无 | §2.4 当作目标 | KCI | `{LKRactor}` / `{LKRafter}` |

### 5.2 同一个攻击，四家四个名字

**Lowe 1996 对 NSPK 的攻击**：

| 来源 | 它叫什么 |
|---|---|
| Clark & Jacob 1997 | 没有类目（正文无 MITM / interleaving），最近的是 Binding Attacks |
| Lowe 1997（自己） | weak agreement 不成立（目标层）；机制描述为 "using B as an oracle in a parallel run" |
| Basin & Cremers 2014 | NS 在 `Adv_INT` = `{LKRothers}` 下被证伪（敌手能力层） |
| Toorani 2016 | man-in-the-middle attack，"a variant of the impersonation attack"（手法层） |

**Denning-Sacco 对 NSSK 的攻击**：

| 来源 | 它叫什么 |
|---|---|
| Clark & Jacob 1997 | Freshness attack（手法层） |
| Syverson 1994 | run-external, classic replay, straight replay（消息来源/去向层） |
| Basin & Cremers 2014 | Table I 的 `{SKR}` 行（敌手能力层） |
| SPORE | "Authentication attack by Denning and Sacco" + 内联 `assume that Kab is compromised`（目标层 + 假设） |

### 5.3 结构：单层、两层还是多轴

| 分类学 | 层数 | 第二层按什么分 |
|---|---|---|
| Clark & Jacob 1997 | 基本单层，只有 4.4 有第二层 | 按密码原语/工作模式（流密码 vs CBC），与第一层不同轴 |
| Syverson 1994 | 两层 × 两套，且是叉乘 | origination 按并发要求；destination 按收件人身份。整体 3×3 |
| Carlsen 1994 | 三层 | 顶层按缺陷来源；中层按缺陷病理；type flaws 下按被混淆的类型种类 |
| Gritzalis & Spinellis 1997 | 两层 | 各分支不同：password 按可检测性、stale message 按 Syverson 两轴、parallel session 按角色数 |
| Boyd & Mathuria 2003 | 单层 | — |
| Toorani 2016 | 两层 | 按被攻击的数学对象 |
| Basin & Cremers 2014 | 不是层级，是三个正交维度 | 数据种类 / 谁的数据 / 何时，组合出 96 个模型（格，不是树） |
| Alashwali & Rasmussen 2018 | 不是层级，是四根轴 | element / vulnerability / method / damage，每轴一个问句 |

**明确做两层的三家，第二层的划分依据在不同分支里各不相同。** 真正做到统一维度的两家都放弃了树形结构，改用正交轴——这两家也是全部文献里唯二能对自己的覆盖面做出算术陈述的。

## 6. 已知批评（含作者自承）

1. **类目边界任意**。Clark & Jacob §4.7："It is a matter of opinion as to when a flaw is considered elementary and the choice is somewhat arbitrary."
2. **一个攻击可能同时属于多类**。Syverson 本人："In practice it may be necessary to use more than one type of replay to mount a successful attack."
3. **清单公认不完备**。Toorani §2.1（见 §2.6）；Boyd & Mathuria §1.6："for many protocols the list will not be complete."
4. **类目在同一份清单里公开重叠**。Toorani 的四条 "a variant of" / "a special case of" / "a combination of"（见 §2.6）。
5. **定义边界随工具能力移动**。type flaw 被 tagging 定理与代数性质切了两次；Clark & Jacob 最经典的 Otway-Rees 例子按 2008 年的定义属于另一类（见 §4.1）。
6. **模型互不可比**。Cremers AsiaCCS 2011；Basin & Cremers §6："generally presented in a monolithic way, where all parts are intertwined."
7. **把后果和手法混在一起**。只有 Alashwali & Rasmussen 显式分成 vulnerability（成因）与 damage（后果）两轴；不这样做 DROWN 无处安放。
8. **形式化验证一侧系统性地不使用攻击类词汇**（见 §4.3）。

## 7. 仓库与工具的 schema 实证

### 7.1 SPORE

> Security Protocols Open Repository, LSV。现址 `https://lsv.ens-paris-saclay.fr/Software/spore/`（旧址 302 跳转，HTTP 200）。内容冻结在 2002 年前后（45 个页面里 32 个 last modified 是 2002），索引列 49 个协议条目。

自述："The purpose of this page is to **continue online the seminal work of Clark and Jacob** …"

页面字段：Summary / Protocol specification / Description of the protocol rules / Requirements / References / Claimed proofs / Claimed attacks / See also / Citations。格式规范页对字段的定义：

> "**Requirements**: Some properties that the protocol is supposed to ensure are written here **in natural language**."
> "**Claimed attacks**: This section **cites the works which claim to have demonstrated a vulnerability** of the protocol, **with respect to the requirements cited above**. …"
> "**Important remark: We do not check the correctness of the claims** presented in protocols pages."

**schema 层的硬证据**：SPORE 每页提供 `.tex` 源（文档类 `splib`）。抽 10 份统计全部环境及参数，`\begin{attacks}` 出现 9 次，**全部零参数**；整个文档类里只有 `\begin{protocol}{...}` 与 `\begin{addcomment}{...}` 带参数。**没有任何 attack-type 槽位存在于 schema 中。** 全语料 grep `attack type` / `attack categ` / `classificat` / `taxonom` = 0 命中。

45 页的 section 频次：Protocol specification 45、References 45、Requirements 44、Description 40、See also 35、**Claimed attacks 仅 24**、Remark 13、Claimed proofs 13。

两条"自由散文"的旁证：

- `man-in-the-middle` / `man in the middle` / 单词 `middle` 在整个 SPORE 语料里出现 **0 次**（含 NSPK 页）。NSPK 的攻击段原文是："An intruder `I` may impersonate `A`, by inciting `A` to initiate a second session[Low95]."
- 同一语料里两种拼法并存：denningSacco 页 "This protocol is subject to a **mutiplicity** attack [Low97]."，spliceas3 页 "Lowe [Low97] demonstrate a **multiplicity** attack …"。

同一仓库里两个条目还用了两根不同的轴：NSSK 条目标签是目标味的（"Authentication attack by Denning and Sacco" + 内联 `assume that Kab is compromised`），Otway-Rees 条目标签是手法味的（"Type flaw in [CJ97] …"）。

### 7.2 AVISPA

`avispa-project.org` 已被抢注，原内容只能走 Wayback。库索引页逐字（`classifiation` 是原文拼写错误）：

> "For each protocol, we describe its purpose, the message exchange in the Alice&Bob-style notation, **the expected security properties and their classifiation**, **the attacks found (if any)**, and the actual HLPSL specification."

TLS 条目实例：

```
PROBLEMS: 3
  secrecy of sec_clientk,sec_serverk
  strong authentication on na_nb1
  strong authentication on na_nb2
CLASSIFICATION: G1, G2, G3, G7, G10, G11, G13
ATTACKS: None
```

69 个条目中 68 个有 ATTACKS 字段，**54 个的值就是 `None`**，只有 14 个有内容且全是散文或原始轨迹（NSPK-KS 的全部内容是一句 "Man-in-the-middle attack"）。**同一页里 `CLASSIFICATION` 是结构化码，`ATTACKS` 是人话。**

G1–G20 目标词表（Deliverable D6.1 §3，逐字，从 2005 年快照的 PostScript 转出）：

| 码 | 名称 | 码 | 名称 |
|---|---|---|---|
| G1 | Entity authentication (Peer Entity Authentication) | G11 | Secure capabilities negotiation (Resistance against Downgrading and Negotiation Attacks) |
| G2 | Message authentication (Data Origin Authentication) | G12 | Confidentiality (Secrecy) |
| G3 | Replay Protection | G13 | Identity Protection against Eavesdroppers |
| G4 | Implicit Destination Authentication | G14 | Identity Protection against Peer |
| G5 | Source Authentication | G15 | (Limited) Denial-of-Service (DoS) Resistance |
| G6 | Authorization (by a Trusted Third Party) | G16 | Sender Invariance |
| G7 | Key authentication | G17 | "Accountability" |
| G8 | Key confirmation (Key Proof of Possession) | G18 | Proof of Origin |
| G9 | Perfect Forward Secrecy (PFS) | G19 | Proof of Delivery |
| G10 | Fresh Key Derivation | G20 | Safety Temporal Property |

**D6.1 里 `classif` 一词出现 0 次，没有任何攻击分类章节**；§7 是一张协议 × 目标矩阵。AVISPA 工具论文（CAV 2005）的实验表里，攻击维度只有一个数字：A = the number of problems for which attacks are detected。

### 7.3 工具示例库

- **Tamarin**：`examples/` 按会议年份组织（`cav13`、`ccs14`、`ccs18-5G`、`csf18-xor`、`usenix23-ens`…），无索引、无 metadata。
- **ProVerif 2.05**：按输入语言再按属性——`secr-auth`、`weaksecr`、`noninterf`、`choice`，全是安全属性名。整棵 examples 树只有一个 README，无任何结构化索引。
- **Scyther**：模型文件里唯一的标注是 goal claim。`otwayrees.spdl` 开头："# Modelled after the description in the SPORE library" + `claim_I1(I, Secret,Kir); claim_I2(I, Nisynch);`

**SPORE → Scyther 这条链传下去的是「协议 + 目标 claim」，攻击标签一次都没被传下去。**

## 8. 自动分类的既有尝试

### 8.1 三个真做自动分类的系统，都受限

1. **Vick, Kang, Tripakis, Counterexample Classification, SoSyM 2023**（arXiv:2108.00885）——最接近，但跑在 **Alloy** 上。关键限制是作者自己写的：

   > "A key idea behind our approach is the use of **user-defined summary predicates** for classifying counterexamples."

   `replay` / `manInTheMiddle` 是用户自己写的 Alloy 谓词，作者只说它们 "could be part of a library"——**那个库并不存在**。攻击名来自"用哪个谓词去种子化"，不是从反例里认出来的。

2. **DBVerify**（Mauw, Smith, Toro-Pozo, Trujillo-Rasua）——唯一找到的「Tamarin 输出 → 具名攻击类别」映射，机制是差分 lemma：

   > "If lemma `dbsec_hnst` fails, then a **mafia fraud** exists. If lemma `dbsec_hnst` holds and `dbsec` does not, then a **distance fraud** and/or a **distance hijacking** attack exist (**trace inspection is recommended**…)."

   词表只覆盖 distance-bounding 一个窄领域的四种 fraud，最后一步仍要人工看轨迹。

3. **Verifpal**——引擎自动贴 subtype 标签，但词表只有 5 个值（2 个 subtype + 3 个 qualifier），且直接由 query 语义推出。

### 8.2 最有力的一条负面证据

> Morio, Esiyok, Jackson, Künnemann. Automated Security Analysis of Exposure Notification Systems. USENIX Security 2023, §5.1 与脚注 5。

> "When Tamarin inevitably returns an attack, **we (manually) identify an attack pattern P₁**, characterising a class of similar attacks using the compromise events in Table 5…"

> "This is in contrast to prior work [19, 7], where attack patterns were **limited to adversarial capabilities, which allowed automating their discovery**. **We purposefully explore the space by hand**, adding information to the attack pattern until it is descriptive about the attack."

**能自动化的恰好只有「对抗能力集合」这一层；一旦要求 pattern 去描述攻击本身，就只能手工。**

相印证的还有三条：

- Cremers, Feasibility of Multi-Protocol Attacks (ARES 2006) 里的 type-flaw 标签来自**哪个配置下攻击才出现**（read 语义设成只收正确类型 / 收任意 basic term / 收任意 term，分别得 17 / 40 / 106 个攻击），而非分析轨迹。同文致谢逐字："thank … Gijs Hollestelle for his work on **classifying the attacks**"——**分类是雇人做的**。
- Scyther 的 "complete characterization" 是轨迹集合的有限表示，不是攻击分类。CAV 2008 工具论文："**By manually inspecting these patterns** … Scyther determines that there are only two patterns for the responder role: one is the correct behaviour of the protocol, and the other is the well-known man-in-the-middle attack."
- 现有可解释性工作止步于"让轨迹更易读"（参与方上色、compromise 规则标红、英文重建推导），**没有把轨迹映射到类目的系统**。

### 8.3 CAPEC / CWE 的缺口

有协议分支：CAPEC-512 Communications、CAPEC-94 Adversary in the Middle（→CWE-300/290/287/294/593）、CAPEC-272 Protocol Manipulation、CAPEC-90 Reflection Attack in Authentication Protocol（→CWE-301）、CAPEC-60 Session Replay（→CWE-294）。

**但 `type flaw` / `parallel session` / `interleaving attack` 在 CAPEC 里零命中。** CAPEC 的粒度是工程/运维层手法，Dolev-Yao 符号模型那套术语基本无对应。在本轮检索覆盖范围内，也没有找到任何把形式化验证器输出映射到 CAPEC/CWE 的工作。

## 9. 工具能力：ProVerif 2.05 的反例里有什么

本章全部经本机实测（32 个小 `.pv` 例子 + 真实 run + 语料轨迹），源码引用为 ProVerif 2.05 的 `src/display.ml`、`src/piauth.ml`、`src/main.ml`、`src/param.ml`。

### 9.1 三判词与三种 cannot be proved

手册 §3.3.1："`RESULT [Query] is true`: The query is proved, there is no attack. … `is false`: ProVerif has discovered an attack … `cannot be proved`: This is a 'don't know' answer."

`cannot be proved` 有三种可区分的子情形：

| 子情形 | 输出里的标记 | 含义 |
|---|---|---|
| 关掉了轨迹重建 | 有 `Derivation:`，无重建尝试提示 | 只是没试 |
| 重建失败 | `Could not find a trace corresponding to this derivation.` | 通常是 Horn 抽象的假攻击 |
| 等价类查询 | 打了完整轨迹，判词仍是 `cannot be proved` | 设计如此 |

重建失败的完整输出（复现手册 §6.7.5 的例子）：

```
Unification of attacker(senc(senc(s[],n[]),n[])) and attacker(senc(s[],n[])) failed or made a constraint become false at the input at occurrence {3}
Try adding a [precise] option on it.
Trying with the initial derivation tree instead.
Could not find a trace corresponding to this derivation.
RESULT not attacker(s[]) cannot be proved.
```

把 `in(c, x: bitstring)` 改成 `in(c, x: bitstring) [precise]` 后直接变成 `RESULT not attacker(s[]) is true.`——**`[precise]` 的有无可以把假攻击和真攻击分开**。

### 9.2 各类查询的反例形状

**secrecy**（`query attacker(M).`，内部编码 `not attacker(M[])`，有 phase 时自动改为最后一个 phase）：

```
goal reachable: attacker(s[])
...
The attacker has the message adec(~M_1,~M_2) = s in phase 1.
A trace has been found.
RESULT not attacker_p1(s[]) is false.
```

`The attacker has the message <recipe> = <value>.` 里的 recipe 就是攻击者的配方，它引用了哪些 `~M_k` 就是用到了哪些已知量。

**correspondence 非单射失败**：

```
event acceptB(a) at {7} in copy a_1 (goal)
The event acceptB(a) is executed at {7} in copy a_1.
RESULT event(acceptB(x)) ==> event(initA(x)) is false.
```

**correspondence 单射失败**（本章最关键的一条）：

```
RESULT inj-event(acceptB(x)) ==> inj-event(initA(x)) is false.
RESULT (but event(acceptB(x)) ==> event(initA(x)) is true.)
```

对照的另一种：`RESULT (even event(...) ==> event(...) is false.)`

`(but …)` 与 `(even …)` 的确切语义（源码 `piauth.ml:1944-2005` + `display.ml:2822-2851`）：ProVerif 先用 `simplify_query` 把原 query 里所有 `inj-event` 降级为 `event` 并把嵌套 `==>` 摊平，得到简化 query，把它的结论作为补充信息打出来，打印规则是

```ocaml
if r' == True then print_string "but " else print_string "even ";
```

所以：

- **`(but Q_simple is true.)` ⟺ 非单射对应成立、只有一一对应失败 ⟺ 重放。这是 ProVerif 唯一一个主动替使用者做的攻击分类。**
- `(even Q_simple is false.)` ⟺ 连非单射都不成立 ⟺ 认证彻底失效，不是重放。

派生里的单射证据：

```
We have @occ8_1 ≠ @occ8_2.
The goals for injectivity are reached, combined in the following fact:
inj-event(acceptB(n_2),@occ8_1) && inj-event(acceptB(n_2),@occ8_2).
```

**observational equivalence / choice**：

```
The attacker tests whether ~M = choice[a,b] is equal to b.
The result in the left-hand side is different from the right-hand side.
A trace has been found.
RESULT Observational equivalence cannot be proved.
```

**永远不会打 `is false`**。手册 §6.7.5："for this reason, ProVerif never says that an observational equivalence is false."；源码 `main.ml:280` 的等价分支结果只能是 `DontKnow`。唯一例外是带 restrictions 的 `ChoiceQuery`（显示名变成 `diff-equivalence`）。

**strong secrecy**（`noninterf`）同样只能 `cannot be proved`（`main.ml:275`）。

**weak secret** 是**唯一一个等价类查询里能给出 `is false` 的**（`main.ml:273`，注释写明 "For weak secrets, the reconstructed attack really falsifies the equivalence"）：

```
This allows the attacker to know whether @weaksecretcst = w.
A trace has been found.
RESULT Weak secret w is false.
```

铁标记三件套：`@weaksecretcst`、`attacker_guess(...)`、`in off-line phase`。

**phases**：query 自动改名 `attacker_p1(...)`；派生里 `So the attacker may know … in phase 1.`。**坑**：short 轨迹里没有 phase 切换行（源码 `display_step_short` 对 `RPhase` 落到 `| _ -> ()`），阶段边界只能靠 `{n}` 反查进程清单。另 `set keyCompromise` 与轨迹重建不兼容（手册 §6.6.2），只有派生。

**table / get**：`get keys(=a,k_1: key): else branch taken at {9}` 是 short 模式下唯一会出现的 else 分支行。

**`set ignoreTypes` 与 type flaw**：ProVerif 2.05 的默认值是 `true`（类型在验证期被擦掉，源码 `param.ml`）。手册 §4.1.2："By default, types are used for typechecking the protocol but during protocol verification, ProVerif ignores types. … (This behavior allows ProVerif to detect type flaw attacks, in which the attacker mixes data of different types.)" 因此**类型化的 `.pv` 模型里 type flaw 攻击照样会被找到**。切到 `set ignoreTypes = false.` 有三个可见变化：攻击者谓词按类型拆分（`attacker_bitstring`、`attacker_nonce`）、投影函数名带类型、基于类型混淆的攻击消失。

### 9.3 轨迹行型速查

`{n}` 是解析期给每个 `in`/`out`/`new`/`let`/`if`/`event`/`insert`/`get`/`phase` 分配的出现序号，打印在开头的 `Process 0 (that is, the initial process):` 清单里。两个坑：编号顺序 ≠ 显示顺序（`get … in … else` 是两段式构造）；ProVerif 通常还会打第二份清单 `Process 1 (that is, process 0, with let moved downwards)`，后面的 `-- Query ... in process 1.` 指明实际验证的是哪一份。

short 模式（默认）只有 9 种 reduction 会输出，其余（`RTest_*`、`RLet_*`、`RPar`、`RRepl`、`RNil`、`RPhase`）一律静默：

| 行 | 含义 |
|---|---|
| `new sk: skey creating sk_1 at {1}` | 诚实进程生成新名 |
| `out(c, ~M) with ~M = s at {3}` | 输出；`~M_k` 是攻击者知识槽 |
| `in(c, ~M) with ~M = senc(n_3,k) at {6} in copy a_1` | 输入；括号里是配方，`=` 后是实际值 |
| `in(c, a) at {6} in copy a_1` | 配方是裸名 → 攻击者凭空造的 |
| `out(d, s) at {1} received at {2}` | 私有信道内部通信，攻击者没插手 |
| `event acceptB(n_3) at {8} in copy a_1 (goal)` | 事件；`(goal)` 表示这一步是 query 的目标 |
| `insert keys(id_1,k_2) at {4}` / `get … at {81} in copy a_4` | 表 |

结尾块：`The attacker has the message …`、`The event … is executed at …`、`The table element … is present.`、`A trace has been found.`（带 axiom/restriction 时是 `A trace has been found, assuming the following hypothesis:`）。

`in copy a` / `a_2` —— 手册 §3.3.2："The name itself is unimportant, just the fact that the copy is the same or different is important: the presence of different names of copies for the same replication shows that several sessions are used."

`set traceDisplay = long.` 多出来的：每步之后的攻击者知识增量与残余进程、**角色名**（`2nd process: Beginning of process processA`）、身份绑定（`let intended_peer_A_1: host = I_1 succeeds`）、每个 `if` 的成败（`if (A_3 = A_3) succeeds` / `if (I_1 = B_2): else branch taken`）。**代价**：long 模式不打 `{n}`，改用会漂移的 `1st process:` 序数。

**派生（Derivation）是目标的证明树，每一步都被用到**，所以"攻击是否依赖某个前提"要在这里查，不要在轨迹里查（轨迹会把所有顶层公开 `out` 都先跑一遍）。主要句式：`The attacker initially knows c[].`、`We assume as hypothesis that attacker(x).`、`The message M may be sent to the attacker at output {n}.`、`The message M that the attacker may have by k may be received at input {n}. So the message M' may be sent to the attacker at output {m}.`（把诚实进程当预言机）、`Using the function adec the attacker may obtain X.`、`So the attacker may know X in phase 1.`、`We have X ≠ Y.`、`The goal is reached, represented in the following fact:`。

### 9.4 `-graph` 的 dot（本轮实测）

`proverif -graph <dir> file.pv` 生成 `trace1.dot`（有 graphviz 时另出 PDF）。实测确认：

- **没有安装 graphviz 时仍然写出 `trace1.dot`，退出码 0，无报错**，只是不生成 PDF。
- dot 节点同时携带**程序点**（`{1}new A_3`）与**角色名**（`Beginning of process <FONT COLOR="darkgreen">processA</FONT>`），边带方向（`dir = back` 表示攻击者→进程）与消息配方，目标节点标 `color = red`。
- 默认（short）的 dot 里没有 `let … succeeds` / `if …` 步骤；**加上 `set traceDisplay = long.` 之后 dot 变大并包含身份绑定与守卫成败**（实测 70137 → 74421 字节，出现 `intended_peer_A_1: host = I_1` 与 `{54}if (I_1 = B_2): else branch taken`、`{67}if (A_3 = A_3)`）。

**即：一次 `set traceDisplay = long.` + `-graph` 的运行，可以在一份机器可读文件里同时拿到程序点、角色名、进程谱系、配方、身份绑定、守卫成败和目标标记。** 这是补上 §9.5 那条缺口（中间人/反射/冒充需要程序点→角色→身份的映射）的现成途径。

### 9.5 哪些类别机械可判、哪些不可

**可机械判定**（只看输出，或加一次确定性的二次运行）：

| 类 | 判据 |
|---|---|
| 重放 | `RESULT (but <非单射版> is true.)` |
| 离线猜测 | `RESULT Weak secret X is false.` + `@weaksecretcst` |
| 会话数 | 同一 `!` 下不同 `in copy` 标签计数 |
| 攻击者凭空造值 | 配方含裸名，或派生有 `The attacker has some term x.` |
| 原样转发 | 配方是单个 `~M_k` |
| 拆装重包 | 配方同时含析构子与构造子 |
| 字段替换 | in/out 配方结构对齐后的差异位置 |
| 把诚实进程当预言机 | 派生 `… received at input {n}. So … sent to the attacker at output {m}.` |
| 用了哪个原语 | 派生 `Using the function f the attacker may obtain …` |
| 是否依赖某个泄露 | 派生是否引用该泄露 output（**务必用派生，不用轨迹**） |
| 是否需要主动发消息 | `set attacker = passive.` 二次运行 |
| 是否依赖类型擦除 | `set ignoreTypes = false.` 二次运行 |
| 疑似假攻击 | `Could not find a trace corresponding to this derivation.`，可用 `[precise]` 复检 |

**区分不开**：

1. **MITM vs 反射 vs 冒充**。三者在 short 轨迹里都是"某条 `in` 的配方引用了别处的 `~M`"。需要 `{n}` → 角色 → 身份两级映射，而身份只在 long 轨迹的 `let … succeeds` 行或 dot 的进程谱系里（见 §9.4）。
2. **KCI vs 前向安全 vs post-compromise**。输出完全同形，差别 100% 在"泄露谁的密钥、在哪个 phase、目标是哪一方"——场景元数据，不是攻击特征。
3. **type flaw vs 普通字段替换**。默认模式下输出一模一样，只有差分运行能分开。
4. **降级攻击**。没有独立的输出信号，只是字段替换 + 原语使用的组合，且要求模型真把弱算法建弱。
5. **不可关联性 / 匿名性"失败"**。ProVerif 给不出 `is false`（§9.2）。
6. **被动 vs 主动**（单次运行）。公开信道上即使原样转发也要过攻击者。

**ProVerif 完全看不到的**：计算复杂度层面的攻击（碰撞、弱随机、小子群、padding malleability）、侧信道、默认建模下的 Bleichenbacher 式 oracle（else 分支不打印，攻击者拿不到"解密失败"这个比特）、可变状态（`table` 只增不减，没有"不在表里"这个谓词，一次性令牌/计数器/撤销列表建不出来）。ProVerif 自身的抽象还会产生假攻击（动作重复次数被忽略、私有信道更不精确），`[precise]` 能消掉相当一部分。

### 9.6 Tamarin 对照

反例是偏序依赖图而非线性轨迹：节点 = 完整实例化的 rule instance（规则名 + `$I=A, $R=I, ~ni=~n1` 全部绑定），边 = fact 依赖与序约束。`!KD` = 解构、`!KU` = 构造，手册："solid red orange arrows … represent steps where the adversary extracts values from a message he received"。

判词行 `summary of summaries` 四种状态：`verified` / `falsified - found trace` / `falsified - no trace found` / `analysis incomplete`。**方向会反转**：`all-traces` 下 `falsified - found trace` 才是有攻击，`exists-trace` 下相反，解析必须连量词一起读。

机器可读导出是它的工程优势：`--output-json=traces.json` / `--output-dot=traces.dot`，反例是结构化图对象。

Tamarin 能表达而 ProVerif 不便表达的：可变全局状态（linear fact 被消耗）、时间点量化的 restriction（"全局只许跑一次"）、post-compromise（`Reveal` 规则 + lemma 里的时间点不等式，比 phase 灵活）、AC 等式理论内建（DH、XOR、bilinear pairing、multiset）。观察等价同样不能给"为假"的确定结论（手册 `014_limitations`："only (soundly) approximates observational equivalence … the found attack is a potential attack"）。

**对反例判读最关键的一条对比**：「哪个 agent 在哪个 session 执行了哪一步」在 Tamarin 里是图节点的一等属性，可直接机械提取；ProVerif 的 short 轨迹只有 `{n}` + `in copy a_k`，身份要靠 long 轨迹或 dot 补上。代价是 Tamarin 把反例拿到手本身更难（sources lemma、oracle、不终止）。

## 10. 语料实证（VerdictBench）

统计范围：106 个协议目录（判据是同时具备 `claims/{properties,assumptions,claims}.json` 与 `results/{cases_results,results}.json`），全部齐全，`vocab_version` 一律 `2.2.0`。

口径说明：**格（cell）** = 一个 property × 一个场景；场景名由解析后的完整赋值（fixed ∪ conditions ∪ 未指定 variable 的本轴 noop 档）反查 `claims.json` 还原，106 个协议全部还原成功；**削弱**定义为某个 variable 假设的档位沿 `stronger_than` 闭包弱于本轴 noop（注意 `channel` 是唯一一根 noop 档就是最弱档的轴，所以 `channel.secure` 出现在场景里是强化不是削弱）；**fixed 假设不参与场景间比较**，因为它对该协议所有场景一视同仁。

### 10.1 规模与 false 分布

| 项 | 数 |
|---|---|
| 协议目录 | 106 |
| 格总数 | 1247 |
| true | 600 |
| **false** | **616** |
| unknown | 31 |
| property 实例（协议 × property） | 532 |
| 场景实例（协议 × 场景） | 264 |
| `results.json` 合并结论 | 532 条，其中 false 380（71.4%） |

按目标类型：

| type.subtype | 格 | false | false 率 |
|---|---|---|---|
| Authentication.injective_agreement | 397 | 233 | 58.7% |
| Authentication.non_injective_agreement | 467 | 221 | 47.3% |
| Secrecy.basic | 317 | 145 | 45.7% |
| Secrecy.forward_secrecy | 45 | 8 | 17.8% |
| Authentication.weak_agreement | 6 | 6 | 100% |
| Secrecy.weak_secret_guessing_resistance | 10 | 3 | 30.0% |
| Privacy.unlinkability | 5 | 0 | 0% |

（Privacy.unlinkability 全部不是 false，与 §9.2「等价类查询永远不会给出 `is false`」一致。）

### 10.2 攻击标注全表

全语料 15 份 `attacks/attacks.json`，共 **16 条 attack、32 条 `refutes`**。**32 条全部落在 ground truth 的 false 格上，零不一致。**

| # | 协议 | name（short） | refutes | reference |
|---|---|---|---|---|
| 1 | 5G-AKA TS33.501 v15.0.0 / AKA | Key-confirmation failure over a non-binding backhaul（Key-confirm fail） | `seaf_agrees_hn_on_supi_noninjective` @ `nonbinding_backhaul` | Basin et al., CCS 2018 |
| 2 | ISO 11770-3 / key-agreement-mechanism-1 | Key-establishment failure (no entity authentication)（No entity auth） | 4 条 @ `baseline` | — |
| 3 | ISO 9798-2 / mechanism-2-no-identifier | Reflection attack（Reflection） | `bob_weak_agreement_with_alice` @ `baseline` | Basin, Cremers, Meier, JCS 2013 |
| 4 | academic/Denning-Sacco | Ticket replay (multiplicity attack)（Ticket replay） | `bob_injective_agreement_with_alice` @ `baseline` | Lowe 1997 |
| 5 | academic/Kao-Chow | One-sided authentication weakness（One-sided auth） | 2 条 @ `baseline` | — |
| 6 | academic/NSPK | Lowe's man-in-the-middle attack（Lowe MITM） | `secrecy_i_a`, `secrecy_i_b`, `auth_b_to_a` @ `admission_open` | Lowe, IPL 1995 |
| 7 | academic/NSSK | Denning--Sacco known-key replay（Known-key replay） | `secrecy_CK` @ `sk_reveal_session_key_skr_others` | Lowe 1997 |
| 8 | academic/Neuman-Stubblebine | Hwang type-flaw attack (responder side)（Type flaw (R)） | 2 条 @ `baseline` | Hwang et al. 1995 |
| 9 | academic/Neuman-Stubblebine | Initiator-side weakness（Initiator weakness） | 2 条 @ `baseline` | Hwang et al. 1995 |
| 10 | academic/Otway-Rees | Weak authentication（Weak auth） | 4 条 @ `baseline` | SPORE 2003 |
| 11 | academic/Yahalom | Weak authentication in the initiator's direction（Weak auth (I)） | 1 条 @ `baseline` | — |
| 12 | academic/wide-mouth-frog | Timestamp replay（Timestamp replay） | 2 条 @ `baseline` | SPORE 2003 |
| 13 | informal/FIDO UAF / registration | Authenticator rebinding（Rebinding） | 1 条 @ `authenticator_rebinding` | Feng et al., NDSS 2021 |
| 14 | rfc/IKEV2 / signature | SA-field disagreement（SA disagreement，`abstraction_gap: true`） | `auth_resp_to_init` @ `baseline` 与 @ `sa_attacker_chosen` | Cremers, ESORICS 2011 |
| 15 | rfc/TLS13 draft18 / zero-rtt | 0-RTT weakness under a leaked PSK（0-RTT / PSK leak） | 2 条 @ `psk_compromised` | Cremers et al., CCS 2017 |
| 16 | rfc/TLS13 draft20 | 同上 | 3 条 @ `psk_compromised` | Cremers et al., CCS 2017 |

**准入口径**（写在生成脚本的 docstring 里）：

> "Only cells the paper actually names as an attack are listed. A false cell that is merely the consequence of a weakened assumption ('the key was handed to the attacker, so secrecy fails') is not an attack and gets no entry — the console then marks nothing, which is the honest outcome."

另有两类非结构化材料：

- `academic/NSPK/attacks/nspk_simple_attack.json` —— 语料里唯一一份消息级攻击轨迹，字段是 `name` / `precondition`（自然语言 + 词表 id）/ `attack_flows`（11 步，每步 `{source, target, value[], note?}`）/ `consequence`。**不能被机器对上 ground-truth 格**，是给人读的说明。
- `ISO/9798-6-manual-data-transfer` 下 4 个子协议各 2 份 ProVerif 原始输出（共 8 份，34–39 KB）。两份的差别在 short random `R` 的建模方式：`leak-R` 是 `new R; out(c, R)`，`predictable-R` 是换成全局公开常量 `fixedR`。8 份结论一致，都是同一组四条对应性查询被证伪。

### 10.3 false 格成因四分

| 类 | 含义 | 数量 | 其中被点名 |
|---|---|---|---|
| **A** | **基线 false**：场景里没有任何削弱 | **148** | 22 |
| A1 | 协议的运行前提（OOB / 受保护链路）被置于 noop 档 | 60 | 1 |
| A2 | 真·裸基线 false | 88 | 21 |
| **B** | **削弱就是原因**：同一目标在无削弱场景下为 true | **367** | 6 |
| **C** | 有削弱，但该目标在无削弱场景下也 false | **88** | 1 |
| **D** | 该目标只在削弱场景下被问过，无基线对照 | **13** | 3 |

**B 类 367 个是整个语料 false 格的主体（59.6%）**，按生成脚本的口径本来就不该被点名——但其中仍有 6 个被点名，**所以「削弱导致」不等于「不是攻击」**。

「真正的削弱」的致 false 率（只算 variable 里弱于 noop 的档，cell 层面）：

| 削弱档 | 出现格数 | 其中 false | 致 false 率 |
|---|---|---|---|
| data.disclosed | 579 | 470 | 81.2% |
| data.leaked_after_session | 100 | 34 | 34.0% |
| primitive.broken（variable） | 12 | 0 | 0% |
| data.chosen | 8 | 2 | 25.0% |
| admission.open（variable） | 4 | 3 | 75.0% |
| data.leaked_in_other_instances | 1 | 1 | 100% |

对照强化档：`channel.secure` 301 格 / 62 false（20.6%）。无任何削弱的格 452 个（严格口径），false 率 26.8%。

**367 个「削弱导致的 false」里，363 个（98.9%）的削弱项全部是 `ltk_*` 前缀的长期密钥假设。** 语料的 variable 命名只有 6 种前缀：`ltk_`（132）、`link_`（54）、`strength_`（2）、`chosen_`（2）、`admission_`（1）、`sk_`（1）。**语料里的可变假设空间实质上只有两件事：泄露一把长期密钥，或者改一条链路的保护等级。**

一条反直觉的实证：**没有任何一个 false 格是把目标 `values` 里的值本身 `disclosed`/`chosen` 出去的**（同一判定在 206 个 Secrecy true 格、460 个 Auth false 格上均 0 命中）。字面口径的"秘密被直接交出"在全语料只命中 5 个格（AKMA 的 `secrecy_k`/`secrecy_supi` 各两条，NSSK 的 `secrecy_CK`），且都是 `leaked_after_session` / `leaked_in_other_instances`。**成立的形式要往上提一层：被泄露的是托住这个目标的那把长期密钥。**

### 10.4 基线 false 的再切分

148 个基线 false 按"该场景相对协议自己声明的可选档处在什么位置"分三层：

| 层 | 定义 | 格数 |
|---|---|---|
| T1 | 每条 variable 都取到声明里的最强档（或协议根本没有 variable）——该协议被问到的最强世界，仍然 false | 82 |
| T2 | 没有削弱，但某条 variable 没取满最强档 | 6 |
| T3 | 有 variable 停在 noop 档，而声明里还存在更强的档——**协议的运行前提被拿掉了** | 60 |

**T1 + T2 = 88 格是「最可能是真正的协议缺陷」的那一堆**，其中 21 格被点名、67 格没有。

T3 的 60 格集中在两族：ISO 9798-6 全族 42 格（4 条人工链路全部留在 `channel.public`，而 9798-6 的全部安全性依赖人工接口不在攻击者手里）、ISO 11770-7 的 15 格与 ISO 11770-3 public-key-transport 的 2 格、FIDO UAF 1 格。

**`channel` 是五根轴里唯一 noop 档就是最弱档的轴。凡是协议把「受保护链路 / OOB 接口」写成 variable 的，它的 `baseline` 就不是「没有削弱的世界」，而是「协议前提不成立的世界」。** 另外值得注意的是，`compromise_local_PAKE_*`、`compromise_*_channel` 这类场景名读起来像削弱，机械上却是"把一条链路留在 noop"，名字与机制对不上。

### 10.5 源文档里的攻击词频

96 份源文档（ISO / RFC 原文）里攻击名词的出现次数 / 覆盖协议数：

`replay` 189/21 · `MITM`+`man-in-the-middle` 143/6 · `forge`+`forgery` 53/14 · `collision` 34/8 · `reflection (attack)` 28/7 · `eavesdrop` 24/6 · `known key` 24/6 · `impersonation` 23/7 · `unknown key(-)share` 21/3 · `linkability` 20/4 · `side(-)channel` 18/2 · `tampering` 17/9 · `forced delay` 16/5 · `downgrade` 16/2 · `denial(-)of(-)service` 15/6 · `key compromise impersonation` 14/4 · `small subgroup` 12/5 · `substitution attack` 12/5 · `tracking` 10/6 · `traffic analysis` 10/3 · `brute-force` 8/4 · `interleaving` 6/6 · `dictionary attack` 5/4 · `guessing attack` 4/2 · `key-malleability` 4/2 · `offline dictionary` 2/2 · `type-flaw` 2/1 · `cross-protocol` 2/1 · `chosen ciphertext` 1/1 · `desynchroniz*` 3/1

**这 30 个词里，只有 replay / MITM / reflection / type-flaw / known-key / rebinding 这 6 个真正出现在 16 条攻击标注的 `name`/`short` 里**；其余（KCI、UKS、small subgroup、downgrade、interleaving、DoS、side-channel…）在语料里只是文档正文的名词，没有任何 ground-truth 格与之对应。

## 11. 本轮自有实验

### 11.1 重放信号在本地 run 中的分布

对 `a_runs` 下全部 ProVerif 输出 grep：`RESULT (but …)` 出现在 58 个文件，`RESULT (even …)` 出现在 352 个文件。`(but …)` 的协议分布：wide-mouth-frog 12、Denning-Sacco 10、ISO-9798-2-mechanism-1 6、ISO-11770-3-secret-key-transport-mechanism-2/3 各 6、ISO-11770-3-key-agreement-mechanism-3 6、Otway-Rees 4、ISO-9798-2-mechanism-3 4……

**落点与语料标注为重放的攻击一致**（Denning-Sacco 的 ticket replay、wide-mouth-frog 的 timestamp replay）。这是 §9.2 那条判据在真实数据上的验证。

### 11.2 配方特征原型

对 NSPK 的 Lowe 攻击轨迹（`02_proverif_trace_secrecy_i_a.txt`）做约 40 行的配方解析，六条攻击者输入被算成：

```
{45} copy a    relay    ~M
{62} copy a_2  rewrap   aenc((1-proj-2-tuple(adec(~M_14,~M_1)),~M_9),~M_3)   跨会话 a→a_2
{78} copy a_4  select   (a_3,~M_9)
{65} copy a_2  relay    ~M_17                                                跨会话 a_4→a_2
{50} copy a    relay    ~M_18                                                跨会话 a_2→a
{70} copy a_2  rewrap   aenc(adec(~M_19,~M_1),~M_3)                          跨会话 a→a_2
```

两处 `rewrap` 是 Lowe 攻击的核心动作（用攻击者自己的私钥解开、换 B 的公钥重封）；`a→a_2` 与 `a_2→a` 构成双向环。判据：配方是裸名 → 伪造；单个 `~M_k` → 转发；同时含析构子与构造子 → 重包；只含构造子 → 拼装。

### 11.3 「交织诚实会话」不能区分真假攻击（负结果）

把同一原型跑在 ISO 9798-2 mechanism-6-mutual 的 `ltk_reveal_KAP` 场景上（泄露一把长期密钥导致的 false），得到的特征是 `fabricate` / `compose` / `rewrap` 加跨会话链接——**与 Lowe 几乎同形**。

**因此「攻击是否需要交织诚实会话」不能把「协议缺陷」和「假设直接导致」分开。**

### 11.4 诚实角色体判据（正结果）

改判据为「被削弱的那个值是否出现在某个诚实角色宏的进程体内」，在两个案例上分得干净：

```
NSPK24      private_key_I  出现在诚实角色体内: 否        （角色 processA / processB / processS）
ISO-mech-6  K_AP           出现在诚实角色体内: processA
```

NSPK 被削弱的是攻击者自己的私钥（它是合法注册的参与方），削弱只是开了门，攻击仍要靠协议结构才成立；ISO 那条被削弱的 `K_AP` 长在 `processA` 体内，拿走它认证必然垮。

**这条判据对应 Basin & Cremers 三维里的第二维「whose data it is」**，也正是 §8.2 所说唯一能自动化的那一层。

### 11.5 成因四分可从单个 run 自己的产物算出

用 `cases_results.json` 加 `assumptions.json` 的 variable 声明，配合 realizer 注册表的 `stronger_than` 闭包与本轴 noop 档，在四个本地 run 上计算成因位：

| run | 格 | false | 成因分布 |
|---|---|---|---|
| ISO-9798-2-mechanism-6-mutual | 24 | 14 | 削弱导致 14 |
| ISO-9798-2-mechanism-5-mutual | 24 | 15 | 削弱导致 11、基线 1、下游重复 3 |
| ISO-11770-3-key-agreement-mechanism-1 | 21 | 18 | 削弱导致 6、基线 4、下游重复 8 |
| NSPK24 | 8 | 3 | 削弱导致 3（即 Lowe 的三个格） |

**一处必须注意的口径**：fixed 假设对该协议每个场景一视同仁，不能计入削弱。未排除时 NSPK 的三个格会被误算成"无基线对照"。

## 12. 结论

1. **按攻击手法切分的封闭词表，在文献里被反复尝试并反复退回到人工。** 证据是收敛的：类目重叠、层级冲突、自认不完备、外延随工具漂移、同一攻击多名，以及 §8 里三个自动分类系统的一致受限。
2. **稳定的两根轴是「被破坏的目标」与「敌手能力 / 前提条件」。** Lowe 1997 的认证层级是全序、封闭且被广泛采用；Basin & Cremers 的三维每一维都在问一个关于明确对象的中性事实问题。历来被当作攻击类型的名字（PFS、wPFS、UKS、KCI）本来就是这两根轴上的二元组。
3. **教科书自己走完了这条路**：Boyd & Mathuria 第 1 版的「攻击类型」在第 2 版改名为「对手能力」，内容一字未动。
4. **工具侧能机械支撑的只有四族信号**：重放（工具自己给的判词）、猜测、攻击者动作形状、会话拓扑；角色与身份需要 long 轨迹或 `-graph` 的 dot 才能拿到；KCI / 前向安全 / post-compromise 在输出里完全同形；等价类目标不会给出 `is false`。
5. **语料实证与文献结论一致**：616 个 false 里只有 5.2% 被认定为攻击；主体（59.6%）是削弱假设的后果，但削弱不等于不是攻击（NSPK 的 Lowe 就在这一堆里）；另有 60 个格是协议前提被拿掉，性质完全不同，任何分类都必须能把它单列出来。

## 附录 A：参考文献

按本文出现顺序。核实状态：✅ 原文已读；⚠️ 仅二手转述；❌ 未取得。

**手法分类学**

1. ✅ J. Clark, J. Jacob. *A Survey of Authentication Protocol Literature: Version 1.0*. University of York, 1997-11-17. https://condor.depaul.edu/dmumaugh/readings/handouts/crypto/ClarkJacob1997SurveyAuthentication.pdf
2. ❌ U. Carlsen. *Cryptographic protocol flaws: know your enemy*. CSFW-7, 1994, pp. 192–200. DOI 10.1109/CSFW.1994.315934.（摘要 ✅ 经 OpenAlex；类目 ⚠️ 经 [1]）
3. ❌ P. Syverson. *A Taxonomy of Replay Attacks*. CSFW-7, 1994, pp. 187–191. DOI 10.1109/CSFW.1994.315935.（结构 ⚠️ 经 [1][4][6]）
4. ✅ S. Gritzalis, D. Spinellis. *Cryptographic Protocols over Open Distributed Systems: A Taxonomy of Flaws and related Protocol Analysis Tools*. SAFECOMP '97, pp. 123–137. https://www2.dmst.aueb.gr/dds/pubs/conf/1997-SafeComp-Formal/html/doc.pdf
5. ⚠️ C. Boyd, A. Mathuria. *Protocols for Authentication and Key Establishment*. Springer, 2003（目录 ✅ 经 d-nb.info/968658024/04；Table 1.3 ✅ 经 IA 全文检索 `protocolsforauth0000boyd`；§1.6 正文 ❌）。第 2 版：Boyd, Mathuria, Stebila, 2020（目录 ✅ 经 d-nb.info/1164799010/04；正文 ❌）
6. ✅ M. Toorani. *Security Protocols in a Nutshell*. arXiv:1605.09771.
7. ❌ U. Carlsen. *Using logics to detect implementation-dependent flaws*. ACSAC 9, 1993, pp. 64–73. DOI 10.1109/CSAC.1993.315453.（摘要 ✅）
8. ❌ U. Carlsen. *Spécification et analyse formelles des protocoles cryptographiques*. Thèse, Université Paris XI, 1994（NNT 1994PA112255，未数字化）

**维度化**

9. ✅ D. Basin, C. Cremers. *Know Your Enemy: Compromising Adversaries in Protocol Analysis*. ACM TISSEC 17(2), 2014. https://people.cispa.io/cas.cremers/downloads/papers/compromise-tissec.pdf
10. ✅ C. Cremers. *Examining Indistinguishability-Based Security Models for Key Exchange Protocols: The case of CK, CK-HMQV, and eCK*. AsiaCCS 2011.
11. ✅ E. Alashwali, K. Rasmussen. *What's in a Downgrade? A Taxonomy of Downgrade Attacks in the TLS Protocol and Application Protocols Using TLS*. SecureComm 2018. arXiv:1809.05681.
12. ⚠️ G. Lowe. *A Hierarchy of Authentication Specifications*. CSFW 1997.（层级定义广泛转述，原文本轮未逐字核对）

**type flaw 线**

13. ✅ F. J. Thayer Fábrega, J. C. Herzog, J. D. Guttman. *Strand Spaces: Proving Security Protocols Correct*. JCS 7(2,3), 1999. https://web.cs.wpi.edu/~guttman/pubs/jcs_strand_spaces.pdf
14. ✅ J. Heather, G. Lowe, S. Schneider. *How to Prevent Type Flaw Attacks on Security Protocols*. CSFW 13, 2000, pp. 255–268；JCS 11(2), 2003（已出版页码 ❌）。作者预印本 https://www.cs.ox.ac.uk/people/gavin.lowe/Security/Papers/typing.ps ／ typingJCS.ps
15. ✅ C. Meadows. *Identifying Potential Type Confusion in Authenticated Messages*. FCS'02, pp. 75–84. https://www.cs.cmu.edu/~iliano/papers/fcs02.pdf
16. ✅ H. Gao, C. Bodei, P. Degano. *A Formal Analysis of Complex Type Flaw Attacks on Security Protocols*. AMAST 2008, LNCS, pp. 167–183. https://pages.di.unipi.it/bodei/publ-40/AMAST08.pdf
17. ✅ S. Malladi, P. Lafourcade. arXiv:1003.5385；S. Malladi. arXiv:1004.2522.
18. ❌ E. Snekkenes. *Roles in cryptographic protocols*. IEEE S&P 1992, pp. 105–119.（摘要 ✅ 经 OpenAlex）

**misbinding / UKS / KCI**

19. ✅ W. Diffie, P. C. van Oorschot, M. J. Wiener. *Authentication and Authenticated Key Exchanges*. Designs, Codes and Cryptography 2(2):107–125, 1992.
20. ✅ S. Blake-Wilson, A. Menezes. *Unknown Key-Share Attacks on the Station-to-Station (STS) Protocol*. PKC '99, LNCS 1560:154–170（作者版 CORR 98-42）
21. ✅ H. Krawczyk. *SIGMA: The 'SIGn-and-MAc' Approach to Authenticated Diffie-Hellman and Its Use in the IKE Protocols*. CRYPTO 2003.
22. ✅ H. Krawczyk. *HMQV: A High-Performance Secure Diffie-Hellman Protocol*. CRYPTO 2005.
23. ⚠️ S. Blake-Wilson, D. Johnson, A. Menezes. *Key Agreement Protocols and their Security Analysis*. 1997.
24. ⚠️ B. LaMacchia, K. Lauter, A. Mityagin. *Stronger Security of Authenticated Key Exchange*. ProvSec 2007.
25. ❌ B. Kaliski. *An unknown key-share attack on the MQV key agreement protocol*. ACM TISSEC 4(3), 2001.（内容经 [22] 附录 A 转述）
26. ❌ M. Just, S. Vaudenay. *Authenticated Multi-Party Key Agreement*. ASIACRYPT 1996.（KCI 首次描述，仅由 [9] 的引用支持）

**cross-protocol / 组合性**

27. ✅ J. Kelsey, B. Schneier, D. Wagner. *Protocol Interactions and the Chosen Protocol Attack*. Security Protocols Workshop 1997. https://www.schneier.com/wp-content/uploads/2016/02/paper-chosen-protocol.pdf
28. ✅ C. Cremers. *Feasibility of Multi-Protocol Attacks*. ARES 2006.
29. ✅ C. Cremers. *Compositionality of Security Protocols: A Research Agenda*. ENTCS 142, 2006. https://people.cispa.io/cas.cremers/downloads/papers/Cr2006-compositionality_agenda.pdf
30. ✅ J. D. Guttman, F. J. Thayer. *Protocol Independence through Disjoint Encryption*. CSFW 2000. https://web.archive.org/web/2020/https://www.mitre.org/sites/default/files/pdf/guttman_protocol.pdf
31. ✅ S. Andova, C. Cremers, K. Gjøsteen, S. Mauw, S. F. Mjølsnes, S. Radomirović. *A framework for compositional verification of security protocols*. Information and Computation 206(2–4), 2008. https://people.cispa.io/cas.cremers/downloads/papers/AnCrGjMaMjRa2008-compositional_framework.pdf
32. ✅ A. Datta, A. Derek, J. C. Mitchell, D. Pavlovic. *Secure Protocol Composition*. MFPS'03 / ENTCS 83, 2004. http://seclab.stanford.edu/pcl/papers/ddmp-mfps03.pdf
33. ✅ M. Arapinis, V. Cheval, S. Delaune. *Composing security protocols: from confidentiality to privacy*. POST'15. arXiv:1407.5444
34. ✅ F. Bergsma, B. Dowling, F. Kohlar, J. Schwenk, D. Stebila. *Multi-ciphersuite security of the Secure Shell (SSH) protocol*. CCS 2014.
35. ⚠️ T. Jager, J. Schwenk, J. Somorovsky. *On the Security of TLS 1.3 and QUIC Against Weaknesses in PKCS#1 v1.5 Encryption*. CCS 2015.
36. ⚠️ J. Alves-Foss. *Multi-protocol attacks and the public key infrastructure*. NISSC 1998.
37. ⚠️ M. Brinkmann et al. *ALPACA: Application Layer Protocol Confusion*. USENIX Security 2021.

**downgrade**

38. ✅ K. Bhargavan, C. Brzuska, C. Fournet, M. Green, M. Kohlweiss, S. Zanella-Béguelin. *Downgrade Resilience in Key-Exchange Protocols*. IEEE S&P 2016.
39. ⚠️ D. Wagner, B. Schneier. *Analysis of the SSL 3.0 Protocol*. USENIX Electronic Commerce 1996.
40. ⚠️ N. Mavrogiannopoulos et al. *A cross-protocol attack on the TLS protocol*. CCS 2012.

**仓库与工具**

41. ✅ SPORE: Security Protocols Open Repository. LSV. https://lsv.ens-paris-saclay.fr/Software/spore/
42. ⚠️ AVISPA Library / Deliverable D6.1（原站已失效，经 Wayback；D6.1 §3 的 G1–G20 ✅ 从 2005 快照 PostScript 转出）
43. ✅ ProVerif 2.05 手册与源码（`src/display.ml`、`src/piauth.ml`、`src/main.ml`、`src/param.ml`）
44. ⚠️ Tamarin-prover 官方手册
45. ⚠️ Scyther 示例库（`otwayrees.spdl` ✅ 已读）

**自动分类**

46. ✅ C. Vick, E. Kang, S. Tripakis. *Counterexample Classification*. SoSyM 2023. arXiv:2108.00885
47. ⚠️ S. Mauw, Z. Smith, J. Toro-Pozo, R. Trujillo-Rasua. DBVerify / distance-bounding 自动验证系列
48. ⚠️ Verifpal
49. ✅ K. Morio, I. Esiyok, D. Jackson, R. Künnemann. *Automated Security Analysis of Exposure Notification Systems*. USENIX Security 2023.
50. ⚠️ CAPEC / CWE 相关条目（CAPEC-512 / 94 / 272 / 90 / 60）

## 附录 B：未核实清单

引用前必须补验：

| 项目 | 状态 |
|---|---|
| Carlsen CSFW 1994 原文全文 | ❌ Unpaywall 确认 closed 且无任何仓储副本；本文第 2.1 节全部分类定义均为二手 |
| Carlsen 博士论文正文、Carlsen OSR 1994 正文 | ❌ |
| Syverson CSFW 1994 原文 | ❌ DTIC 403，IEEE 付费墙 |
| Gritzalis & Spinellis 的 Carlsen 转述是否忠实 | ❌ 需与 Carlsen 原文对照 |
| Boyd & Mathuria 第 1 版 §1.6 正文、Table 1.2 的内容 | ❌ |
| Boyd & Mathuria 第 2 版的汇总表（表号 / 是否保留 / 定义有无改动） | ❌ 不要假设仍是 Table 1.3 |
| Boyd & Mathuria 中独立的 "adversary goals" 清单 | ❌ 第 1 版全文检索 0 命中，倾向于不存在 |
| Heather-Lowe-Schneider 的 JCS 2003 已出版页码 | ❌ 本文页码均为 29 页作者预印本页码 |
| Snekkenes 1992 正文；"单字段与串接混淆"归属于他 | ❌ 仅有 Meadows 的转述 |
| Meadows CSFW 2003 扩展版正文 | ❌ 本文用的是 FCS'02 版 |
| Kaliski 2001 原文；Just & Vaudenay 1996 原文 | ❌ |
| AVISPA D6.1 以外的官方文档 | ❌ 原站已被抢注 |

三处明确不成立的说法，不要引用：

1. **"HLS 承认其定义有争议"** —— 两版全文 grep contentious / debate / disagree / controvers / arguable / "some authors" 零命中。
2. **"parasite flaws 属于 Carlsen 的分类"** —— 任何来源均未见。
3. **Carlsen 的 "Know Your Enemy" 副标题与 Basin & Cremers 同名论文有承继关系** —— TISSEC 2014 全文 0 次提及 Carlsen，属同名而未相互引用。

另有两条来源可靠性提示：`eprint.iacr.org/2002/015`（Jencusová 2002）的 Carlsen 清单含 Clark & Jacob 的 "Freshless" 排印错误，可判定为转抄，不构成独立佐证；搜索引擎摘要曾把 arXiv:2505.10316 与 eprint 2019/779 说成含 attack pattern / classification 表述，全文 grep 证明那是错的。
