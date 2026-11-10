# FILS 协议安全问题汇总（含 DoS 分析）

- 日期：2026-11-05
- 范围：IEEE 802.11-2024 §12.11（FILS）中的 FILS PK（ANA=6）、FILS SK（ANA=4/5）、
  PMKSA 缓存、EAP-RP 接口、GTK rekey、status/失败处理、证书/原始公钥信任
- 工具：ProVerif 2.05（`proverifcode/proverifbin2.05/proverif.exe`）
- 模型目录：`wifi标准/proverifcode/`
- 配套文档：
  - `FILS_VERIFICATION_SUMMARY.md`（逐模型结果）
  - `FILS_PK_证书与延迟认证分析.md`（证书/无证书/延迟认证专题）
  - 本文：把所有已分析出的问题按“合规残余风险 / 不合规实现 / 信任锚 / DoS”归类

> 说明：ProVerif 能证明机密性、认证性、对应性、单射性、密钥一致性、
> 观测等价等性质；**不能**证明时间、CPU、内存、队列等可用性性质。
> 因此本文中的 DoS 结论分两层：
> 1. 形式化层：证明“未认证的昂贵工作可达”（DoS 前提）；
> 2. 工程层：结合 AP 的速率限制、状态上限、超时、anti-clogging 判断实际风险。

---

## 0. 结论摘要

- **合规实现 + 正常 RNG**：FILS PK/SK 的机密性、双向认证、密钥确认、单射、
  PTK 一致性/唯一性、UKS 防护、跨 AKM 分离、缓存一致性均成立。
- **合规实现仍有残余风险**：
  - PMKID 可链接/可跟踪（隐私）；
  - 伪造 status 可让 STA 中止（单会话 DoS）；
  - ANA=4 无前向保密（需 rMSK 泄露）；
  - **M1/M2 未认证，AP 必须先做 DH/状态分配，存在资源耗尽 DoS**（本文重点）。
- **不合规实现会出现**：PTK/PMK 重用、GTK 重放、失败回退旧密钥、
  Session 错绑、证书主体不绑定导致冒充、无证书公钥不固定导致中间人、
  KeyAuth 不绑定 gSTA/gAP 导致 UKS/密钥泄露、DH 公钥不校验导致退化 DH。
- **对“没有预置公钥的 STA 反复发 M1、不做身份认证会不会 DoS”的回答**：
  **会**。M1 本身不携带任何可验证凭证，AP 在 M2 之前无法知道对端是否有密钥、
  是否是真实 STA；攻击者/未配置 STA 只要发合法格式的 M1，就能迫使 AP 做
  群元素校验、生成 ANonce/gAP、做 DH、派生 PTK、分配状态并回 M2。
  如果攻击者随后不发 M3（或发无效 M3），AP 的状态会保持到超时。
  这是 FILS “1 个往返完成认证”设计的固有代价；是否被打垮取决于 AP 的
  anti-clogging、速率限制、状态上限和超时策略。

---

## 1. 威胁模型与方法

### 1.1 攻击者能力

- Dolev-Yao 空口攻击者：可窃听、注入、修改、重放、删除、交错消息；
- 可伪造源 MAC、可分布式发起大量会话；
- 可持有自己的证书/私钥（内部人/被攻陷设备）；
- 可等待 RNG 失效、缓存不同步、实现回退等异常条件。

### 1.2 两类实现

| 类别 | 含义 | 例子 |
|---|---|---|
| 合规实现 | 按标准做新鲜性、校验、绑定、失败清理 | `FILS_PK.pv`、`FILS_SK.pv`、`FILS_PK_CERT.pv`、`FILS_PK_RAW.pv`、`FILS_LATEAUTH.pv` |
| 不合规实现 | 缺少某一步校验/绑定/清理 | `FILS_PK_CERT_bad.pv`、`FILS_PK_RAW_bad.pv`、`FILS_LATEAUTH_nobind.pv`、`FILS_KEYREUSE.pv`、`FILS_STATUS_faulty.pv` |

### 1.3 结果记号

- `not attacker(x) is true`：攻击者得不到 x（保密性成立）；
- `not attacker(x) is false`：攻击者可得到 x（攻击成立）；
- `event(A) ==> event(B) is false`：存在 A 发生但 B 未发生的轨迹（认证/对应性失败）；
- `inj-event(A) ==> inj-event(B) is false`：单射性失败（重放/重复接受）；
- `cannot be proved`：ProVerif 未能证明（可能是攻击，也可能是模型/工具限制，需看轨迹）。

---

## 2. 问题总览

| ID | 类别 | 问题 | 模型 | 结果 | 影响 | 严重性 |
|---|---|---|---|---|---|---|
| A1 | 合规/隐私 | PMKID 稳定且明文，可跨会话链接设备 | `FILS_PMKID_LINK.pv` | false（可链接） | 隐私/跟踪 | 中 |
| A2 | 合规/可用性 | status 不在 KeyAuth/AEAD 保护内，可伪造 112 使 STA 中止 | `FILS_STATUS.pv` | `abort_flag` false（DoS 可达） | 单会话 DoS | 中 |
| A3 | 合规/取舍 | ANA=4 无 PFS，rMSK 泄露可恢复旧 TK | `FILS_PFS.pv` | SK4 false | 前向保密缺失 | 中 |
| A4 | 合规/可用性 | M1/M2 未认证，AP 先做 DH/状态分配，可被半开会话耗尽 | `FILS_DOS_UNAUTH.pv` | `ApWork ==> StaStart` false | 资源耗尽 DoS | 高（取决于防护） |
| A5 | 合规/实现 | M3 可携带大证书链/大元素，解析/验链消耗 CPU/内存 | 未单独建模 | — | DoS/放大 | 中 |
| A6 | 合规/隐私 | status 53 / PMKID 查询可作缓存成员预言机 | `FILS_PMKID_LINK.pv` 相关 | — | 隐私/探测 | 低-中 |
| A7 | 合规/可用性 | FILS SK 无缓存时 AP→AS 转发 EAP-Initiate，可放大到 AS | 未建模（AP↔AS out of scope） | — | AS/网络 DoS | 中 |
| B1 | 不合规/RNG | SNonce/ANonce/临时 DH/Session 重用 → PTK 重用 | `FILS_KEYREUSE.pv` | 唯一性 false | 密钥重用 | 高 |
| B2 | 不合规/EAP-RP | 不校验 WrappedData 的 SEQ → 重放导致 PMK 重用 | `FILS_EAPRP_SEQ_bad.pv` | PMK 唯一性 false | PMK 重用 | 高 |
| B3 | 不合规/GTK | 不校验 KeyID/epoch → 重放旧 GTK | `FILS_GTK_REPLAY_bad.pv` | inj false | GTK 回滚/重放 | 中-高 |
| B4 | 不合规/状态机 | 失败后回退旧 PTK → 降级/继续用旧密钥 | `FILS_STATUS_faulty.pv` | `bad_flag` false | 降级/旧密钥 | 高 |
| B5 | 不合规/绑定 | Session 未进 KeyAuth/AAD → Session 替换 | `FILS_REPLAY.pv` 建模过程 | 未绑定时 PTK 一致性 false | 会话错绑 | 中-高 |
| B6 | 不合规/EAP-RP | 16-bit SEQ 回绕前未 rekey → 重放窗口 | 未展开 2^16 | — | 重放窗口 | 中 |
| B7 | 不合规/证书 | 只验证书链、不检查证书主体 → 冒充/GTK/TK 泄露 | `FILS_PK_CERT_bad.pv` | 7/7 false | 冒充/机密性 | 高 |
| B8 | 不合规/公钥 | 无证书且不固定原始公钥（TOFU/信任报文中的公钥） | `FILS_PK_RAW_bad.pv` | 7/7 false | 中间人 | 高 |
| B9 | 不合规/绑定 | KeyAuth 不覆盖 gSTA/gAP → UKS，双方认证成功但 PTK 不同 | `FILS_LATEAUTH_nobind.pv` | PTK 一致性 false | UKS/密钥泄露 | 高 |
| B10 | 不合规/DH | 不校验对端 DH 公钥 → 退化 DH（如 gAP=g） | 概念/建模观察 | — | 密钥可算/DoS | 中-高 |
| B11 | 不合规/缓存 | PMKID/PMK 未绑定 STA/AP，缓存条目未校验 | 未完整建模 | — | 跨 STA/AP 误用 | 中 |
| B12 | 不合规/状态机 | KeyAuth 成功前安装/使用密钥，或发送 M3 后提前完成 | 概念（`FILS_LATEAUTH` 要求等 M4） | — | 单向认证/数据泄露 | 高 |
| B13 | 不合规/PKI | 不检查证书有效期/吊销/策略 | 未建模 | — | 过期/被撤销证书可用 | 高 |

> 注：A 类是“合规实现也可能成立”的问题；B 类只在实现偏离标准时出现。
> 严重性取决于部署：企业网、公共热点、物联网的暴露面不同。

---

## 3. A 类：合规实现下的残余风险

### A1. PMKID 链接性 / 隐私跟踪

- **模型**：`FILS_PMKID_LINK.pv`
- **结果**：`event(Sent(s1,p)) && event(Sent(s2,p)) ==> s1 = s2` 为 **false**
- **条件**：同一 PMKSA 的 PMKID 在多次会话中保持不变；PMKID 在 M1/M2、
  (Re)Association、4-way Message 2 中明文出现。
- **影响**：攻击者把不同 MAC/不同时间的连接归并为同一设备，形成
  存在性/位置画像；MAC 随机化无法消除。
- **标准依据**：PMKID 是 PMKSA 的稳定标识符，标准没有要求每次会话更换。
- **修复/缓解**：
  - 接受这是标准设计取舍；在高隐私场景使用不缓存 PMKSA / 使用 FILS SK
    的匿名身份机制；
  - 不要把 PMKID 当作跨会话的公开标识；
  - AP 侧限制 PMKID List 的暴露；对 status 53 的响应做速率限制；
  - 研究/部署层可考虑 PMKID 轮换/加密，但会破坏缓存兼容性。
- **注意**：这与 2018 年 Hashcat “PMKID 离线口令破解”不同；这里是链接性，
  不涉及口令或密钥破解。

### A2. 伪造 status → 单会话 DoS

- **模型**：`FILS_STATUS.pv`
- **结果**：`not attacker(abort_flag[]) is false`（攻击者可触发 abort）；
  `not attacker(probe[]) is true`（密钥仍保密）；认证查询 true。
- **条件**：FILS Authentication 帧中的 status 不在 KeyAuth/AEAD 保护范围内。
- **影响**：攻击者把 M2 的 status 改成 112（或其他非成功值），STA 按标准中止
  本次认证；不泄露密钥，但可反复打断。
- **标准依据**：status 字段在 Authentication 帧中明文；标准要求 STA 在非成功
  status 时终止。
- **修复/缓解**：
  - 这是协议层固有的；只能在实现/部署层缓解（速率限制、快速重试、
    监控异常 112、允许回退到完整 EAP）；
  - 不要因为收到 112 就删除长期凭证/PMKSA（标准也只要求删除本次 PTK 相关材料）；
  - 对反复 112 的 BSSID 做异常检测。
- **严重性**：中（单会话可用性，不是密钥泄露）。

### A3. ANA=4 无前向保密

- **模型**：`FILS_PFS.pv`
- **结果**：PK true、SK5 true、**SK4 false**。
- **条件**：ANA=4（FILS Shared Key without PFS）不做 DH；PMK = HMAC(SNonce||ANonce, rMSK)。
- **影响**：rMSK 泄露后，攻击者可重算旧会话的 PMK/PTK/TK；旧流量可被解密。
- **标准依据**：ANA=4 是标准明确允许的取舍；ANA=5 才带 PFS。
- **修复/缓解**：
  - 高安全场景优先 ANA=5 或 FILS PK（始终有 PFS）；
  - 缩短 rMSK 生命周期、限制 rMSK 暴露面；
  - 不要把 ANA=4 用于长期敏感数据。
- **严重性**：中（需 rMSK 已泄露）。

### A4. 未认证 M1/M2 → AP 资源耗尽 DoS

- **模型**：`FILS_DOS_UNAUTH.pv`
- **结果**：
  - `event(ApWork(a,s,se,gs)) ==> event(StaStart(s,a,se))` 为 **false**；
  - `event(ApFinish(s,a,se)) ==> event(ApWork(a,s,se,gs))` 为 **true**。
- **含义**：AP 可以在没有任何真实 STA 启动/认证的情况下，先做 DH、派生、
  分配状态并回复 M2；而认证完成一定以这些工作为前提。
- **条件**：M1 是未认证的 Authentication 帧；AP 在 M2 前无法验证 STA 的
  证书/公钥/PMKID 有效性；攻击者只要发格式合法的 M1 即可。
- **影响**：半开会话/状态耗尽/CPU 耗尽；合法 STA 被拒绝或延迟。
- **详细分析**：见第 6 节。
- **严重性**：高（取决于 AP 的 anti-clogging/速率限制/状态上限）。

### A5. 证书链/大元素解析 DoS

- **未单独建模**（ProVerif 无资源语义）。
- **条件**：M3 的 `FILS Public Key` 元素可以携带多张证书/大公钥；
  AP 需要 AEAD 解密、解析 ASN.1、验证证书链、验签。
- **影响**：攻击者完成 M1/M2 后，发送超大/畸形证书链或大量无效 M3，
  迫使 AP 做解析/验链/验签；可能导致 CPU/内存耗尽。
- **修复/缓解**：
  - 限制 `FILS Public Key` 元素/证书链的最大长度和证书数量；
  - 先做长度/格式/算法白名单等廉价检查，再做昂贵验签；
  - 对 M3 失败率做速率限制；
  - 证书链解析使用有界、抗递归的库。
- **严重性**：中（实现层）。

### A6. status 53 / PMKID 预言机

- **相关模型**：`FILS_PMKID_LINK.pv`
- **条件**：AP 对无效 PMKID 回 status 53；对有效 PMKID 继续。
- **影响**：攻击者可用 53/非 53 判断某个 PMKID 是否在缓存中，
  辅助确认设备回访/缓存成员；也可用于探测 AP 的缓存策略。
- **修复/缓解**：
  - 对 PMKID 查询做速率限制；
  - 统一无效/有效路径的响应时间/形态（减少侧信道）；
  - 不要把 PMKID 当作秘密，但也不要主动扩大其暴露。
- **严重性**：低-中。

### A7. FILS SK 无缓存时的 AP→AS 转发放大

- **未建模**（AP↔AS 接口标准列为 out of scope）。
- **条件**：FILS SK 未命中 PMKSA、M1 携带 EAP-Initiate/Reauth；AP 转发给 AS。
- **影响**：攻击者伪造大量 M1/EAP-Initiate，迫使 AP 与 AS 做 EAP-RP 处理；
  可放大到 RADIUS/Diameter/AS。
- **修复/缓解**：
  - AP 侧对 EAP-Initiate 转发做速率限制/配额；
  - AS 侧限流、连接数上限；
  - 优先使用 PMKSA 缓存快路径；
  - 监控 AP↔AS 异常流量。
- **严重性**：中（取决于 AS 容量与网络策略）。

---

## 4. B 类：不合规实现导致的攻击

### B1. RNG 失效 → PTK 重用

- **模型**：`FILS_KEYREUSE.pv`
- **结果**：PTK 唯一性 **false**。
- **条件**：两次会话复用同一 `SNonce/ANonce/临时 DH 私钥/Session`。
- **影响**：PTK 重复，进一步导致数据密钥/非ce 重用；可能破坏机密性和完整性。
- **修复**：
  - 使用 CSPRNG；每次会话新鲜 `SNonce/ANonce/临时 DH/Session`；
  - 启动时检查 RNG 健康；失败则拒绝启动/拒绝认证；
  - 监控重复 nonce/PTK。
- **严重性**：高。

### B2. EAP-RP SEQ 未校验 → PMK 重用

- **模型**：`FILS_EAPRP_SEQ_bad.pv`
- **结果**：PMK 唯一性 **false**（附攻击轨迹）；rMSK 仍保密。
- **条件**：AP 不校验 WrappedData 中的 SEQ，未按 RFC 6696 维护单调性。
- **影响**：重放旧 WrappedData 可让 AP 重新派生出相同 PMK（PMK 重用）。
- **对照**：`FILS_EAPRP_SEQ.pv`（正确校验 SEQ）为 true。
- **修复**：
  - 严格校验 SEQ/KeyName/域；维护单调计数；
  - 拒绝过期/重复的 EAP-Initiate/Finish；
  - 按 RFC 6696 处理重传与窗口。
- **严重性**：高。

### B3. GTK rekey 未校验 KeyID/epoch → 重放旧 GTK

- **模型**：`FILS_GTK_REPLAY_bad.pv`
- **结果**：`inj-event(StaAccept) ==> inj-event(ApSend)` 为 **false**。
- **条件**：STA 不校验 GTK 的 KeyID/epoch，只按内容接受。
- **影响**：攻击者重放旧 GTK 帧并被再次接受（GTK 重放/回滚）。
- **对照**：`FILS_GTK_REPLAY_good.pv` 为 true/true。
- **修复**：
  - 维护 GTK KeyID/epoch 单调性；
  - 拒绝旧/重复 KeyID；
  - 与 4-way/FT 的 KeyID 规则一致。
- **严重性**：中-高。

### B4. status 失败后回退旧密钥 → 降级

- **模型**：`FILS_STATUS_faulty.pv`
- **结果**：`not attacker(bad_flag[]) is false`（回退分支可达）；`old_ptk` true；
  `probe` true（密钥仍保密，但回退到旧密钥）。
- **条件**：实现不按标准终止，而是在非成功 status 后回退到旧 PTK。
- **影响**：攻击者伪造失败 status 即可让 STA 继续使用旧密钥；若旧密钥已泄露/
  过时，数据面临风险；破坏状态机语义。
- **对照**：`FILS_STATUS.pv`（正确实现）只出现 abort（DoS），密钥仍保密。
- **修复**：
  - 失败即删除 ICK/KEK/TK/PTKSA（及按缓存规则处理 PMKSA）；
  - 绝不回退旧 PTK；
  - 明确重试/换 AKM 策略。
- **严重性**：高。

### B5. Session 未绑定进 KeyAuth/AAD → Session 替换

- **模型**：`FILS_REPLAY.pv` 的建模过程。
- **现象**：未绑定 Session 时，ProVerif 找到“同一 PTK、不同 Session”的替换轨迹
  （PTK 一致性 false）；把 Session 绑定进 KeyAuth/AAD 后轨迹消失（true）。
- **条件**：实现未把 FILS Session 纳入 KeyAuth/AAD。
- **影响**：会话标识错绑；不一定是密钥泄露，但破坏会话绑定/单射语义，
  可能与其他状态机缺陷组合。
- **修复**：
  - 把 Session 纳入 KeyAuth 和 AEAD AAD；
  - 在 M3/M4 严格比对；
  - 不要把 Session 当作可忽略的“提示字段”。
- **严重性**：中-高。

### B6. EAP-RP SEQ 回绕未 rekey → 重放窗口

- **未展开 2^16**（文档级要求）。
- **条件**：RFC 6696 的 16-bit SEQ 回绕前未重新协商/更换 rMSK。
- **影响**：旧 SEQ 可能重新“有效”，形成重放窗口。
- **修复**：
  - 在 SEQ 接近回绕前 rekey/更换 rMSK；
  - 维护窗口/重放检测；
  - 记录并审计 SEQ 使用。
- **严重性**：中。

### B7. 只验证书链、不检查主体 → 冒充/GTK/TK 泄露

- **模型**：`FILS_PK_CERT_bad.pv`（对照 `FILS_PK_CERT.pv`）。
- **结果**：7 条主查询 **全部 false**：
  - `attacker(gtk_val)` false（GTK 泄露）；
  - `attacker(probe_tk)` false（TK 数据帧被解密）；
  - `StaFinish ==> ApFinish` false（冒充 AP）；
  - `ApFinish ==> StaStart` false（冒充 STA）；
  - `StaPTK ==> ApPTK` false（PTK 不一致/UKS）。
- **条件**：验证方验证了 CA 签名/证书链，但**没有检查证书 Subject/SAN 是否
  等于自己期望的对端身份**；攻击者持有一张 CA 合法签发、主体为 sta2/ap2
  的证书和私钥。
- **影响**：攻击者用“合法但不属于该身份”的证书冒充 sta1/ap1；AP/STA 接受
  KeyAuth，泄露 GTK/TK，或造成 UKS。
- **修复**：
  - 证书链校验 + 主体到身份的策略映射；
  - 校验 KeyAuth 覆盖的 MAC/BSSID/身份；
  - 不要只取叶子证书公钥就完事。
- **严重性**：高。

### B8. 无证书且不固定原始公钥 → 中间人

- **模型**：`FILS_PK_RAW_bad.pv`（对照 `FILS_PK_RAW.pv`）。
- **结果**：7 条主查询 **全部 false**：完整中间人、GTK/TK 泄露、PTK 不一致。
- **条件**：无证书，验签方直接相信报文里携带的公钥（TOFU/只匹配哈希/
  无信任锚）。
- **影响**：攻击者生成自己的 `(skE,pkE)`，在 M3/M4 声明 `pkE`；验签方用
  `pkE` 验证攻击者签名，必然通过。
- **修复**：
  - 原始公钥必须来自带外可信渠道（预置/固定/DPP/企业下发）；
  - `FILS Indication` 的 SHA-256 只做选择，不做信任；
  - 把公钥与 BSSID/SSID/设备/用户身份绑定；
  - 提供轮换/撤销机制。
- **严重性**：高。

### B9. KeyAuth 不覆盖 gSTA/gAP → UKS/密钥泄露

- **模型**：`FILS_LATEAUTH_nobind.pv`（对照 `FILS_LATEAUTH.pv`）。
- **结果**：
  - `attacker(probe_tk)` **false**（攻击者解密 STA 数据帧）；
  - `StaFinish ==> ApFinish` true（两端都“完成”）；
  - `StaPTK ==> ApPTK` **false**（PTK 不一致/UKS）。
- **条件**：KeyAuth 签名/HMAC 只覆盖 nonce/身份/Session，**不覆盖 gSTA/gAP**；
  即使 KeyAuth 仍在 AEAD(PTK-KEK) 内，也不够。
- **攻击**：中间人选择自己的 DH 私钥 `m1/m2`，分别与两端协商：
  `K_STA=g^(s·m2)`、`K_AP=g^(a·m1)`；攻击者知道 `g^s/g^a/m1/m2`，能算出
  两把密钥，解密/重加密并转发 M3/M4。两端签名合法、都完成，但 PTK 不同。
- **影响**：UKS + 会话密钥泄露；双方以为在彼此通信，实际各自与攻击者共享密钥。
- **修复**：
  - KeyAuth 必须覆盖 `gSTA||gAP||SNonce||ANonce||身份/MAC||Session`；
  - 方向绑定（两个方向顺序不同）；
  - AEAD AAD 也绑定这些字段；
  - 不要用“AEAD 已经加密了”替代 transcript 绑定。
- **严重性**：高。

### B10. 不校验对端 DH 公钥 → 退化 DH

- **概念/建模观察**：在 `FILS_PK_CERT_bad.pv` 的早期版本中，若接收方只检查
  `DH Group` 字段、不检查 `gSTA/gAP` 是否是合法群元素，攻击者可发送
  `gAP = g`，使 `DHss = gSTA`（公开值），从而直接算出 PTK。
- **最终模型**：新模型都加入 `dh_ok(exp(g,x))` 作为“合法群元素”的抽象；
  该退化路径消失。
- **条件**：实现不按 NIST SP 800-56A §5.6.2.3 做公钥验证（identity/子群/阶/
  cofactor）。
- **影响**：DHss 可预测/公开；与证书主体不绑定、无预置公钥等缺陷组合时，
  可导致密钥泄露/冒充；单独看是严重的实现缺陷。
- **修复**：
  - 校验 `gSTA/gAP` 是合法群元素，拒绝 identity/退化值/小群元素；
  - 使用标准群和标准编码；
  - 不要把“字段长度正确”当作“群元素合法”。
- **严重性**：中-高（实现层；取决于是否可与其他缺陷组合）。

### B11. PMKID/PMK 未与身份绑定、缓存未校验

- **未完整建模**（当前缓存模型是简化单条目）。
- **条件**：PMKID 查找/缓存实现未绑定 STA/AP 身份，或缓存条目未校验
  （如只按 PMKID 命中，不检查 AP BSSID/STA MAC/缓存标识）。
- **影响**：可能出现跨 STA/AP 的缓存误用；在极端情况下导致密钥错配/认证失败，
  或把 A 的缓存用于 B（取决于实现）。
- **修复**：
  - PMKID/PMKSA 条目绑定 STA MAC、AP BSSID、缓存标识、AKM；
  - 缓存查找做完整匹配；
  - 缓存不同步时只失败，不要“猜”密钥。
- **严重性**：中。

### B12. KeyAuth 成功前安装/使用密钥，或提前完成

- **概念**（`FILS_LATEAUTH.pv` 要求 STA 等到并验证 M4 才 `StaFinish`）。
- **条件**：STA 发出 M3 后就安装 TK/GTK、转发数据或认为认证完成；
  或 AP 在验证 M3 前就下发 GTK/转发数据。
- **影响**：单向认证；攻击者拦住 M4 即可让 STA “认证成功”但没有认证 AP；
  若提前转发数据，可能把数据送给未认证对端。
- **修复**：
  - 双方都验证对方 KeyAuth 后才安装密钥/转发数据；
  - 严格状态机：M3 后等待 M4，失败即清理；
  - HLP/IP 数据在密钥确认成功前不得转发（标准明确要求）。
- **严重性**：高（若提前转发数据）。

### B13. 不检查证书有效期/吊销/策略

- **未建模**。
- **条件**：只验证书签名，不检查有效期、CRL/OCSP、Basic Constraints、
  Key Usage、EKU、Name Constraints、证书策略。
- **影响**：过期证书、被撤销证书、用途不符的证书仍可用于认证；PKI 信任锚
  配置错误会放大。
- **修复**：
  - 完整 RFC 5280 路径校验；
  - 吊销检查与失败策略（软失败/硬失败要明确）；
  - 证书策略与 Wi-Fi 身份映射；
  - 定期更新信任锚/CRL。
- **严重性**：高。

---

## 5. C 类：证书/公钥信任锚问题（检查清单）

| 编号 | 检查项 | 失败后果 | 相关模型 |
|---|---|---|---|
| C1 | 是否验证完整证书链到本地信任锚？ | 自签名/伪造证书可用 | `FILS_PK_CERT.pv` |
| C2 | 是否检查证书 Subject/SAN == 期望对端身份？ | 合法但错身份的证书可冒充 | `FILS_PK_CERT_bad.pv` |
| C3 | 是否检查有效期/吊销/策略/EKU？ | 过期/撤销/用途不符证书可用 | 未建模 |
| C4 | 原始公钥是否来自带外可信渠道并固定？ | 中间人替换公钥 | `FILS_PK_RAW.pv` / `_bad.pv` |
| C5 | 是否把 FILS Indication 的哈希当信任？ | 攻击者广播自己的哈希即可 | `FILS_PK_RAW_bad.pv` |
| C6 | 证书 Subject 与 STA-MAC/AP-BSSID/SSID 的映射策略是否正确？ | 身份错绑/越权 | 未建模 |
| C7 | 信任锚/根证书是否过期、是否被错误配置？ | 整条 PKI 失效 | 未建模 |
| C8 | 多级链/交叉签名/桥 CA 是否处理？ | 链验证失败或绕过 | 未建模（单级 CA 抽象） |

---

## 6. D 类：DoS 专题——没有预置公钥的 STA 反复发 M1、不做身份认证，会不会 DoS？

### 6.1 问题重述

> 一个不持有预置公钥的 STA，不断发起 FILS 密钥协商请求（Authentication Seq=1），
> 但不进行身份认证（不完成 M3/M4）。这会不会造成 DoS？

### 6.2 直接回答

**会。** 至少会造成以下几类可用性问题：

1. **半开会话/状态耗尽**：AP 为每个 M1 分配状态（ANonce、gAP、DHss、PTK、
   Session、定时器），等待 M3；攻击者不发 M3，状态保持到超时。大量 M1
   可占满 AP 的 pending 表。
2. **CPU 消耗**：AP 要做群元素校验、生成临时 DH 密钥、做 DH、派生 PTK、
   可能还要做证书/签名验证；这些都比“丢弃一个格式错误的帧”昂贵。
3. **合法 STA 被拒绝/延迟**：pending 表满、CPU 饱和、速率限制触发时，
   合法 STA 的 M1 被丢弃或排队。
4. **放大到 AS（FILS SK 无缓存时）**：如果 M1 携带 EAP-Initiate，AP 可能
   转发给 AS，造成 AP↔AS/AS 的负载。
5. **与 status 112 组合**：攻击者还可以伪造 M2 的 status=112，直接打断
   合法 STA 的会话（A2），成本更低。

**但它不是密钥泄露/冒充**：攻击者没有得到 PTK/GTK/TK，也没有让 AP 接受
一个未认证的 STA；它消耗的是资源。是否“打垮”AP 取决于 AP 的防护。

### 6.3 为什么“没有预置公钥”不影响发起 DoS

这是关键点：

- M1 的内容是 `ANA、DH Group、gSTA、SNonce、Session、RSNE、[PMKIDList]`；
  **没有证书、没有签名、没有持钥证明**。
- AP 在 M2 之前**无法验证** STA 是否有预置公钥/证书/PMKID；它只能检查
  格式、AKM/群支持、RSNE 等。
- 因此：
  - 有预置公钥的 STA 可以发 M1；
  - 没有预置公钥的 STA 也可以发 M1；
  - 攻击者**不需要任何密钥**，只要发格式合法的 M1；
  - 即使 AP 要求“必须有证书”，证书是在 M3 才出现的；攻击者永远不发 M3，
    AP 就已经完成了 M2 的工作。
- 反过来，一个**诚实但未配置**的 STA 也会反复发 M1、在 M3/M4 失败；
  这会造成“配置错误风暴”，但恶意攻击者可以做得更狠（伪造源 MAC、
  分布式、并发大量会话）。

所以：**“不持有预置公钥”不是 DoS 的前提条件；它只是保证这次认证最终会失败，
但不能阻止 AP 先为它做工作。**

### 6.4 AP 在 M1 之后到底做了什么

以 FILS PK 为例（FILS SK 类似，且有 AS 转发的额外成本）：

| 步骤 | 工作 | 是否可在认证前避免 |
|---|---|---|
| 1 | 解析 Authentication 帧、检查 ANA/长度/RSNE/AKM | 部分可廉价拒绝 |
| 2 | 检查 DH Group 是否支持 | 可廉价拒绝（status 77） |
| 3 | 校验 gSTA 是合法群元素（NIST SP 800-56A） | 必须做（否则 B10） |
| 4 | 生成 ANonce、临时 DH 私钥 sA、gAP | 必须做（M2 需要） |
| 5 | 计算 DHss、PMK、PTK（ICK/KEK/TK） | 必须做（M3 解密需要） |
| 6 | 分配 Session/状态/定时器 | 必须做（等待 M3） |
| 7 | 构造并发送 M2 | 必须做 |
| 8 | 等待 M3；超时后清理 | 攻击者不发 M3 → 状态保持到超时 |

其中 3–7 是“未认证的昂贵工作”。FILS 的 4 帧设计决定了 AP 必须在知道
STA 身份之前完成这些工作；否则无法在 M3 中解密/验证 KeyAuth。

### 6.5 形式化：`FILS_DOS_UNAUTH.pv`

模型把“AP 的昂贵工作”抽象为事件 `ApWork(AP, 声称的 STA, Session, gSTA)`：

- AP 收到格式合法的 M1 后，立即触发 `ApWork`，然后生成 ANonce/gAP、回 M2；
- 诚实 STA 触发 `StaStart`；
- 恶意/未预置 STA 只发 M1，不触发 `StaStart`，也不发 M3。

查询与结果：

```
event(ApWork(a,s,se,gs)) ==> event(StaStart(s,a,se))   false
event(ApFinish(s,a,se)) ==> event(ApWork(a,s,se,gs))   true
```

解释：

- 第一条 false：存在“AP 已工作，但对应 STA 从未启动”的轨迹；
  即 **AP 可以被未认证的 M1 迫使做昂贵工作**。
- 第二条 true：认证完成一定以这些工作为前提；工作本身不是错误，
  问题是它发生在认证之前且可被无界触发。

**模型边界**：ProVerif 没有时间/CPU/内存/队列语义，所以它证明的是
“未认证工作可达”，不是“AP 一定会被打垮”。实际 DoS 取决于：
- AP 每 M1 的工作量（DH/验签/状态）；
- pending 会话上限；
- 超时长度；
- 速率限制/anti-clogging；
- CPU/内存/带宽；
- 是否有分布式攻击。

### 6.6 攻击变体

| 变体 | 做法 | 主要消耗 |
|---|---|---|
| 半开 M1 洪泛 | 大量 M1，不发 M3 | 状态表、定时器、DH |
| 无效 M3 洪泛 | 完成 M1/M2，发无效 M3（坏 KeyAuth/坏证书） | DH + AEAD + 验签/验链 |
| 大证书链 | M3 携带超大/畸形证书链 | 解析、验链、内存 |
| 源 MAC 伪造/分布式 | 每帧换 MAC，绕过 per-MAC 限速 | 全局 CPU/状态 |
| status 112 注入 | 改 M2 status，让 STA 中止 | 合法会话可用性 |
| 不支持群探测 | 发不支持群，收 status 77 | 廉价，主要用于探测 |
| EAP-Initiate 洪泛 | FILS SK 无缓存，迫使 AP→AS | AP↔AS/AS 负载 |
| PMKID 随机填充 | 大量随机 PMKID，迫使 miss/AS 路径 | 缓存查找/AS |

### 6.7 严重性判断

| 条件 | 风险 |
|---|---|
| AP 在 M1 后做完整 DH + 分配状态，且无速率限制/状态上限 | **高**：容易半开耗尽 |
| AP 有 per-MAC 速率限制，但 MAC 可伪造 | **中-高**：分布式可绕过 |
| AP 有全局/每射频限速 + pending 上限 + 短超时 | **中**：可缓解但仍有负载 |
| AP 有 stateless cookie/anti-clogging，延迟 DH/状态到 M3 | **低-中**：大幅缓解，但增加往返/复杂度 |
| AP 只支持已知 STA 的 PMKSA 缓存快路径 | **中**：M1 仍可伪造，但可廉价拒绝 |
| AP 把 M1 处理卸载到硬件/多核 + 限流 | **中**：提高容量，不消除根本 |

### 6.8 缓解措施（按优先级）

**P0（必须）**

1. **速率限制**：per-STA-MAC、per-BSSID、per-radio、全局多级限速；
   注意 MAC 可伪造，不能只依赖 per-MAC。
2. **pending 会话上限 + 短超时**：限制同时等待 M3 的会话数；
   超时快速清理；满时优先丢弃新 M1，保护已建立会话。
3. **廉价前置检查**：长度、ANA、AKM、RSNE、DH Group、元素大小；
   不支持的群直接 status 77，不进入 DH。
4. **证书/元素大小上限**：限制 `FILS Public Key` 元素、证书链长度、
   证书数量、签名长度；解析用有界库。

**P1（强烈建议）**

5. **anti-clogging / stateless cookie**：在昂贵 DH/状态分配前，让 STA
   证明“能收到并返回一个 cookie/ puzzle”；可显著降低半开洪泛。
   代价：可能增加一个往返，和 FILS 的低延迟目标冲突，需要按部署权衡。
6. **延迟状态分配**：M2 阶段只保留最小状态（或 stateless M2），
   把 PTK/ICK/KEK 的完整派生推迟到 M3；但 M2 仍需要 gAP/ANonce，
   不能完全免费。
7. **CPU 隔离/配额**：DH/验签/验链走独立 worker/队列；对昂贵操作限流；
   保护已建立数据面。
8. **AP↔AS 限流**：FILS SK 无缓存时，对 EAP-Initiate 转发做配额；
   AS 侧连接数/速率限制。

**P2（运营/监控）**

9. **监控**：M1/M2 比例、半开会话数、M3 失败率、112 比例、CPU/内存；
   异常告警。
10. **管理帧限速/异常检测**：利用 AP/控制器能力限制 Authentication 帧速率；
    检测源 MAC 快速变化/大量失败。
11. **部署策略**：已知 STA 用 PMKSA 缓存/FILS SK；未知/未配置 STA 走
    802.1X/EAP 并限流；不要在公共热点对匿名 STA 开放高成本 FILS PK。
12. **不要用“没有预置公钥”作为信任/拒绝依据**：AP 在 M1 阶段无法验证；
    必须在资源策略上假设“任何 M1 都可能是攻击”。

### 6.9 结论

- **会 DoS**：至少是半开会话/状态耗尽/CPU 消耗型 DoS；在无防护的 AP 上
  可以很严重。
- **根因是协议设计取舍**：FILS 为了 1-RTT，把 DH 放在未认证的 M1/M2；
  AP 必须在认证前工作。这不是实现“忘了认证”，而是标准流程的固有暴露面。
- **“没有预置公钥”不是关键**：攻击者不需要密钥；有密钥的 STA 也能被伪造。
  关键在 AP 是否对未认证的 M1 做无界昂贵工作。
- **不能靠密码学消除**：这是可用性问题，必须靠限流、状态上限、超时、
  anti-clogging、CPU 配额和监控来缓解。
- **与密钥安全区分**：该 DoS 不泄露 PTK/GTK/TK，也不让 AP 接受未认证 STA；
  它是可用性风险，不是机密性/认证性失败。

---

## 7. 全部模型与结果总表

| 模型 | 验证内容 | 查询数 | 结果 |
|---|---|---|---|
| `FILS_PK.pv` | FILS PK 基线：GTK/TK/缓存 PMK 保密、双向认证、单射、PTK 一致性/唯一性、UKS、缓存一致性 | 17 | 全部 true |
| `FILS_SK.pv` | FILS SK（ANA=4/5/5C）：GTK/TK/PMK/rMSK 保密、双向认证、单射、PTK 一致性/唯一性、UKS、跨 AKM 分离、同会话单 AKM | 22 | 全部 true |
| `FILS_PFS.pv` | 前向保密：PK、SK5、SK4 | 3 | PK true、SK5 true、SK4 false（预期） |
| `FILS_CACHE.pv` | 缓存一致/不同步 | 3 | 全部 true |
| `FILS_KEYREUSE.pv` | RNG 失效 → PTK 重用 | 1 | false（重用成立） |
| `FILS_EAPRP_SEQ.pv` | 正确校验 SEQ | 2 | 全部 true |
| `FILS_EAPRP_SEQ_bad.pv` | 不校验 SEQ → PMK 重用 | 2 | 唯一性 false，rMSK 仍保密 |
| `FILS_GTK_REPLAY_good.pv` | 校验 KeyID/epoch | 2 | true/true |
| `FILS_GTK_REPLAY_bad.pv` | 不校验 KeyID/epoch → GTK 重放 | 2 | `StaAccept=>ApSend` true，inj false |
| `FILS_PMKID_LINK.pv` | PMKID 链接性 | 1 | false（可链接） |
| `FILS_PRIVACY.pv` | PMKID 观测等价 | 1 | cannot be proved（附区分轨迹） |
| `FILS_REPLAY.pv` | Seq/消息重放、PTK 重用 | 3 | 全部 true |
| `FILS_STATUS.pv` | status + 伪造错误 status（正确实现） | 3 | abort_flag false（DoS 可达）、probe true、认证 true |
| `FILS_STATUS_faulty.pv` | 失败后回退旧密钥 | 3 | bad_flag false、old_ptk true、probe true |
| `FILS_PK_old.pv` | 早期合并模型（历史版） | — | 仅参考 |
| `FILS_PK_CERT.pv` | 证书链 + 主体绑定 + KeyAuth | 7 | 全部 true |
| `FILS_PK_CERT_bad.pv` | 只验证书链、不验主体 | 7 | 全部 false（冒充/GTK/TK 泄露/UKS） |
| `FILS_PK_RAW.pv` | 无证书、预置原始公钥 | 7 | 全部 true |
| `FILS_PK_RAW_bad.pv` | 无证书、无预置（TOFU/信任报文中的公钥） | 7 | 全部 false（中间人） |
| `FILS_LATEAUTH.pv` | 先 DH、KeyAuth 覆盖完整 transcript + AEAD | 7 | 全部 true |
| `FILS_LATEAUTH_nobind.pv` | KeyAuth 漏掉 gSTA/gAP | 7 | 双向完成 true，PTK 一致性 false、probe 泄露 false |
| `FILS_DOS_UNAUTH.pv` | 未认证 M1 迫使 AP 先工作 | 2 | `ApWork=>StaStart` false；`ApFinish=>ApWork` true |

> 计数说明：`FILS_PK_CERT_bad.pv` / `FILS_PK_RAW_bad.pv` 的输出中，
> ProVerif 会对非单射查询额外打印 `(even ... is false)` 的补充说明；
> “7 条主查询全部 false”指 7 条原始 query。

---

## 8. 修复优先级建议

### P0（直接影响密钥/认证）

- 证书链 + 主体绑定（B7/C2）；
- 原始公钥带外固定（B8/C4）；
- KeyAuth 覆盖完整 transcript（B9）；
- 新鲜 nonce/临时 DH/Session + CSPRNG（B1）；
- EAP-RP SEQ 校验（B2）；
- 失败不回退旧密钥（B4）；
- KeyAuth 成功前不使用/转发数据（B12）；
- DH 公钥合法性校验（B10）。

### P1（影响可用性/隐私）

- status 保护/限速/异常检测（A2）；
- 未认证 M1 的 anti-clogging/状态上限/超时（A4）；
- 证书链大小/解析上限（A5）；
- GTK KeyID/epoch 校验（B3）；
- Session 绑定（B5）；
- PMKID 查询限速/响应形态统一（A6）；
- AP↔AS 转发限流（A7）。

### P2（长期/运营）

- PMKID 链接性风险评估与隐私策略（A1）；
- ANA=4 → ANA=5/PK 的迁移（A3）；
- EAP-RP SEQ 回绕/rekey 策略（B6）；
- PMKID/PMKSA 缓存多条目/跨 AP 校验（B11）；
- 证书吊销/有效期/策略（B13）；
- 多级链/交叉签名/桥 CA（C8）；
- 监控、审计、应急响应。

---

## 9. 未覆盖 / 边界

- 未建模 **时间/CPU/内存/队列**，DoS 结论分“形式化前提 + 工程判断”；
- 未完整建模 **多 AP/移动性**、PMKID miss 回退、跨 AP 缓存；
- 未建模 **完整 EAP-RP**（rMSK 抽象为后端共享私钥；AP↔AS out of scope）；
- 未建模 **GTK rekey 完整状态机**（仅 KeyID/epoch 微观模型）；
- 未建模 **证书吊销/OCSP/CRL 实时性**、多级/交叉证书链、名称约束/策略；
- 未建模 **证书 Subject ↔ STA-MAC/AP-BSSID/SSID 的真实映射**；
- 未建模 **帧级攻击**（分片/聚合、实现内存错误）、**计算安全性/时序侧信道**；
- `FILS_PRIVACY.pv` 的 observational equivalence 在 2.05 下为 `cannot be proved`；
  确定性链接性结论以 `FILS_PMKID_LINK.pv` 的 false 为准；
- 未联网核对具体论文/CVE 编号；本文只记录**本目录模型实际跑出的结果**与
  标准层面的通用结论。

---

## 10. 复现

```powershell
$pv  = "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode\proverifbin2.05\proverif.exe"
$dir = "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode"

# 单个模型
& $pv "$dir\FILS_DOS_UNAUTH.pv"

# 批量生成 out/err
foreach ($n in @(
  "FILS_PK","FILS_SK","FILS_PFS","FILS_CACHE",
  "FILS_KEYREUSE","FILS_EAPRP_SEQ","FILS_EAPRP_SEQ_bad",
  "FILS_GTK_REPLAY_good","FILS_GTK_REPLAY_bad",
  "FILS_PMKID_LINK","FILS_PRIVACY","FILS_REPLAY",
  "FILS_STATUS","FILS_STATUS_faulty",
  "FILS_PK_CERT","FILS_PK_CERT_bad",
  "FILS_PK_RAW","FILS_PK_RAW_bad",
  "FILS_LATEAUTH","FILS_LATEAUTH_nobind",
  "FILS_DOS_UNAUTH"
)) {
  & $pv "$dir\$n.pv" > "$dir\$n.out.txt" 2> "$dir\$n.err.txt"
}
```

---

## 11. 标准条款速查

| 主题 | 802.11-2024 | 802.11ai-2016 |
|---|---|---|
| FILS 安全假设与目标 | §12.11.1 | §12.12.1 |
| 发现与公钥可信 | §12.11.2.2 | §12.12.2.2 |
| FILS PK Authentication Seq=1/2 | §12.11.2.4 | §12.12.2.4 |
| FILS SK Authentication Seq=1/2 | §12.11.2.3 | §12.12.2.3 |
| PMK/PMKID/PTK 推导 | §12.11.2.5 | §12.12.2.5 |
| (Re)Association 密钥确认 | §12.11.2.6 | §12.12.2.6 |
| AEAD（AES-SIV） | §12.11.2.7 | §12.12.2.7 |
| FILS Public Key 元素 | §9.4.2.174–188 | §9.4.2.176–190 |
| FILS Key Confirmation 元素 | §9.4.2.177 | §9.4.2.179 |
| 关联响应超时 | `dot11AuthenticationResponseTimeout` | 同 |
| 证书路径校验 | RFC 5280 | RFC 5280 |
| 原始公钥编码 | RFC 5480 / RFC 3279 | 同 |
| DH 公钥验证 | NIST SP 800-56A §5.6.2.3 | 同 |
| EAP-RP | RFC 6696 | 同 |
