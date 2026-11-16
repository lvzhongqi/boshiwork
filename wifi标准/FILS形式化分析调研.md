# FILS 协议形式化分析研究现状调研

- **调研日期**：2026-11-16
- **调研对象**：IEEE 802.11ai-2016 / IEEE 802.11-2024 §12.11 的 FILS（Fast Initial Link Setup）
- **调研问题**：公开文献中，是否有人使用 ProVerif 或其他形式化方法对 FILS 进行分析？覆盖了什么、遗漏了什么？
- **证据口径**：只统计可获取全文或摘要的公开文献；全文阅读标注 **A**，仅摘要标注 **B**，二手转引标注 **C**。

---

## 0. 结论摘要

### 0.1 直接回答

**在可检索到的公开文献中（截至 2026-11-16），没有发现对完整 FILS 协议（802.11ai / 802.11-2024 §12.11）进行 ProVerif、Tamarin、CryptoVerif 或 AVISPA 形式化建模与机器验证的工作。**

最接近“FILS + 形式化方法”的工作只有三类：

1. **Zhang 2018 NTU 博士论文**：用 **BAN 逻辑 + Scyther** 验证其提出的 FKR/SEF 方案。论文中有一张图标题为 “Scyther Tool Verification Result of FILS”，但实际模型是**两消息重认证抽象**（`protocol2`），不是标准 FILS 四帧握手；验证性质仅 `Secret`、`Nisynch` 等。
2. **Zhang & Ma ICC 2018**：用 **BAN 逻辑**分析其面向 802.11ah 的 FILS 认证增强方案。BAN 逻辑是手工逻辑推演，不是机器验证，也不建模状态、重放和密钥安装。
3. **Hoque & Rahbari CNS 2022**：声称“首次形式化建模并分析 Wi-Fi 连接建立阶段”。从摘要看，其对象是**受保护认证之前的非保护管理帧链**（探测/认证/关联），性质集中在 DoS/MitM；是否把 FILS 作为一条并行路径纳入模型，摘要未说明，需全文确认。其后续 WiSec 2023 / TDSC 2025 用 **ProVerif + 模型检测器** 验证自己的 PHY 层前导签名防御，FILS 仅作为动机出现。

此外，**Vanhoef & Piessens CCS 2018（Release the Kraken）** 对 FILS 的 KRACK 分析是**纯人工协议分析**。作者明确写道：

> “A formal analysis of our new countermeasure is unfortunately out of scope for this paper.”

并在结论中呼吁：

> “We believe … (formally) modeling 802.11 would help to better secure both implementations and the standard itself.”

这既证明 FILS 存在已知的密钥重装问题，也说明该问题**没有被形式化工具覆盖**。

### 0.2 五条关键发现

| # | 发现 | 证据 |
|---|---|---|
| 1 | 没有 FILS 的 ProVerif / Tamarin 模型 | OpenAlex、Crossref、arXiv 检索；WPA2 Tamarin 论文全文 0 次 “FILS”；Kraken 全文 26 次但均为人工分析 |
| 2 | 唯一的 Scyther “FILS” 模型是两消息重认证抽象 | NTU 论文 §3.3.2、图 12 与 SPDL 片段（A） |
| 3 | BAN 逻辑分析不覆盖密钥安装 / 重放 | Zhang & Ma ICC'18 摘要（B）；NTU 论文 §2.4.1 自述 KRA 不违反形式化性质（A） |
| 4 | Kraken 的 FILS KRACK 是人工分析，作者明确未做形式化 | CCS'18 §4、§6.3.2（A） |
| 5 | WPA2 的 Tamarin 工作可作为方法模板，但不含 FILS | USENIX'20 全文 0 次 “FILS”（A）；STM'20 摘要（B） |

### 0.3 对我们工作的含义

- **可以主张的新颖性**：
  - 首个覆盖 FILS **密钥建立 + 密钥安装语义** 的 ProVerif 模型；
  - 首个 FILS **PK 证书 / 原始公钥双模式** 形式化分析；
  - 首个 FILS **延迟认证（KeyAuth transcript 绑定）** 形式化分析；
  - 首个 FILS **未认证 M1 的 DoS 可达性** 模型；
  - 首个 FILS **PTK 重装 / KRACK** 的机器可检轨迹。
- **不建议主张**：“首个 FILS 形式化分析”——Zhang 2018 的 Scyther 模型（尽管是抽象）会被审稿人视为 prior art。
- **建议的英文表述**：
  > To the best of our knowledge, this is the first machine-checked analysis of the FILS key establishment and key installation procedures, covering both certificate-based and raw-public-key trust, delayed authentication, and denial-of-service reachability.

---

## 1. 调研方法

### 1.1 数据源

| 数据源 | 用途 | 状态 |
|---|---|---|
| OpenAlex API | 标题/摘要/全文检索、引文 | 可用 |
| Crossref API | 补充书目、摘要 | 可用 |
| arXiv API | 预印本检索 | 可用 |
| 本地 PDF 全文 | Kraken'18、CCS'17、NTU 论文、SEF/WCNC'19 | 可用 |
| Google Scholar | 引文检索 | 网络阻断 |
| Semantic Scholar | 引文/全文 | API 429、网页 403 |
| DBLP | 会议论文 | Anubis 反爬 |
| CNKI / 万方 / 百度学术 | 中文文献 | 安全验证 / JS 渲染 |

### 1.2 检索式（节选）

- `FILS formal verification`
- `802.11ai security analysis`
- `fast initial link setup security`
- `FILS ProVerif` / `FILS Tamarin` / `FILS Scyther`
- arXiv：`all:"FILS" AND all:"formal"`、`all:"802.11" AND all:"ProVerif"`、`all:"802.11" AND all:"Tamarin"`
- OpenAlex：`title_and_abstract.search:"fast initial link setup"`（20 条）、`title_and_abstract.search:"802.11ai"`（16 条）
- 中文：`快速初始链路建立`（OpenAlex 0 条；CNKI/万方未能系统检索）

### 1.3 局限

1. Google Scholar、Semantic Scholar、DBLP、CNKI、万方、百度学术在当前网络环境下不可用或不稳定；**中文期刊、日文 IEICE 文稿、802.11 TGai 提案**可能漏检。
2. “未发现”不等于“不存在”；本报告结论应表述为“在可检索的公开文献中未发现”。
3. 部分 IEEE/ACM 论文只能读到摘要，具体工具与模型细节可能不完整（表中已标注证据等级）。
4. 检索截止日期：2026-11-16。

---

## 2. 文献总表

| # | 工作 | 年份 /  venue | 分析对象 | 方法 / 工具 | 验证或分析目标 | 与 FILS 本体的关系 | 证据 |
|---|---|---|---|---|---|---|---|
| 1 | IEEE 802.11ai-2016 | 2016 标准 | FILS 协议定义 | 无 | 无形式化证明 | 本体 | A |
| 2 | IEEE 802.11-2024 §12.11 | 2024 标准 | FILS 合并版 | 无 | 无形式化证明 | 本体 | A |
| 3 | Vanhoef & Piessens, CCS'17 | 2017 | 4-way handshake | 人工分析 + 实现测试 + **NuSMV（仅反制状态机）** | KRACK | 前 FILS | A |
| 4 | Vanhoef & Piessens, CCS'18 “Kraken” | 2018 | FILS、TPK、4-way（并测试 FT） | 人工协议分析 + 实现测试 | KRACK、重放、PN 复位 | **本体（攻击）** | A |
| 5 | Zhang & Ma, ICC'18 | 2018 | FILS 认证增强（802.11ah） | **BAN 逻辑** | 认证逻辑正确性 | 派生方案 | B |
| 6 | Zhang, NTU 博士论文 | 2018 | FKR、SEF（FILS 派生） | **BAN 逻辑 + Scyther** | Secrecy、Nisynch、Alive、Weakagree、Niagree | 图 12 标为 FILS，实为两消息重认证 | A |
| 7 | Zhang & Ma, WCNC'19 | 2019 | SEF | BAN（Scyther 见博士论文同源版本） | 抗 KRA 的定性论证 | 派生方案 | B |
| 8 | Zhang & Ma, IJCS'19 | 2019 | SEF | BAN（Scyther 见博士论文同源版本） | 抗 KRA、性能 | 派生方案 | B |
| 9 | Zhang & Ma, Computers & Security'19 | 2019 | FKR | BAN/Scyther（同源，见博士论文） | 快速重认证 | 派生方案 | B |
| 10 | Lee & Chung, IJCSEE'15 | 2015 | FILS DoS | 人工协议分析 | ERP Failure、Handshake Corruption | **本体（DoS）** | C |
| 11 | Hoque, Rahbari & Rezendes, CNS'22 | 2022 | Wi-Fi 连接建立阶段 | 形式化建模（摘要未说明工具） | DoS、MitM 变体 | 摘要看是非保护管理帧；FILS 覆盖待全文确认 | B |
| 12 | Hoque & Rahbari, WiSec'23 | 2023 | PHY 层前导签名防御 | 模型检测器 + 密码协议验证器 | 其方案的安全性 | FILS 仅动机 | B |
| 13 | Hoque & Rahbari, TDSC'25 | 2025 | 802.11ax 连接建立防御 | **ProVerif + 模型检测器** | 其方案的安全性 | FILS 仅动机（全文 1 次） | A |
| 14 | He et al., CCS'05 | 2005 | 802.11i + TLS | PCL 组合证明 | 密钥保密、认证 | 前 FILS | B |
| 15 | Cremers, Kiesl & Medinger, USENIX Sec'20 | 2020 | WPA2 4-way / group key / WNM | **Tamarin** | 首个能检测 KRACK 的模型 | 非 FILS | A |
| 16 | Singh et al., STM'20 | 2020 | 802.11 4-way | **Tamarin** | 标准性质不足；新增性质 | 非 FILS | B |
| 17 | Metere et al., arXiv 2026 | 2026 | WPA3 SAE | **ProVerif + ASMETA** | 通信逻辑 + 状态机 | 非 FILS | B |
| 18 | Shen, Karim & Bertino, arXiv 2024 | 2024 | Wi-Fi 分片 / 省电 | **Tamarin** | 68 条功能性质 | 非 FILS | B |
| 19 | Dragonstar, arXiv 2023 | 2023 | WPA3 Dragonfly 实现 | HACL* 形式化验证实现 | 侧信道 / 实现正确性 | 非 FILS | B |
| 20 | 本工作 ProVerif 模型集 | 2026 | FILS PK/SK、证书/原始公钥、延迟认证、DoS、KRACK | **ProVerif 2.05** | 机密性、认证、单射、PTK 一致性/唯一性、UKS、可达性 | **本体** | A |

---

## 3. 逐项评述

### 3.1 标准与产业侧

IEEE 802.11ai-2016 只给出协议流程、状态机、帧格式和密钥派生规则，没有任何形式化安全证明；IEEE 802.11-2024 §12.11 是合并版，同样没有。Wi-Fi Alliance 的认证是互操作与一致性测试，不是形式化验证。

因此，**FILS 的安全性质在标准层面是“设计论证 + 实现测试”，不是“机器验证”**。这为后续学术分析留下了空间，也意味着标准文本中的歧义（例如 FILS Session 的语义、KeyAuth 的 transcript 范围、PTK 何时安装）不会被标准本身消除。

### 3.2 Kraken CCS'18：唯一的 FILS KRACK 分析，但是人工的

**论文**：Mathy Vanhoef, Frank Piessens, “Release the Kraken: New KRACKs in the 802.11 Standard”, CCS 2018, DOI 10.1145/3243734.3243807。

**贡献**：
- 系统扫描 802.11 中所有协商/管理密钥的握手；
- 发现 **FILS** 与 **TPK** 也可被密钥重装攻击；
- 给出 FILS KRACK 的 4 阶段攻击流程（Figure 6：重放 `(Re)Association Request` → AP 重发 `(Re)Association Response` 并重装 PTK → PN/nonce 复位）；
- 讨论标准层面的反制（重放计数器、密钥安装状态机）。

**与形式化方法的关系**：
- 全文没有 ProVerif、Tamarin、Scyther、AVISPA、CryptoVerif 或模型检测；
- 作者在 §6.3.2 明确说新反制的形式化分析 “out of scope”；
- 作者在 §9 结论中把“对 802.11 做形式化建模”列为未来方向。

**意义**：Kraken 证明了 FILS 的**协议设计层**存在密钥重装问题，但它没有给出机器可检的模型或轨迹。我们的 `FILS_KRACK_PTK_good/bad.pv` 正好补上“机器可检轨迹”这一环。

> 注意：Kraken 的攻击依赖“AP 在收到重放的 `(Re)Association Request` 时再次安装同一 PTK”。这属于**状态机/密钥安装时机**问题，而不是密钥派生或认证逻辑问题。Scyther/BAN 这类只建模消息逻辑的工具天然看不到它。

### 3.3 Zhang 系列：最接近“FILS + 形式化”的工作

这是目前唯一直接对 FILS 派生方案做机器辅助验证的学术线索。作者 Lyuye Zhang（NTU）与 Maode Ma 围绕 802.11ah 的 FILS 认证增强发表了多篇论文。

#### 3.3.1 ICC 2018：BAN 逻辑分析 FILS 增强

**论文**：Lyuye Zhang, Maode Ma, “Performance and Security Enhancements to Fast Initial Link Setup in IEEE 802.11ah Wireless Networks”, IEEE ICC Workshops 2018, DOI 10.1109/ICCW.2018.8403746。

**方法**：BAN 逻辑。

**对象**：作者提出的 FILS 认证增强方案（面向 802.11ah 低功耗设备），不是标准 FILS 本体。

**验证内容**：BAN 逻辑的“信仰/管辖权”推理，证明双方相信协商出的密钥、nonce 等。

**局限**：
- BAN 逻辑是手工推演，不是机器验证；
- 需要对协议做“理想化”，容易把不安全细节理想化掉；
- 不建模状态、重放、密钥安装、并发会话；
- 不提供攻击轨迹。

#### 3.3.2 NTU 博士论文 2018：BAN + Scyther

**论文**：Lyuye Zhang, “Design of efficient and secure authentication schemes in IEEE 802.11ah networks”, NTU, 2018, DOI 10.32657/10356/75846。

论文提出两个方案：

1. **FKR**（Fast Key Re-authentication）：两消息重认证，用 PMK 和旧 SNonce/ANonce 先算 `N′`，再用新 nonce `NS` 派生新 PTK；
2. **SEF**（Secure and Efficient FILS）：五消息、三方（STA/AP/AS）的 FILS 替代方案，声称抗 KRA。

**形式化部分**：
- 第 3 章 FKR：BAN 逻辑 + Scyther；
- 第 4 章 SEF：BAN 逻辑 + Scyther；
- Scyther 模型使用 SPDL，角色为 `I`/`R`（FKR）或 `STA`/`AP`/`AS`（SEF）。

**关键细节（FKR 的 Scyther 模型）**：

```text
protocol protocol2(I, R) {
  role I {
    fresh ni: Nonce;
    var nr: Nonce;
    var ptk2: Key;
    match(ptk2, prf(hash(nonceold, ni), k));
    send_1(I, R, { ni, I, {nonceold}ptk2 }k);
    recv_2(R, I, { nr, R }ptk2);
    claim_i1(I, Secret, ptk2);
    claim_i2(I, Nisynch);
  }
  role R { ... }
}
```

它只有**两条消息**，PTK2 = `prf(hash(nonceold, ni), k)`；验证的 claim 是 `Secret(ptk2)` 与 `Nisynch`（以及 Scyther 自动生成的 Aliveness / Weakagree / Niagree）。

论文图 12 的标题写作 “Scyther Tool Verification Result of FILS”，但正文明确说该模型是 `protocol2`、用于 FKR 的**重认证**过程，且“不需要 AS 再次认证，只有两方参与”。因此：

> **这不是标准 FILS 四帧握手的模型，而是 FILS 派生出的两消息重认证抽象。**

**SEF 的 Scyther 模型**：
- 三方 `STA`/`AP`/`AS`；
- 使用 `k(STA,AS)`、`k(AP,AS)` 共享密钥和 ticket `T1`/`T2`；
- PTK 由 AS 新鲜生成并分发；
- claims 包括 `Secret(N/AN/SN/GTK/PTK)`、`Alive`、`Weakagree`、`Niagree`、`Nisynch`。

**评价**：
- 这是目前**唯一**能被称为“FILS 派生方案的机器辅助验证”的工作；
- 但它验证的是**作者自己的简化方案**，不是 802.11ai/2024 的标准 FILS；
- 抽象层级是 Dolev-Yao 完美密码，未建模 AES-SIV/AEAD、KeyAuth 的具体 transcript、证书链、原始公钥、FILS Session、GTK/IGTK/BIGTK；
- 没有建模“密钥何时安装”，因此**不可能发现 KRACK**；
- 论文 §2.4.1 自己也承认：“KRA just relays messages and does not change any bit of them. Consequently, KRA does not theoretically violate formal security properties.” 这句话正好说明：**传统形式化性质（secrecy/authentication）与抗重装是两回事**。

#### 3.3.3 SEF 的期刊/会议版

- **WCNC 2019**：Lyuye Zhang, Maode Ma, “Secure and Efficient Fast Initial Link Setup Scheme Design”, DOI 10.1109/WCNC.2019.8885719。
- **IJCS 2019**：Lyuye Zhang, Maode Ma, “Secure and efficient scheme for fast initial link setup against key reinstallation attacks in IEEE 802.11ah networks”, DOI 10.1002/dac.4192。

两篇都提出 SEF，声称“eradicate potential threats from KRAs without degrading performance”。从摘要看，安全论证仍是**定性分析 + BAN（Scyther 见博士论文同源版本）**；没有给出针对 KRACK 的机器验证轨迹。

#### 3.3.4 FKR 期刊版

- **Computers & Security 2019**：Lyuye Zhang, Maode Ma, “FKR: An efficient authentication scheme for IEEE 802.11ah networks”, DOI 10.1016/j.cose.2019.101633。

同样属于 FILS 派生方案，不是标准 FILS 本体。

### 3.4 Hoque & Rahbari 系列：连接建立阶段，不是 FILS 密钥建立

#### 3.4.1 CNS 2022

**论文**：Naureen Hoque, Hanif Rahbari, C. Rezendes, “Systematically Analyzing Vulnerabilities in the Connection Establishment Phase of Wi-Fi Systems”, IEEE CNS 2022, DOI 10.1109/CNS56114.2022.9947252。

**摘要要点**：
- “first to formally model and analyze this connection establishment phase, based on the latest IEEE 802.11 standard”；
- 发现一个新的 DoS 漏洞和三个已知 MitM 的新变体；
- 形式化说明可选的操作信道验证（OCV）只能防多信道 MitM；
- 在 `wpa_supplicant` 上验证 DoS。

**与 FILS 的关系**：
- 从摘要看，其对象是**受保护认证之前的非保护管理帧链**（探测、开放认证、关联）；
- 摘要没有声称覆盖 FILS 的 4 帧快速认证/密钥建立，也没有提到 KeyAuth/PTK 安装；
- 摘要未说明具体工具；同组后续论文使用 ProVerif + 模型检测器。

**判断**：这是“Wi-Fi 连接建立”的形式化工作，性质集中在 DoS/MitM；是否把 FILS 纳入模型需要全文确认。即使纳入，其性质也不覆盖 FILS 的 KeyAuth transcript、证书/原始公钥和 PTK 安装。若审稿人引用，需要按全文范围区分。

#### 3.4.2 WiSec 2023

**论文**：Naureen Hoque, Hanif Rahbari, “Countering Relay and Spoofing Attacks in the Connection Establishment Phase of Wi-Fi Systems”, WiSec 2023, DOI 10.1145/3558482.3590185。

**摘要要点**：
- 在 PHY 层前导信号中嵌入 AP 的数字签名/MAC；
- 用“模型检测器 + 密码协议验证器”对其方案做形式化安全分析；
- 在商用 AP + USRP 测试床上评估。

**与 FILS 的关系**：FILS 仅作为“快速链路建立”的背景动机；不是对 FILS 的分析。

#### 3.4.3 TDSC 2025

**论文**：Naureen Hoque, Hanif Rahbari, “Locking Down Relay and Spoofing Attacks During Concurrent Connection Establishments in 802.11ax”, IEEE TDSC 2025, DOI 10.1109/TDSC.2025.3596245；arXiv:2501.01517。

**全文核查**：
- 使用 **ProVerif**（4 次提及）和**符号模型检测**（FSM）；
- 对“前导签名切片 + 时间约束”的方案做端到端形式化；
- 全文只有 **1 次**提及 FILS，且是 “IEEE 802.11ai goal for fast link setup (FILS)” 的动机句。

**判断**：不是 FILS 分析。

### 3.5 WPA2 的形式化工作：方法论模板，但不是 FILS

#### 3.5.1 He et al. CCS 2005

**论文**：Changhua He, Mukund Sundararajan, Anupam Datta, Ante Derek, John C. Mitchell, “A modular correctness proof of IEEE 802.11i and TLS”, CCS 2005, DOI 10.1145/1102120.1102124。

**方法**：Protocol Composition Logic（PCL）。

**对象**：802.11i 的 4-way handshake、group key handshake、TLS。

**意义**：这是 WPA2 核心握手的经典形式化正确性证明。Kraken 论文明确指出：**这些证明没有建模“密钥何时安装”**，所以 KRACK 不违反它们证明的性质。这一点对 FILS 同样成立。

#### 3.5.2 Cremers, Kiesl & Medinger, USENIX Security 2020

**论文**：“A Formal Analysis of IEEE 802.11's WPA2: Countering the Kracks Caused by Cracking the Counters”, USENIX Security 2020。

**方法**：**Tamarin**。

**贡献**：
- 首个**细节足够检测 KRACK** 的 WPA2 形式化模型；
- 覆盖 4-way、group-key、WNM sleep 等机制的交互；
- 说明标准补丁为什么不足，并给出修复。

**与 FILS 的关系**：全文 **0 次** “FILS”。它是“如何为 Wi-Fi 握手建模密钥安装/重放”的最佳方法模板，但没有覆盖 FILS。

#### 3.5.3 Singh et al., STM 2020

**论文**：Rajiv Ranjan Singh, José Moreira, Tom Chothia, Mark D. Ryan, “Modelling of 802.11 4-Way Handshake Attacks and Analysis of Security Properties”, STM 2020, LNCS 12386, DOI 10.1007/978-3-030-59817-4_1。

**方法**：**Tamarin**。

**贡献**：
- 首个用形式化方法系统回答“KRACK 是违反标准性质，还是标准性质本身不足”的工作；
- 发现：**能复现 KRACK 的 Tamarin 模型并不违反标准规定的安全性质**；
- 提出额外性质，并证明该性质能阻止 KRACK。

**启示**：FILS 也需要“标准性质之外”的**密钥安装/重放性质**；仅验证 secrecy/authentication 不够。这与我们 `FILS_KRACK_PTK_*` 的设计思路一致。

#### 3.5.4 Vanhoef & Piessens, CCS 2017：NuSMV 验证的是反制，不是协议

**论文**：Mathy Vanhoef, Frank Piessens, “Key Reinstallation Attacks: Forcing Nonce Reuse in WPA2”, CCS 2017, DOI 10.1145/3133956.3134027。

**方法**：人工攻击 + 对**反制状态机**做 NuSMV 符号模型检测。

**关键区别**（容易与 Kraken 混淆）：

- CCS'17 的 NuSMV 模型只覆盖 **4-way handshake 的“密钥只安装一次”布尔标志状态机**，用来证明该反制能阻止重装；
- 它**不建模**协议消息、密码原语、FILS，也不产生“攻击轨迹”；
- CCS'18（Kraken）才把攻击扩展到 FILS/TPK，且**没有**对 FILS 反制作形式化分析（§6.3.2 明确 out of scope）。

**对 FILS 的启示**：Kraken 提出的两条反制——(a) 密钥在一次握手中只安装一次，(b) 组密钥重放计数器单调递增——在 FILS 上的正确性**从未被模型检测**。我们的 `FILS_KRACK_PTK_good.pv` 正是对 (a) 在 FILS 语义下的 ProVerif 版本，可作为 NuSMV 结论在 FILS 上的补充而非重复。

### 3.6 其他 Wi-Fi 形式化工作（均非 FILS）

| 工作 | 方法 | 对象 | 与 FILS 的距离 |
|---|---|---|---|
| Metere et al., “What a Mesh”, arXiv:2603.23352, 2026 | ProVerif + ASMETA | WPA3 SAE 的通信逻辑 + 状态机 | 方法最接近（双层次建模），但对象是 SAE |
| Shen, Karim & Bertino, arXiv:2312.07877, 2024 | Tamarin | Wi-Fi 分片、省电模式 | 功能性质，不是认证/密钥建立 |
| Dragonstar, arXiv:2307.09243, 2023 | HACL* 形式化验证实现 | WPA3 Dragonfly 的数学运算 | 实现级验证，不是协议级 |
| Hoque & Rahbari, CNS'22/WiSec'23/TDSC'25 | 形式化建模 + ProVerif + MC | 连接建立/PHY 防御 | 不覆盖 FILS 密钥建立 |

**最值得借鉴的是 “What a Mesh”**：它同时建模**通信逻辑**（ProVerif）和**设备状态机**（ASMETA），并因此发现了单靠消息逻辑看不到的问题。FILS 的 KRACK 正是“消息逻辑正确、状态机错误”的典型，因此“ProVerif + 状态机/模型检测”的双层路线是后续工作的自然方向。

### 3.7 非形式化的 FILS 安全/性能文献

这些工作不构成形式化 prior art，但可作为背景与威胁模型来源：

- **S. Lee, B. H. Chung**, “Denial of Service Attack against IEEE 802.11 WLAN Fast Initial Link Setup Technology”, IJCSEE 2015, 3(4):335–337：人工分析 FILS 的 ERP Failure Attack 与 FILS Handshake Corruption Attack。
- **Eng Hwee Ong**, “Performance analysis of fast initial link setup for IEEE 802.11ai WLANs”, PIMRC 2012：性能分析。
- **Kushida et al.**, “On the effectiveness of FILS in IEEE 802.11ad wireless networks”, APCC 2017：性能/适用性。
- **Kato et al.**, “Link Setup Time Reduction by FILS on IEEE 802.11-Based Inter-Vehicular Communications”, IEEE Access 2021：性能。
- **Giuseppe Marini**, “Implementazione e Validazione Sperimentale del Protocollo IEEE 802.11ai (FILS)”, Bologna 2026：实现与实验验证，不是形式化。
- **IEEE 802.11-2024 §12.11**：协议定义与状态机，不含证明。

---

## 4. 覆盖矩阵

图例：**✅** 覆盖；**◐** 部分覆盖/仅抽象；**✗** 未覆盖；**—** 不适用。

| 能力 / 性质 | Kraken'18（人工） | Zhang'18（Scyther/BAN） | Hoque'22（连接建立） | WPA2 Tamarin'20 | 本工作 ProVerif |
|---|---|---|---|---|---|
| FILS SK（ANA=4/5） | ◐（攻击示例用 rRK） | ✗ | ✗ | — | ✅ |
| FILS PK（DH） | ◐（同一 4 帧结构） | ✗ | ✗ | — | ✅ |
| 证书链 + 主体绑定 | ✗ | ✗ | ✗ | — | ✅ |
| 原始公钥固定（无证书） | ✗ | ✗ | ✗ | — | ✅ |
| ERP / rRK / rMSK | ◐（背景） | ◐（SEF 使用 rIK/rRK） | ✗ | — | ✅ |
| PTK 派生 | ◐ | ◐（`prf(hash(...))`） | ✗ | ◐（4-way） | ✅ |
| KeyAuth transcript 绑定 | ◐（描述 HMAC 输入） | ✗ | ✗ | — | ✅ |
| (Re)Assoc + GTK | ✅（攻击路径） | ◐（SEF 分发 GTK） | ✗ | ◐（group key） | ✅ |
| 密钥安装时机 / 状态机 | ✅（攻击核心） | ✗ | ✗ | ✅ | ✅ |
| 重放 / PN 复位 | ✅（攻击核心） | ✗ | ✗ | ✅ | ✅ |
| 延迟认证 / UKS | ✗ | ✗ | ✗ | — | ✅ |
| 未认证 M1 的 DoS 可达性 | ◐（提及资源消耗） | ✗ | ◐（DoS，但非 FILS） | — | ✅ |
| PFS | ✗ | ✗ | ✗ | — | ✅（PK/SK5；SK4 预期不成立） |
| PMKID 隐私/链接性 | ✗ | ✗ | ✗ | — | ✅ |
| GTK rekey 重放 | ◐（group key） | ✗ | ✗ | ✅ | ✅ |
| 多 AP / FT / PMKSA 缓存 | ◐（FT 背景） | ◐（802.11ah 缓存） | ✗ | — | ◐ |
| 实现一致性/代码级 | ◐（hostapd） | ✗ | ◐（wpa_supplicant） | ✗ | ✗ |

**矩阵结论**：
- Kraken 覆盖“攻击面”，但不提供模型；
- Zhang 覆盖“消息逻辑的 secrecy/authentication”，但不覆盖状态/安装/重放；
- Hoque 覆盖“连接建立的前置帧”，不覆盖 FILS 密钥建立；
- WPA2 Tamarin 覆盖“4-way 的安装/重放”，但对象不是 FILS；
- 我们的 ProVerif 模型是唯一同时覆盖 FILS 本体、PK 双模式、延迟认证、DoS 和 PTK 重装的组合。

---

## 5. 研究空白

按“重要性 × 可发表性”排序：

### G1. 完整 FILS 本体的机器验证

- **现状**：没有 ProVerif/Tamarin 模型覆盖 802.11ai/2024 的完整 4 帧流程（AuthReq/AuthResp/(Re)AssocReq/(Re)AssocResp）。
- **难点**：FILS 同时包含 SK（PMK/rRK/rMSK）与 PK（DH/证书/原始公钥）、ERP、GTK/IGTK/BIGTK、FILS Session、AAD、KeyAuth、PMKSA 缓存。
- **可做**：以 802.11-2024 §12.11 为唯一文本依据，建立“标准条款 → 模型规则”的映射表；对每条性质给出“标准是否要求”的判定。

### G2. 密钥安装语义与 KRACK

- **现状**：Kraken 人工发现 FILS KRACK；Zhang 的 Scyther 模型明确不建模安装；WPA2 Tamarin 只覆盖 4-way。
- **可做**：
  - 在 ProVerif 中用 `ApInstalls` / `ApReinstalls` 事件 + 会话去重规则建模；
  - 用 Tamarin 的 global state / locks 建模 AP 的“已安装/等待/完成”状态；
  - 证明“无重放计数器 + 成功关联删除旧 PTKSA” ⇒ 重装可达。
- **我们已有**：`FILS_KRACK_PTK_good.pv` / `_bad.pv`，good 版 `ApReinstalls` 不可达，bad 版可达。

### G3. 重放计数器缺失与 PN 复位

- **现状**：802.11-2024 FILS 仍无重放计数器；FILS Session 只是 8 字节标识；AEAD AAD 不含序列号。
- **可做**：把“同一 `(Re)Association Request` 原样重放”与“新会话但相同 PTK”区分；证明前者在合规实现下只触发缓存重发，后者才会重装。
- **注意**：ProVerif 不能直接建模 PN 复位；需要把“重装事件”作为 PN 复位的充分条件，并在文档中说明这一抽象。

### G4. PK 信任模式：证书链 vs 原始公钥

- **现状**：Kraken 指出“公钥认证没有关于如何/何时信任公钥的指南”；标准没有规定证书链校验和主体绑定。
- **可做**：
  - 证书模式：链验证 + `Subject == 期望对端` + KeyAuth 覆盖完整 transcript；
  - 原始公钥模式：预置/固定公钥（Key Type=2/3），禁止 TOFU；
  - 证明“只验证书链、不验主体”会导致冒充/GTK 泄露。
- **我们已有**：`FILS_PK_CERT*`、`FILS_PK_RAW*`。

### G5. 延迟认证与 UKS

- **现状**：FILS 允许 STA 在收到 M2 后才验证 AP 的认证器（延迟认证）；若 KeyAuth 不绑定 `gSTA/gAP`，会出现 UKS/密钥确认错绑。
- **可做**：证明 KeyAuth 必须覆盖 `gSTA/gAP/SNonce/ANonce/identities/Session`；仅靠 AEAD 不够。
- **我们已有**：`FILS_LATEAUTH*`。

### G6. DoS 可达性

- **现状**：M1 未认证，AP 必须先做 DH/状态分配；Lee & Chung 人工分析了 ERP Failure / Handshake Corruption；没有形式化可达性模型。
- **可做**：用 ProVerif 的 reachability（`event(ApWork) ==> event(StaStart)`）证明“未认证的昂贵工作可达”；再结合工程层的速率限制/状态上限讨论实际影响。
- **我们已有**：`FILS_DOS_UNAUTH.pv`。

### G7. 组密钥与 IGTK/BIGTK

- **现状**：802.11-2024 §12.11.2.1 只强制 GTK/IGTK/BIGTK/WIGTK 抗重装，未强制 PTK；组密钥 rekey 的 KeyID/epoch 校验是实现相关。
- **可做**：分别建模 GTK/IGTK/BIGTK 的安装与 rekey，证明“不校验 KeyID/epoch ⇒ 旧组密钥被接受”。

### G8. 多 AP、FT、PMKSA 缓存

- **现状**：FILS 常与 802.11r FT、PMKSA 缓存、ERP 一起部署；跨 AP 的 rRK/rMSK 分发、缓存不同步、PMKID 链接性都缺少形式化。
- **可做**：扩展为多 AP 模型；证明缓存不同步只导致失败、不产生错配 PTK；分析 PMKID 的可链接性。

### G9. 计算模型与实现级验证

- **现状**：现有工作都是符号模型（Dolev-Yao）；没有 CryptoVerif/EasyCrypt 的 FILS 计算可靠性证明。
- **可做**：对 AES-SIV/AEAD、HKDF、HMAC 的组合做计算模型证明；或用 HACL*/Dragonstar 路线验证实现。

### G10. 标准文本的歧义与实现一致性

- **现状**：Kraken 指出标准对“重放计数器接受哪些值”“密钥何时安装”存在歧义；FILS Session 的语义也不够精确。
- **可做**：把标准条款转成可执行的 state machine（ASMETA/SPIN/Tamarin），做“标准 ↔ 实现”一致性测试；这与 “What a Mesh” 的路线一致。

---

## 6. 我们工作的定位

### 6.1 已有模型与结果（ProVerif 2.05）

| 模型 | 覆盖内容 | 结果 |
|---|---|---|
| `FILS_PK.pv` | FILS PK（无缓存 F / 缓存 C）：GTK/TK/缓存 PMK 保密、双向认证、单射、PTK 一致性/唯一性、UKS、缓存一致性 | 17/17 **true** |
| `FILS_SK.pv` | FILS SK（ANA=4/5/5C）：GTK/TK/PMK/rMSK 保密、双向认证、单射、PTK 一致性/唯一性、UKS、跨 AKM 分离 | 22/22 **true** |
| `FILS_PFS.pv` | 前向保密：PK、SK5、SK4 | PK true、SK5 true、SK4 **false（预期）** |
| `FILS_PK_CERT.pv` / `_bad.pv` | 证书链 + 主体绑定 + KeyAuth / 只验证书链 | 7/7 true / 7/7 **false** |
| `FILS_PK_RAW.pv` / `_bad.pv` | 预置原始公钥 / 信任报文中的公钥 | 7/7 true / 7/7 **false** |
| `FILS_LATEAUTH.pv` / `_nobind.pv` | KeyAuth 覆盖完整 transcript / 漏掉 `gSTA/gAP` | 7/7 true / PTK 一致性 **false** |
| `FILS_DOS_UNAUTH.pv` | 未认证 M1 迫使 AP 做 DH/状态分配 | `ApWork ==> StaStart` **false**；`ApFinish ==> ApWork` true |
| `FILS_KRACK_PTK_good.pv` / `_bad.pv` | 按 FILS Session 去重 / 不去重，重放 `(Re)Assoc` | good：`not ApReinstalls` **true**；bad：该查询 **false（重装可达）** |
| `FILS_GTK_REPLAY_*` | GTK rekey 校验 / 不校验 KeyID/epoch | good true / bad 重放被接受 |
| `FILS_EAPRP_SEQ_*` | ERP PMK SEQ 校验 / 不校验 | good true / bad PMK 重用 |
| `FILS_PMKID_LINK.pv` | PMKID 链接性 | **false（可链接）** |
| `FILS_STATUS.pv` / `_faulty.pv` | 伪造 status / 失败回退旧密钥 | DoS 可达 / 回退可达 |

### 6.2 新颖性表述建议

**可以写**：

- “We present ProVerif models of FILS PK and SK that, for the first time, cover both certificate-based and raw-public-key trust, delayed authentication, and key installation.”
- “We give the first machine-checked trace of the FILS PTK reinstallation attack and show that a session-based replay check eliminates it.”
- “We give the first formal reachability model of the unauthenticated FILS M1 work amplification.”

**不要写**：

- “This is the first formal analysis of FILS.”（Zhang 2018 的 Scyther 模型会被视为反例）
- “No one has formally analyzed FILS.”（同上）

**折中写法**：

> “While a Scyther model of a two-message FILS-derived re-authentication protocol exists, to our knowledge no prior work provides a machine-checked model of the standard FILS key establishment and installation procedures.”

### 6.3 审稿人可能引用的 prior art 与区分话术

| 审稿人可能说 | 我们的区分 |
|---|---|
| “Zhang 2018 已经用 Scyther 验证了 FILS。” | 那是两消息 FKR 重认证抽象（`protocol2`），不是标准四帧 FILS；只验证 `Secret`/`Nisynch`，不含 KeyAuth/AEAD/证书/原始公钥/密钥安装。 |
| “Kraken 已经分析了 FILS KRACK。” | Kraken 是人工分析，没有模型或机器可检轨迹；作者明确说形式化分析 out of scope。我们给出 ProVerif 轨迹与修复验证。 |
| “Hoque & Rahbari 已经形式化分析了连接建立。” | 其对象是受保护认证前的非保护管理帧，性质是 DoS/MitM；是否覆盖 FILS 需全文确认。即使覆盖，也不含 KeyAuth/证书/PTK 安装。其后续工作验证的是 PHY 前导签名方案。 |
| “WPA2 的 Tamarin 工作已经覆盖了 KRACK。” | 对象是 4-way/group key，不是 FILS；FILS 无重放计数器、FILS Session 语义不同、PK 模式不同。 |
| “BAN 逻辑已经证明了 FILS 增强方案。” | BAN 是手工逻辑，不建模状态/重放/安装；不能发现 KRACK。 |

### 6.4 建议补强的实验（提高可信度/可发表性）

1. **Tamarin 交叉验证**：用 Tamarin 的 global state 建模 AP 的 `INSTALLED`/`WAIT_M4` 状态，独立复现 `FILS_KRACK_PTK_bad` 的轨迹；与 ProVerif 结果互证。
2. **状态机层**：把 802.11-2024 §12.11 的 AP/STA 状态机抽成 ASMETA/SPIN 模型，验证“成功关联删除旧 PTKSA”与“缓存重发”的交互。
3. **计算模型**：对 AES-SIV/AEAD + HKDF 的组合做 CryptoVerif 证明，或至少讨论符号模型的可靠性假设。
4. **实现一致性**：用 hostapd/wpa_supplicant 的实际代码路径核对“重放 `(Re)Assoc` 是否触发重新装钥”，把模型事件映射到代码行。
5. **标准条款映射表**：每条 ProVerif 规则标注对应的 802.11-2024 条款/页码，方便审稿人核对。

---

## 7. 结论

1. **在可检索的公开文献中，FILS 的完整协议没有被 ProVerif/Tamarin/CryptoVerif/AVISPA 形式化分析过。**
2. 唯一直接相关的机器辅助验证是 **Zhang 2018 的 Scyther 模型**，但它是 FILS 派生的两消息重认证抽象，且不覆盖密钥安装/重放。
3. **Kraken CCS'18** 是 FILS KRACK 的权威人工分析，明确未做形式化，并呼吁对 802.11 做形式化建模。
4. **WPA2 的 Tamarin 工作**（Cremers 2020；Singh 2020）证明了“传统 secrecy/authentication 性质不足以捕获 KRACK”，这为 FILS 的“密钥安装性质”提供了方法论依据。
5. 我们的 ProVerif 工作在**覆盖范围**上填补了空白：FILS 本体、PK 双模式、延迟认证、DoS、PTK 重装。论文中应把“首个”限定在“密钥建立 + 密钥安装语义”，而不是“首个 FILS 形式化分析”。

---

## 8. 参考文献

1. IEEE Std 802.11ai-2016, “Amendment 1: Fast Initial Link Setup,” DOI: 10.1109/IEEESTD.2016.7792308.
2. IEEE Std 802.11-2024, “Wireless LAN Medium Access Control (MAC) and Physical Layer (PHY) Specifications,” §12.11.
3. M. Vanhoef and F. Piessens, “Key Reinstallation Attacks: Forcing Nonce Reuse in WPA2,” CCS 2017, DOI: 10.1145/3133956.3134027.
4. M. Vanhoef and F. Piessens, “Release the Kraken: New KRACKs in the 802.11 Standard,” CCS 2018, DOI: 10.1145/3243734.3243807.
5. L. Zhang and M. Ma, “Performance and Security Enhancements to Fast Initial Link Setup in IEEE 802.11ah Wireless Networks,” IEEE ICC Workshops 2018, DOI: 10.1109/ICCW.2018.8403746.
6. L. Zhang, “Design of efficient and secure authentication schemes in IEEE 802.11ah networks,” Ph.D. thesis, NTU, 2018, DOI: 10.32657/10356/75846.
7. L. Zhang and M. Ma, “Secure and Efficient Fast Initial Link Setup Scheme Design,” IEEE WCNC 2019, DOI: 10.1109/WCNC.2019.8885719.
8. L. Zhang and M. Ma, “Secure and efficient scheme for fast initial link setup against key reinstallation attacks in IEEE 802.11ah networks,” Int. J. Commun. Syst., 2019, DOI: 10.1002/dac.4192.
9. L. Zhang and M. Ma, “FKR: An efficient authentication scheme for IEEE 802.11ah networks,” Computers & Security, 2019, DOI: 10.1016/j.cose.2019.101633.
10. S. Lee and B. H. Chung, “Denial of Service Attack against IEEE 802.11 WLAN Fast Initial Link Setup Technology,” IJCSEE, 3(4):335–337, 2015.
11. N. Hoque, H. Rahbari, and C. Rezendes, “Systematically Analyzing Vulnerabilities in the Connection Establishment Phase of Wi-Fi Systems,” IEEE CNS 2022, DOI: 10.1109/CNS56114.2022.9947252.
12. N. Hoque and H. Rahbari, “Countering Relay and Spoofing Attacks in the Connection Establishment Phase of Wi-Fi Systems,” ACM WiSec 2023, DOI: 10.1145/3558482.3590185.
13. N. Hoque and H. Rahbari, “Locking Down Relay and Spoofing Attacks During Concurrent Connection Establishments in 802.11ax,” IEEE TDSC 2025, DOI: 10.1109/TDSC.2025.3596245; arXiv:2501.01517.
14. C. He, M. Sundararajan, A. Datta, A. Derek, and J. C. Mitchell, “A modular correctness proof of IEEE 802.11i and TLS,” CCS 2005, DOI: 10.1145/1102120.1102124.
15. C. Cremers, B. Kiesl, and N. Medinger, “A Formal Analysis of IEEE 802.11's WPA2: Countering the Kracks Caused by Cracking the Counters,” USENIX Security 2020.
16. R. R. Singh, J. Moreira, T. Chothia, and M. D. Ryan, “Modelling of 802.11 4-Way Handshake Attacks and Analysis of Security Properties,” STM 2020, LNCS 12386, DOI: 10.1007/978-3-030-59817-4_1.
17. R. Metere, M. Lilli, L. Arnaboldi, and E. Riccobene, “What a Mesh: Formal Security Analysis of WPA3 SAE Wireless Authentication,” arXiv:2603.23352, 2026.
18. Z. Shen, I. Karim, and E. Bertino, “Segment-Based Formal Verification of WiFi Fragmentation and Power Save Mode,” arXiv:2312.07877, 2024.
19. E. H. Ong, “Performance analysis of fast initial link setup for IEEE 802.11ai WLANs,” IEEE PIMRC 2012, DOI: 10.1109/PIMRC.2012.6362543.
20. H. Kushida, H. Mano, M. Takai, Z. Liu, and S. Ishihara, “On the effectiveness of FILS in IEEE 802.11ad wireless networks,” APCC 2017, DOI: 10.23919/APCC.2017.8304047.
21. A. Kato et al., “Link Setup Time Reduction by FILS on IEEE 802.11-Based Inter-Vehicular Communications,” IEEE Access 2021, DOI: 10.1109/ACCESS.2021.3128974.
22. G. Marini, “Implementazione e Validazione Sperimentale del Protocollo IEEE 802.11ai (FILS),” University of Bologna, 2026.

---

## 附录 A：Zhang 2018 的 Scyther 模型（整理版）

> 说明：以下按原文 SPDL 整理，去除了 PDF 双栏抽取造成的乱序；只保留 FKR 的两消息结构。

```text
hashfunction hash;
usertype Key;
const nonceold: Nonce;
const k: Key;
const prf: Function;

protocol protocol2(I, R) {
  role I {
    fresh ni: Nonce;
    var nr: Nonce;
    var ptk2: Key;
    match(ptk2, prf(hash(nonceold, ni), k));
    send_1(I, R, { ni, I, {nonceold}ptk2 }k);
    recv_2(R, I, { nr, R }ptk2);
    claim_i1(I, Secret, ptk2);
    claim_i2(I, Nisynch);
  }
  role R {
    var ni: Nonce;
    fresh nr: Nonce;
    var ptk2: Key;
    recv_1(I, R, { ni, I, {nonceold}ptk2 }k);
    match(ptk2, prf(hash(nonceold, ni), k));
    send_2(R, I, { nr, R }ptk2);
    claim_r1(R, Secret, ptk2);
    claim_r2(R, Nisynch);
  }
}
```

**解读**：

- `nonceold` 是常量，代表旧 nonce；`k` 是长期共享密钥；
- 新 PTK 由 `prf(hash(nonceold, ni), k)` 派生；
- 只有两条消息，没有 ANonce/SNonce 的完整交换、没有 KeyAuth、没有 AEAD/AES-SIV、没有证书/原始公钥、没有 FILS Session；
- `Secret` 只证明 PTK 不被攻击者获得；`Nisynch` 只证明事件顺序一致；二者都不约束“PTK 被安装几次”。

## 附录 B：检索记录（节选）

| 查询 | 数据源 | 命中 | 备注 |
|---|---|---|---|
| `FILS formal verification` | OpenAlex | 15,899（模糊） | 前 15 条无 FILS 相关 |
| `802.11ai security analysis` | OpenAlex | 63 | 仅 Zhang 系列与性能/实现论文 |
| `title_and_abstract.search:"fast initial link setup"` | OpenAlex | 20 | 无形式化分析 |
| `title_and_abstract.search:"802.11ai"` | OpenAlex | 16 | 无形式化分析 |
| `all:"FILS" AND all:"formal"` | arXiv | 5 | 均为数学/物理误命中 |
| `all:"802.11" AND all:"ProVerif"` | arXiv | 1 | WPA3 SAE，不是 FILS |
| `all:"802.11" AND all:"Tamarin"` | arXiv | 1 | 分片/省电，不是 FILS |
| `FILS` in Kraken'18 full text | 本地 PDF | 26 | 人工分析 |
| `FILS` in Cremers'20 full text | 本地 PDF | 0 | 不含 FILS |
| `ProVerif` in TDSC'25 full text | 本地 PDF | 4 | 其自身方案，不是 FILS |
| `FILS` in TDSC'25 full text | 本地 PDF | 1 | 仅动机句 |
| `Scyther` in NTU thesis | 本地 PDF | 21 | FKR/SEF 模型 |
| `ProVerif` in NTU thesis | 本地 PDF | 1 | 仅在工具介绍中提及，未用于 FILS |

---

## 附录 C：一句话回答（给非形式化读者）

> 在可检索的公开文献中，**还没有人用 ProVerif 或 Tamarin 对标准 FILS 做过完整的形式化分析**；唯一接近的是 2018 年 NTU 博士论文里用 Scyther 验证的一个“两消息重认证”抽象，以及同作者用 BAN 逻辑做的逻辑推演。FILS 最著名的安全问题（KRACK 密钥重装）是 2018 年 CCS 论文**人工**发现的，作者明确说没有做形式化分析，并呼吁后续工作补上。因此，用 ProVerif 覆盖 FILS 的密钥建立、证书/原始公钥、延迟认证、DoS 和密钥重装，仍然是有新颖性的。
