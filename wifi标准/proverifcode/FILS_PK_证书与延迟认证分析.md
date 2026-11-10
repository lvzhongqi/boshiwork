# FILS PK：证书认证、无证书公钥认证与“延迟认证”分析

- 日期：2026-11-05
- 依据：IEEE Std 802.11-2024 §12.11（FILS）、IEEE Std 802.11ai-2016、RFC 5280、RFC 5480、RFC 3279、RFC 3447、RFC 6696、NIST SP 800-56A
- 形式化工具：ProVerif 2.05
- 新增模型：
  - `FILS_PK_CERT.pv` / `FILS_PK_CERT_bad.pv`
  - `FILS_PK_RAW.pv` / `FILS_PK_RAW_bad.pv`
  - `FILS_LATEAUTH.pv` / `FILS_LATEAUTH_nobind.pv`

---

## 0. 三句话结论

1. **FILS PK 的“证书认证”不是把证书当密码用，而是三件事的组合**：
   证书链把“身份 ↔ 公钥”绑死；KeyAuth 签名证明“你确实持有对应私钥”；签名覆盖
   `gSTA||gAP||SNonce||ANonce||STA-MAC||AP-BSSID` 把该公钥绑定到**本次新鲜会话**。
   证书本身不加密任何东西，它在 M3/M4 中作为 `FILS Public Key` 元素、在 AEAD 密文里传输。

2. **没有证书时，FILS PK 仍然可用，但必须有“带外信任锚”**：
   标准允许 `FILS Public Key` 元素携带 **Key Type=2/3 的原始公钥**（RFC 5480 / RFC 3279）。
   这时“身份 ↔ 公钥”的绑定来自预置、固定（pinning）、DPP、企业下发等带外手段；
   `FILS Indication` 里的 `Public Key Identifier = SHA-256(pk)` **只是选择器，不是信任凭证**。
   没有证书又没有预置公钥，公钥认证就是空的（模型 `FILS_PK_RAW_bad.pv` 给出冒充轨迹）。

3. **“先 DH 密钥协商、后在密钥确认消息里认证身份”是合理的，而且是 TLS 1.3 / SIGMA /
   Noise 同类模式；但它不是无条件安全**：
   身份认证消息必须覆盖**完整的握手 transcript（尤其 gSTA、gAP）**，必须用派生密钥保护，
   必须双向验证，必须有可信的公钥锚点。只要漏掉“绑定 ephemeral DH 公钥”这一条，
   中间人就能各自与两端协商不同的 PTK，同时让两端都“认证成功”——这就是 UKS。
   `FILS_LATEAUTH.pv` 为 true，`FILS_LATEAUTH_nobind.pv` 的 PTK 一致性为 false，正是这个结论。

---

## 1. 问题一：FILS PK 如何完成证书认证

### 1.1 先澄清：FILS PK 里的“证书”到底做什么

FILS Public Key authentication（ANA=6）是 **STA 与 AP 之间的双向公钥认证**，
不需要 Authentication Server（AS）。标准 §12.11.2.2 给出两种“对方公钥可信”的来源：

| 来源 | FILS Public Key 元素 Key Type | 编码/校验 | 信任锚 |
|---|---|---|---|
| X.509v3 证书链 | 1 | RFC 5280 | CA 根证书/信任策略 |
| 未认证原始公钥 | 2 | RFC 5480（SubjectPublicKeyInfo） | 带外预置/固定 |
| 未认证原始公钥 | 3 | RFC 3279 | 带外预置/固定 |

所以“FILS PK 证书认证”精确地说不是“证书认证协议”，而是：

> **用证书链验证对端公钥的可信性，再用该公钥验证 KeyAuth 签名，签名覆盖本次 DH transcript。**

证书解决的是 **“这把公钥属于谁”**；
签名解决的是 **“对端确实持有对应私钥，并且是对本次会话签的”**；
DH 解决的是 **“会话密钥新鲜、且具备前向保密”**；
AEAD 解决的是 **“密钥确认 + 只有同一 DH 对方能解开”**。

四者缺一不可。

### 1.2 四帧中证书放在哪里

FILS PK 的证书**不在** Authentication（Seq=1/Seq=2）帧里，而在后面的
(Re)Association Request/Response 的 **AEAD 密文部分**：

| 帧 | 方向 | 与证书/公钥相关的内容 | 保护方式 |
|---|---|---|---|
| M1 Auth Seq=1 | STA→AP | `DH Group`、`gSTA`、`SNonce`、`Session`、`RSNE`、可选 PMKID List | 明文（无认证） |
| M2 Auth Seq=2 | AP→STA | `DH Group`、`gAP`、`ANonce`、`Session`、`RSNE`、可选 PMKID | 明文（无认证） |
| M3 (Re)Assoc Request | STA→AP | **FILS Public Key 元素（STA 证书链/原始公钥）**、`KeyAuth = Sig-STA(...)` | `AEAD(PTK-KEK)`，AAD 含 Session/RSNE 等 |
| M4 (Re)Assoc Response | AP→STA | **FILS Public Key 元素（AP 证书链/原始公钥）**、`KeyAuth = Sig-AP(...)`、Key Delivery(GTK/IGTK…) | `AEAD(PTK-KEK)` |

要点：

- 证书是**加密传输**的（在 M3/M4 的 AEAD 密文里），空口被动攻击者看不到证书内容；
  但 STA-MAC / AP-BSSID 在帧头是明文，所以**身份隐私并不由证书加密提供**。
- AP 的公钥标识可以提前出现在 Beacon/Probe Response 的 **FILS Indication** 元素中：
  - Key Type=1：`Public Key Identifier` = 证书的 **Issuer**；
  - Key Type=2/3：`Public Key Identifier` = 原始公钥的 **SHA-256 哈希**。
  这个标识符只用于“选择哪张证书/哪把公钥”，**不能替代证书链校验或带外信任**。
- M1/M2 只交换 DH 公钥和 nonce，**此时双方都还没有认证对方**；真正的身份认证在 M3/M4。

### 1.3 AP 验证 STA 的完整步骤（M3）

AP 收到 M3 后，按标准 §12.11.2.6.2 的顺序：

1. **FILS Session 一致性**：M3 中的 Session 必须等于 M1/M2 中协商的 Session。
2. **RSNE 一致性**：Association 帧中的 RSNE 必须与 Authentication 帧一致（AKM/cipher/RSN 能力）。
3. **AEAD 解密**：用 `PTK-KEK` 解密，AAD 必须与发送端一致（Session、RSNE、MAC 等）。
   解密失败 → Status 112，删除 ICK/KEK/TK/PTKSA。
4. **取 STA 公钥**：从 `FILS Public Key` 元素取出证书链或原始公钥。
5. **证书链校验（Key Type=1）**：
   - 逐级验证签名，直到本地信任锚；
   - 检查有效期、Basic Constraints（CA=true）、Key Usage、Extended Key Usage、
     Name Constraints、证书策略、吊销状态（CRL/OCSP）；
   - 按 RFC 5280 做“密码学 + 安全策略”两方面的校验。
6. **主体身份绑定**：证书 Subject/SAN 必须与本次声称的 STA 身份/订阅一致。
   **只验证“证书是 CA 签的”而不检查“证书主体是不是对端”，等于没认证**。
7. **验证 KeyAuth 签名**：用证书里的公钥验证
   `Sig-STA(gSTA || gAP || SNonce || ANonce || STA-MAC || AP-BSSID)`。
   - 签名算法由公钥类型决定：RSA（RFC 3447）、DSA（FIPS 186-4）、ECDSA（ISO/IEC 14888-3）。
   - 验签通过说明：对端持有私钥，且签的是**本次**的 gSTA/gAP/nonce/MAC。
8. **密钥确认成功**：安装 PTKSA，构造 M4（AP 的证书 + AP 的 KeyAuth + Key Delivery）。

### 1.4 STA 验证 AP 的完整步骤（M4）

对称地，STA 收到 M4 后：

1. 检查 Session、RSNE、AEAD 解密。
2. 从 `FILS Public Key` 元素取 AP 证书链/原始公钥。
3. 按 RFC 5280 校验证书链到本地信任锚（AP 的证书通常由企业 CA/公共 CA 签发）。
4. 检查证书主体与期望的 AP 身份（BSSID/SSID/域名）一致。
5. 用 AP 公钥验证
   `Sig-AP(gAP || gSTA || ANonce || SNonce || AP-BSSID || STA-MAC)`。
6. 验证通过后安装 TK/GTK，FILS 完成；失败则删除 ICK/KEK/PMK/TK，放弃交换。

### 1.5 为什么这套组合能抵抗冒充、重放和 UKS

| 攻击 | 被哪一层挡住 |
|---|---|
| 攻击者用自己的证书冒充 STA | AP 检查证书主体 ≠ 声称身份 → 拒绝（见 `FILS_PK_CERT_bad.pv` 的反例） |
| 攻击者用别人的合法证书 | 没有对应私钥，KeyAuth 签名验证失败 |
| 重放旧 M3/M4 | 签名覆盖 SNonce/ANonce/Session/gSTA/gAP；每次新鲜，重放失败 |
| 中间人替换 gSTA/gAP | 签名覆盖两个 DH 公钥，替换后验签失败 |
| 中间人替换证书 | 证书链校验到信任锚，替换后链断 |
| 未知密钥共享（UKS） | KeyAuth 把身份、MAC、DH 公钥、nonce、Session 全部绑在一起 |
| 密钥确认错配 | M3/M4 都在 `AEAD(PTK-KEK)` 内，密钥不一致则解密失败 |

### 1.6 形式化验证：`FILS_PK_CERT.pv` 与 `FILS_PK_CERT_bad.pv`

`FILS_PK_CERT.pv` 显式建模了：

- CA 根公钥 `pkCA` 是信任锚；
- 证书 `cert = Sign_CA(subject, pk_subject)`；
- 攻击者持有一张 **CA 合法签发、但主体为 sta2/ap2** 的证书 `certE/certE2`，
  以及对应私钥 `skE/skE2`（模拟“内部人/被攻陷设备”）；
- 诚实 AP/STA 既验证 CA 签名，又检查 `subject == 期望对端`。

结果（7 条查询全部 true）：

```
not attacker(gtk_val)                         true
not attacker(probe_tk)                        true
event(StaFinish) ==> event(ApFinish)          true
inj-event(StaFinish) ==> inj-event(ApFinish)  true
event(ApFinish) ==> event(StaStart)           true
inj-event(ApFinish) ==> inj-event(StaStart)   true
event(StaPTK) ==> event(ApPTK)                true
```

`FILS_PK_CERT_bad.pv` 只去掉“证书主体检查”，其余完全相同。结果全部为 false：

```
not attacker(gtk_val)                         false  ← 攻击者拿到 GTK
not attacker(probe_tk)                        false  ← 攻击者解密 STA 的 TK 数据帧
event(StaFinish) ==> event(ApFinish)          false  ← 冒充 AP 成功
event(ApFinish) ==> event(StaStart)           false  ← 冒充 STA 成功
event(StaPTK) ==> event(ApPTK)                false  ← 两侧 PTK 不一致
```

这组对照说明：**“证书链校验通过”不等于“认证通过”**。证书链只证明
“这把公钥被某个 CA 签过”，还必须检查“这把公钥对应的是不是我以为的对端”。
很多实现漏洞就出在这一步。

### 1.7 证书认证的实现检查清单

- [ ] 是否校验完整证书链到本地信任锚，而不是只取叶子证书里的公钥？
- [ ] 是否检查证书有效期、Basic Constraints、Key Usage、EKU、Name Constraints？
- [ ] 是否检查吊销状态（CRL/OCSP），并处理 CRL 过期/不可达策略？
- [ ] 是否把证书 Subject/SAN 与期望的 STA/AP 身份做策略映射？
- [ ] 是否验证 KeyAuth 签名覆盖 `gSTA||gAP||SNonce||ANonce||STA-MAC||AP-BSSID`？
- [ ] 是否把 Session、RSNE 纳入 AAD/签名，防止 Session 替换？
- [ ] 是否校验对端 DH 公钥是合法群元素（NIST SP 800-56A §5.6.2.3）？
- [ ] 失败时是否按标准删除 ICK/KEK/TK/PTKSA，而不是回退旧密钥？
- [ ] 证书链较大时是否处理分片/长度/DoS 风险？
- [ ] 是否在 KeyAuth 成功前拒绝转发任何受保护数据？

---

## 2. 问题二：没有证书时，如何基于公钥认证

### 2.1 标准允许“原始公钥”，不要求必须有证书

FILS Public Key 元素的 Key Type 明确支持：

- **Key Type = 1**：X.509v3 证书（RFC 5280）；
- **Key Type = 2**：未认证公钥，RFC 5480 编码（SubjectPublicKeyInfo）；
- **Key Type = 3**：未认证公钥，RFC 3279 编码。

“未认证公钥”（unauthenticated public key）不是“不需要信任”，而是
**“没有 CA 签名，信任由协议之外的手段建立”**。标准 §12.11.1 把
“每个 STA 具备信任对方公钥的手段”列为 FILS PK 的安全前提。

### 2.2 无证书时的信任从哪来

常见做法（都属于“带外信任锚”）：

| 方式 | 典型场景 | 绑定了什么 |
|---|---|---|
| 出厂/预置公钥 | IoT、固定设备 | 设备身份 ↔ 公钥 |
| 固定（pinning） | 管理型 Wi-Fi、私有 AP | BSSID/SSID ↔ AP 公钥 |
| DPP（Device Provisioning Protocol） | 消费级 Wi-Fi 快速配网 | 引导公钥 ↔ 设备 |
| 二维码/NFC/蓝牙带外 | 首次配网 | 公钥指纹 ↔ 设备 |
| 企业 MDM/证书下发 | 企业网 | 用户/设备身份 ↔ 公钥 |
| 首次使用后固定（TOFU） | 实验/临时网络 | 首次看到的公钥（**有风险**） |

关键点：**公钥本身是公开的，公开不等于可信**。必须有一条“认证通道”
把“这把公钥 = 这个身份”传给你。没有这条通道，任何人都能把自己的公钥发给你。

### 2.3 FILS Indication 里的哈希不是信任凭证

AP 在 Beacon/Probe Response 的 FILS Indication 中携带
`Public Key Identifier`：

- Key Type=1：证书 Issuer；
- Key Type=2/3：`SHA-256(原始公钥)`。

它的作用只是让 STA **快速判断“这是不是我信任的那把 AP 公钥”**。
如果 STA 只是“看到信标里的哈希，就用信标里对应的公钥”，
攻击者完全可以广播自己的哈希和自己的公钥——哈希匹配，但信任锚是攻击者。
所以：

> **哈希是选择器（selector），不是认证器（authenticator）。**
> 只有当哈希值本身是通过带外可信渠道预置的，匹配才有意义。

### 2.4 无证书 FILS PK 的消息流程

与有证书时完全同构，只是 `FILS Public Key` 元素里放的是原始公钥（Key Type=2/3），
而不是证书链：

```
M1 STA→AP: gSTA, SNonce, Session, RSNE, [PMKIDList]
M2 AP→STA: gAP, ANonce, Session, RSNE, [PMKID]
   双方计算 DHss → PMK → PTK → ICK/KEK/TK
M3 STA→AP: AEAD(PTK-KEK, FILS Public Key = pkSTA, KeyAuth=Sig-STA(...))
M4 AP→STA: AEAD(PTK-KEK, FILS Public Key = pkAP,  KeyAuth=Sig-AP(...), Key Delivery)
```

验证方：

1. 取出原始公钥；
2. 检查它是否**等于/匹配带外预置的那把公钥**（或它的哈希）；
3. 用该公钥验证 KeyAuth 签名；
4. 检查签名覆盖的 transcript（gSTA/gAP/nonce/MAC/Session）；
5. AEAD 解密成功、KeyAuth 成功后才安装密钥。

如果 AP 和 STA 的信任方式不同（例如 AP 有证书、STA 只有原始公钥），
两侧的 `FILS Public Key` 元素可以分别使用不同的 Key Type；标准是按元素分别编码的。

### 2.5 形式化验证：`FILS_PK_RAW.pv` 与 `FILS_PK_RAW_bad.pv`

`FILS_PK_RAW.pv` 建模：

- 没有 CA，没有证书；
- STA 预置并信任 `pkA1`，AP 预置并信任 `pkS1`；
- `FILS Indication` 中只公开 `h(pkS1)`、`h(pkA1)` 作为选择器；
- 攻击者有自己的 `(skE, pkE)`，但没有被预置。

结果（7 条查询全部 true）：GTK/TK 保密、双向认证、单射、PTK 一致性全部成立。

`FILS_PK_RAW_bad.pv` 去掉“预置公钥匹配”，验签方直接相信报文里携带的公钥。
结果全部为 false：攻击者用自己的 `pkE` 冒充 sta1/ap1，完成完整中间人，
拿到 GTK、解密 TK 数据帧，并造成 PTK 不一致。

对照结论：

> **无证书公钥认证的安全性 = 带外信任锚的质量。**
> 预置/固定做得好，安全性等价于证书；没有锚点，公钥认证是空的。

### 2.6 没有证书、也没有预置公钥怎么办

如果既没有证书，也没有任何带外预置的公钥，**不要使用 FILS PK**。可选：

1. **FILS SK + EAP-RP/rRK**：先通过 802.1X/EAP 建立 rRK，之后用 FILS SK；
   这是企业网最常见的“STA 没有客户端证书”的部署方式。
2. **FILS SK + PMKSA 缓存**：此前已成功认证并缓存 PMKSA，后续快速重连。
3. **DPP 先配网**：用 DPP 引导信任，再使用 FILS PK/后续 AKM。
4. **完整 EAP**：没有快速建立需求时，直接走 802.1X。
5. **TOFU 只适用于实验/受控环境**：首次连接记录公钥，后续固定；
   首次连接本身仍可能被中间人攻击，不能作为生产安全方案。

### 2.7 无证书公钥认证的实现检查清单

- [ ] 原始公钥是否来自可信的带外渠道，而不是仅从空口/信标获取？
- [ ] 是否把公钥与期望身份（BSSID/SSID/设备 ID/用户）绑定？
- [ ] `Public Key Identifier` 哈希是否只用于选择，是否没有替代签名验证？
- [ ] 是否验证 KeyAuth 签名覆盖完整 transcript？
- [ ] 是否校验 DH 公钥合法性？
- [ ] 密钥更新/轮换时，如何更新预置公钥？是否有回滚/撤销机制？
- [ ] 设备丢失/私钥泄露时，如何撤销“固定”的公钥？

---

## 3. 问题三：先密钥协商、后在密钥确认中认证身份，是否合理？

### 3.1 结论

**合理，而且这是现代认证密钥交换的标准做法之一**：

- TLS 1.3：ServerHello 里先做 (EC)DHE，之后用 CertificateVerify 对 transcript 签名；
- SIGMA / IKEv2：先 DH，再用签名/MAC 认证；
- Noise IK/XX：先 DH，再在后续消息中加密并认证身份；
- FILS PK：M1/M2 先 DH，M3/M4 用 KeyAuth 认证身份并确认密钥。

这种模式常被称为 **delayed authentication / authentication in key confirmation**。
它的安全性不取决于“先协商”这个顺序本身，而取决于**认证消息是否绑定了完整的协商 transcript**。

### 3.2 为什么可以“先协商”

1. **前两帧不产生任何可用密钥**：M1/M2 只交换 `gSTA/gAP/SNonce/ANonce/Session`，
   双方算出的是一个“候选 PTK”，还没有安装、没有确认、没有传数据。
2. **认证消息受候选密钥保护**：M3/M4 在 `AEAD(PTK-KEK)` 内，
   只有算出同一个 `DHss` 的一方能正确解密/验证。攻击者如果替换了 DH 公钥，
   它和两端算出的是不同的密钥，无法翻译密文（除非它同时知道两把密钥——见 3.4 的反例）。
3. **认证消息覆盖 transcript**：KeyAuth 签名/HMAC 把 `gSTA/gAP/SNonce/ANonce/MAC/Session`
   全部纳入，等于对“这次协商的完整上下文”签字。
4. **双向确认**：STA 验证 AP 的 KeyAuth，AP 验证 STA 的 KeyAuth，
   两边都确认“对方持有私钥/共享密钥，且我们算出了同一把 PTK”。
5. **失败即终止**：任何一步失败就删除 PTK/ICK/KEK/TK，不进入数据阶段。

因此，“先协商”只是把**密钥建立**提前，**认证并没有被省略**，只是放在了
受密钥保护的最后两帧里。这和“先认证再协商”（如 TLS 1.2 的 Certificate + CKE）
相比，少了一个往返，适合 FILS 的 4 帧目标。

### 3.3 但“合理”不等于“无条件安全”：必要条件

| 编号 | 条件 | 不满足的后果 | 对应模型 |
|---|---|---|---|
| C1 | 每次会话使用新鲜的 `SNonce/ANonce/临时 DH 私钥/Session` | 重放、PTK 重用 | `FILS_KEYREUSE.pv` |
| C2 | 校验对端 DH 公钥是合法群元素（NIST SP 800-56A §5.6.2.3） | 退化值/小群攻击，DHss 可预测 | 本轮模型加入 `dh_ok` 后排除 |
| C3 | KeyAuth 覆盖**完整 transcript**，尤其 `gSTA/gAP` | UKS：双方认证成功但 PTK 不同，攻击者知道两把密钥 | `FILS_LATEAUTH_nobind.pv` |
| C4 | KeyAuth 受派生密钥保护（AEAD）或签名+加密 | 篡改/重放/密钥确认缺失 | `FILS_LATEAUTH.pv` |
| C5 | 双向验证，不能只验一侧 | 单向认证/冒充 | 见 3.5 |
| C6 | 对端公钥有可信锚点（证书链或预置原始公钥） | 公钥替换/中间人 | `FILS_PK_CERT_bad.pv`、`FILS_PK_RAW_bad.pv` |
| C7 | 失败即终止并删除临时密钥，不回退旧密钥 | 降级/继续使用旧密钥 | `FILS_STATUS_faulty.pv` |

其中 **C3 是最容易被误解的一条**。很多人认为“KeyAuth 已经在 AEAD 里了，
攻击者没有密钥，改不了 DH 公钥”。但中间人可以选择自己的 DH 私钥 `m1/m2`，
分别与两端协商：

```
STA 侧：K_STA = (g^m2)^s = g^(s·m2)
AP  侧：K_AP  = (g^m1)^a = g^(a·m1)
攻击者知道 g^s、g^a、m1、m2，因此两把密钥都能算出来。
```

如果 KeyAuth 签名只覆盖 nonce/身份/Session、不覆盖 `g^m1/g^m2`，
攻击者就可以用 `K_STA` 解开 STA 的 M3，再用 `K_AP` 重新加密后转发；
反向同理。两端签名都合法、都“完成认证”，但 PTK 不同，攻击者掌握两把会话密钥。
**AEAD 本身救不了，因为攻击者知道两把 AEAD 密钥。**

### 3.4 反例模型：`FILS_LATEAUTH_nobind.pv`

模型与 `FILS_LATEAUTH.pv` 的唯一区别：

```
正确：KeyAuth_STA = Sign(gs || ga || sn || an || sta || ap || sess)
错误：KeyAuth_STA = Sign(sn || an || sta || ap || sess)        ← 漏掉 gs/ga
```

两者都保留 `AEAD(PTK-KEK)`、都双向验证、都检查 nonce/Session/身份。
结果：

```
FILS_LATEAUTH.pv（正确绑定）：
  attacker(probe_tk)                    true
  StaFinish ==> ApFinish                true
  StaPTK ==> ApPTK                      true
  唯一性                                 true

FILS_LATEAUTH_nobind.pv（漏掉 gs/ga）：
  attacker(probe_tk)                    false  ← 攻击者解密 STA 数据帧
  StaFinish ==> ApFinish                true   ← 两端都“完成”了
  ApFinish ==> StaStart                 true
  StaPTK ==> ApPTK                      false  ← 但 PTK 不一致（UKS）
```

注意第二组里 `StaFinish ==> ApFinish` 仍是 true：
**“双方都完成了”并不等于“双方完成了同一件事”**。
这正是 UKS 的典型特征，也是为什么只看“认证事件是否对应”不够，
还要看 **PTK 一致性**（同一会话、同一密钥）查询。

### 3.5 只认证一侧会怎样

如果 STA 在发出 M3 后不等 M4、不验证 AP 的 KeyAuth 就安装密钥并认为完成，
那么攻击者可以只拦住 M4，STA 仍然“认证成功”。这等价于**单向认证**：
AP 可能认证了 STA，但 STA 没有认证 AP。

FILS 在 M3/M4 两个方向都放了 KeyAuth，且 STA 必须验证 M4 才 `StaFinish`，
所以标准实现不会出现这种退化。实现检查时要确认：
**不能在发送 M3 后就提前安装 TK/GTK 或转发数据。**

### 3.6 FILS 具体是怎么做的

| 方向 | KeyAuth（无缓存 PK） | 覆盖的关键字段 |
|---|---|---|
| STA→AP | `Sig-STA(gSTA || gAP || SNonce || ANonce || STA-MAC || AP-BSSID)` | 两个 DH 公钥、两个 nonce、双方 MAC |
| AP→STA | `Sig-AP(gAP || gSTA || ANonce || SNonce || AP-BSSID || STA-MAC)` | 同上，顺序方向绑定 |

- FILS SK（HMAC 版本）同样把 `SNonce||ANonce||STA-MAC||AP-BSSID`（PFS 时再加
  `gSTA||gAP`）纳入 HMAC，方向顺序不同，防止反射。
- 2024 中 **PK + PMKSA 缓存** 的 KeyAuth 改为 HMAC 构造（不再签名），
  因为 PMKSA 已经在此前会话中建立了身份绑定；此时“认证”依赖缓存的 PMKSA，
  而不是本次的证书。
- `FILS Key Confirmation` 元素在 AEAD 密文里；AEAD 的 AAD 还绑定
  Session、RSNE 等，防止字段替换。

### 3.7 这种设计的代价与残余风险

1. **DoS / 资源消耗**：M1/M2 未认证，攻击者可伪造大量 M1 让 AP 做 DH/验签；
   需要 anti-clogging、速率限制。status 字段不在 KeyAuth/AEAD 保护内，
   伪造 `status=112` 可让 STA 中止（`FILS_STATUS.pv` 已给出 DoS 轨迹）。
2. **身份隐私**：STA-MAC 在 M1 明文，延迟认证不隐藏身份；
   PMKID 也是稳定标识，可跨会话链接（`FILS_PMKID_LINK.pv`）。
3. **前向保密**：FILS PK 始终有 PFS；FILS SK 的 ANA=5 有 PFS，ANA=4 没有
   （`FILS_PFS.pv` 中 SK4 为 false 是标准允许的取舍）。
4. **公钥/证书吊销**：延迟认证不解决撤销；证书过期、设备丢失、私钥泄露
   仍需要 CRL/OCSP/管理面撤销。
5. **降级/回退**：失败后不能回退旧 PTK；`FILS_STATUS_faulty.pv` 展示了
   错误实现如何被伪造 status 触发回退。
6. **实现复杂度**：证书链解析、策略校验、群元素校验、transcript 编码、
   方向绑定、状态机清理，任何一处遗漏都可能把“延迟认证”变成“延迟漏洞”。

---

## 4. 新增模型与验证结果汇总

| 模型 | 验证内容 | 查询数 | 结果 |
|---|---|---|---|
| `FILS_PK_CERT.pv` | 证书链 + 主体绑定 + KeyAuth + PTK 一致性 | 7 | **全部 true** |
| `FILS_PK_CERT_bad.pv` | 只验链、不验主体 | 7 | **全部 false（冒充/GTK/TK 泄露/UKS）** |
| `FILS_PK_RAW.pv` | 无证书、预置原始公钥 | 7 | **全部 true** |
| `FILS_PK_RAW_bad.pv` | 无证书、无预置（TOFU/信任报文中的公钥） | 7 | **全部 false（中间人）** |
| `FILS_LATEAUTH.pv` | 先 DH、KeyAuth 覆盖完整 transcript + AEAD | 7 | **全部 true** |
| `FILS_LATEAUTH_nobind.pv` | 先 DH、KeyAuth 漏掉 gSTA/gAP | 7 | 双向完成 true，**PTK 一致性 false、数据泄露 false** |

补充说明：

- 所有新模型都加入了 `dh_ok(exp(g,x))` 群元素校验。它是对标准
  “校验 gSTA/gAP 是合法群元素”要求的**模型抽象**（只接受形如 `g^x` 的项，
  拒绝裸 `g` 等退化值）；真实实现还应按 NIST SP 800-56A §5.6.2.3 检查
  identity、子群/阶、cofactor 等。没有这层校验时，攻击者可发送 `gAP = g`，
  使 `DHss = gSTA`（公开值），从而直接算出 PTK；这是一个独立的实现陷阱，
  不应与“证书主体未校验”混为一谈。
- `FILS_PK_CERT_bad.pv` 中 `attacker(gtk_val)` 的攻击路径是：
  恶意 STA 用主体为 sta2 的合法证书 + 自己的私钥，向 AP 冒充 sta1；
  AP 只验链不验主体，接受并下发 GTK。
- `FILS_PK_CERT_bad.pv` 中 `attacker(probe_tk)` 的攻击路径是：
  恶意 AP 用主体为 ap2 的合法证书 + 自己的私钥，向 STA 冒充 ap1；
  STA 只验链不验主体，接受并安装攻击者给的 GTK，随后发送的 TK 数据帧
  被攻击者用同一 PTK 解密。

---

## 5. 与既有工作的关系 / 边界

- **不是首次提出**：延迟认证（SIGMA、TLS 1.3、Noise）和“证书链 + 主体绑定”
  都是成熟技术；本工作的贡献是把 FILS PK 的这几个环节形式化，并给出
  “合规/不合规”对照的可复现 ProVerif 轨迹。
- **证书链抽象**：模型用单级 CA 直接签叶子证书；真实部署可能是多级链、
  交叉签名、桥 CA。多级链只是把 `checksign(cert, pkParent)` 迭代，
  安全结论不变；但策略/吊销/名称约束的复杂度不在模型中。
- **身份映射**：模型把 STA-MAC / AP-BSSID 当作身份；真实证书的 Subject
  可能是用户/设备名，需要策略映射到 MAC/SSID。这个映射错误也会导致冒充，
  模型未展开。
- **未建模**：CRL/OCSP 实时性、证书链分片、证书解析漏洞、PKI 信任锚配置错误、
  多 AP 漫游、完整 EAP-RP、GTK rekey 状态机、帧级/实现层攻击、时序侧信道。
- **未联网核对**：本文件不给出具体论文/CVE 编号；如需精确引用，可在提供来源后补充。

---

## 6. 复现

```powershell
$pv = "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode\proverifbin2.05\proverif.exe"
$dir = "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode"
foreach ($n in @(
  "FILS_PK_CERT","FILS_PK_CERT_bad",
  "FILS_PK_RAW","FILS_PK_RAW_bad",
  "FILS_LATEAUTH","FILS_LATEAUTH_nobind"
)) {
  & $pv "$dir\$n.pv" > "$dir\$n.out.txt" 2> "$dir\$n.err.txt"
}
```

---

## 7. 标准条款速查

| 主题 | 802.11-2024 | 802.11ai-2016 |
|---|---|---|
| FILS 安全假设与目标 | §12.11.1 | §12.12.1 |
| 发现与公钥可信 | §12.11.2.2 | §12.12.2.2 |
| FILS PK Authentication Seq=1/2 | §12.11.2.4 | §12.12.2.4 |
| PMK/PMKID/PTK 推导 | §12.11.2.5 | §12.12.2.5 |
| (Re)Association 密钥确认 | §12.11.2.6 | §12.12.2.6 |
| AEAD（AES-SIV） | §12.11.2.7 | §12.12.2.7 |
| FILS Public Key 元素 | §9.4.2.174–188 | §9.4.2.176–190 |
| FILS Key Confirmation 元素 | §9.4.2.177 | §9.4.2.179 |
| FILS Indication | §9.4.2.174–188（元素族） | §9.4.2.176–190（元素族） |

外部标准：

- RFC 5280：Internet X.509 PKI Certificate and CRL Profile；
- RFC 5480：Elliptic Curve Cryptography Subject Public Key Information；
- RFC 3279：Algorithms and Identifiers for PKIX；
- RFC 3447：PKCS #1（RSA）；
- RFC 6696：EAP Re-authentication Protocol（EAP-RP）；
- NIST SP 800-56A R2 §5.6.2.3：DH 公钥验证。
