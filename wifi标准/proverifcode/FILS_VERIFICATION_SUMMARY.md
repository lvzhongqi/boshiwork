# FILS 协议 ProVerif 验证 —— 今日工作总结

- 日期：2026-11-04
- 工具：ProVerif 2.05（`proverifcode/proverifbin2.05/proverif.exe`）
- 模型目录：`proverifcode/`
- 说明：以下“true/false”均指 ProVerif 的查询结果；其中
  `not attacker(x) is false` 表示**攻击者可以得到 x**（攻击成立），
  `inj-event(...) is false` 表示**单射性被破坏**（重放/重复接受成立）。

---

## 一、今日完成的工作

1. 分析了目录下已有 `.pv` 模型与对应 `.out.txt`，为各文件补充了中文注释与结论块：
   `FILS_PK.pv`、`FILS_SK.pv`、`FILS_PFS.pv`、`FILS_PK_old.pv`。
2. 明确了 ProVerif 2.05（untyped 新语法）的使用要点：
   - `process` 语句**不能以 `.` 结尾**（否则语法错误）；
   - `event(Sec(x)) ==> not attacker(x)` **不被支持**，改用“私有探针 + `query attacker`”；
   - 支持**等式结论查询**（用于 PTK 一致性/唯一性/UKS）；
   - 支持 `choice` / observational equivalence。
3. 扩展了 `FILS_PK.pv` 与 `FILS_SK.pv` 的安全目标（见下）。
4. 新增了 11 个专项模型，覆盖密钥重用、Seq 重放、status、GTK rekey、PMKID 隐私、缓存一致/不同步、PFS 等。
5. 用 ProVerif 重新生成全部输出文件（`.out.txt`），`.err.txt` 均为 0 字节，所有 `.pv` 均通过 `-parse-only`。
6. 分析并记录了“符合标准”与“不符合标准”两类情况下可成功的攻击。
7. 补充了 PMKID 链接性/跟踪的成因、与 2018 年 “PMKID 口令破解攻击”的区别，以及“非首创/相关工作”的说明（见 3.1.1–3.1.3）。

---

## 二、模型文件清单与验证结果

| 模型文件 | 验证内容 | 查询数 | 结果 |
|---|---|---|---|
| `FILS_PK.pv` | FILS PK（无缓存 F / 缓存 C）：GTK/TK/缓存 PMK 保密、双向认证、单射、PTK 一致性、PTK 唯一性、UKS、缓存一致性 | 17 | **全部 true** |
| `FILS_SK.pv` | FILS SK（ANA=4/5/5C）：GTK/TK/PMK/rMSK 保密、双向认证、单射、PTK 一致性、唯一性、UKS、跨 AKM 分离、同会话单 AKM | 22 | **全部 true** |
| `FILS_PFS.pv` | 前向保密：PK、SK5、SK4 | 3 | PK true、SK5 true、SK4 **false（预期，ANA=4 无 PFS）** |
| `FILS_CACHE.pv` | 缓存一致 / 不同步 | 3 | **全部 true**（不同步只导致失败，不产生错配 PTK） |
| `FILS_KEYREUSE.pv` | RNG 失效（nonce/临时密钥复用）→ PTK 重用 | 1 | **false（PTK 重用成立）** |
| `FILS_EAPRP_SEQ.pv` | WrappedData 中 PMK SEQ 校验正确时重放 | 2 | **全部 true**（无 PMK 重用） |
| `FILS_EAPRP_SEQ_bad.pv` | 不校验 SEQ 时重放 | 2 | 唯一性 **false（PMK 重用）**，rMSK 仍保密 |
| `FILS_GTK_REPLAY_good.pv` | GTK rekey 校验 KeyID/epoch | 2 | **true / true** |
| `FILS_GTK_REPLAY_bad.pv` | 不校验 KeyID/epoch，重放旧 GTK | 2 | `StaAccept=>ApSend` true，**inj false（重放被接受）** |
| `FILS_PMKID_LINK.pv` | PMKID 链接性/跟踪 | 1 | **false（同一 PMKID 可跨会话关联）** |
| `FILS_PRIVACY.pv` | PMKID 观测等价 | 1 | `cannot be proved`（附区分轨迹；确定性结论见 `FILS_PMKID_LINK.pv`） |
| `FILS_REPLAY.pv` | Seq/消息重放（双端独立进程） | 3 | **全部 true**（PTK 不重用、PTK 一致、PMK 保密） |
| `FILS_STATUS.pv` | status 机制 + 伪造错误 status（正确实现） | 3 | `abort_flag` **false（DoS 可达）**、`probe` true（密钥仍保密）、认证 true |
| `FILS_STATUS_faulty.pv` | 失败后回退旧密钥（错误实现） | 3 | `bad_flag` **false（回退可达）**、`old_ptk` true、`probe` true |
| `FILS_PK_old.pv` | 早期合并模型（历史版，仅参考） | — | 未作为正式验证目标 |

> 注：`FILS_GTK_REPLAY_bad.out.txt` 中还有一行
> `(but event(StaAccept...) ==> ... is true)`，是 ProVerif 对非单射查询的补充说明，
> 关键结论是 **inj-event 为 false**。

---

## 三、符合标准要求情况下可以成功的攻击

以下攻击在“实现符合标准 + 正常 RNG”前提下仍然成立，属于**协议/标准层面固有的残余风险**。

### 3.1 PMKID 链接性 / 隐私跟踪（成立）

- 模型：`FILS_PMKID_LINK.pv`
- 结果：`event(Sent(s1,p)) && event(Sent(s2,p)) ==> s1 = s2` 为 **false**
- 含义：同一 PMKSA 的 PMKID 在多次会话中保持不变且明文携带，攻击者可把
  不同会话关联到同一 STA，形成**跟踪/链接**。
- 性质：这是标准设计使然（PMKID 是稳定伪标识），不是实现错误。
- 影响：**隐私**（不是密钥泄露）。

#### 3.1.1 PMKID 是什么、怎么导致跟踪

- PMKID 是 PMKSA 的标识符，典型派生：
  `PMKID = Truncate-128(HMAC-SHA-256(PMK, "PMK Name" || AP_MAC || STA_MAC))`。
  只要 PMKSA 不变，同一 STA 对同一 AP 的 PMKID 就不变。
- 出现位置：FILS Authentication M1 的 PMKID List、M2 回显、PMKSA caching 的
  (Re)Association、传统 RSN 4-way handshake 的 Message 2；这些字段**明文**。
- 攻击步骤（被动）：抓包记录 PMKID → 用户随机化 MAC → 用不变的 PMKID 做关联键
  → 把不同 MAC 的多次连接归并为同一设备（存在性/位置画像）。
- 攻击步骤（主动）：流氓 AP 诱导 STA 报出 PMKID List，或用 status 53
  （Invalid PMKID）作为“该 PMKID 是否有效”的预言机，确认缓存成员/设备回访。
- 根因：确定性派生 + 明文传输 + 长生命周期 + 回显/可探测；仅靠 MAC 随机化无法消除。

#### 3.1.2 与“2018 年 PMKID 攻击”的区别（重要）

- 2018 年 Jens Steube / Hashcat 的 “PMKID attack”：抓取 PMKID 作为可离线爆破的
  哈希，用来**猜解 WPA2 口令（PSK）**，属于口令破解。
- 本节说的是“PMKID 链接性/跟踪”：用稳定 PMKID **关联设备**，属于隐私问题，
  不涉及口令或密钥破解。两者常被混淆，性质不同。

#### 3.1.3 是否由他人提出（相关工作与定位）

- “稳定标识符 + MAC 随机化失效 → 设备跟踪”是 Wi-Fi 隐私研究的成熟方向；
  802.11 标准的隐私/安全考量也讨论 MAC 随机化与标识符暴露；PMK 缓存 / FILS
  的隐私分析中也提到 PMKID 的可链接性。因此**该问题的概念并非本工作首次提出**。
- 本工作的贡献是：把“同一 PMKID 跨会话出现”形式化为等式查询，并在
  `FILS_PMKID_LINK.pv` 中用 ProVerif 给出可复现的 **false（可链接）** 结论。
- 说明：当前环境未联网核对具体论文标题/编号，故不在此给出可能不准确的引用；
  如需精确引用，可在提供来源或允许联网后补充。

### 3.2 伪造错误 status → 拒绝服务（DoS）（成立）

- 模型：`FILS_STATUS.pv`
- 结果：`not attacker(abort_flag[]) is false`（攻击者可触发 abort），
  `not attacker(probe[]) is true`（密钥/数据仍保密）
- 含义：FILS Authentication 帧中的 status 不在 KeyAuth/AEAD 保护范围内，
  攻击者可把 M2 的 status 改成 `112` 等，使 STA 中止本次认证。
- 性质：符合标准的 STA 本来就会在非成功 status 时终止，因此这是**有效的可用性攻击**。
- 影响：**DoS**（不是密钥恢复/冒充）。

### 3.3 ANA=4（FILS Shared Key without PFS）无前向保密（标准允许的取舍）

- 模型：`FILS_PFS.pv`
- 结果：`not attacker_p1(probe_sk4[]) is false`（rMSK 泄露后可恢复旧会话 TK）
- 含义：ANA=4 不做 DH，rMSK 一旦泄露，攻击者可重算旧会话的 PMK/PTK/TK。
- 性质：**标准明确允许**（ANA=5 才带 PFS；FILS PK 总是 PFS）。
- 影响：**前向保密缺失**，前提是 rMSK 已泄露。

### 3.4 说明

- 上述 3.1、3.2 是“合规实现也会成立”的攻击；3.3 是标准规定的设计取舍，
  需要“rMSK 泄露”这一额外前提。
- 合规实现下，PTK 一致性、PTK 唯一性、UKS、跨 AKM 分离、双向认证/单射、
  GTK/TK/rMSK 保密等均为 true（见 `FILS_PK.pv`、`FILS_SK.pv`、`FILS_REPLAY.pv`）。

---

## 四、不符合标准情况下可以出现的攻击

以下攻击只在**实现偏离标准**（缺少新鲜性、缺少校验、错误回退、缺少绑定）时出现。

### 4.1 RNG 失效 → PTK 重用

- 模型：`FILS_KEYREUSE.pv`
- 结果：唯一性查询 **false**
- 条件：两次会话复用同一 `SNonce/ANonce/临时 DH 私钥`（RNG 失效或弱随机）。
- 影响：**密钥重用**（PTK 重复），可能进一步导致数据密钥重用。

### 4.2 EAP-RP PMK SEQ 未校验 → 重放导致 PMK 重用

- 模型：`FILS_EAPRP_SEQ_bad.pv`
- 结果：PMK 唯一性 **false**（附攻击轨迹）
- 条件：AP 不校验 WrappedData 中的 SEQ（未按 RFC 6696 维护 SEQ 单调性）。
- 影响：重放旧 WrappedData 可让 AP 重新派生出**相同 PMK**，即 PMK 重用。
- 对照：`FILS_EAPRP_SEQ.pv`（正确校验 SEQ）结果为 **true**（无重用）。

### 4.3 GTK rekey 未校验 KeyID/epoch → 重放旧 GTK

- 模型：`FILS_GTK_REPLAY_bad.pv`
- 结果：`inj-event(StaAccept) ==> inj-event(ApSend)` 为 **false**
- 条件：STA 不校验 GTK 的 KeyID/epoch，只按内容接受。
- 影响：攻击者可重放旧 GTK 帧并被再次接受（GTK 重放/回滚）。
- 对照：`FILS_GTK_REPLAY_good.pv` 为 **true / true**。

### 4.4 status 失败后回退旧密钥 → 降级 / 继续使用旧密钥

- 模型：`FILS_STATUS_faulty.pv`
- 结果：`not attacker(bad_flag[]) is false`（回退分支可达）
- 条件：实现不按标准终止，而是在非成功 status 后回退到旧 PTK。
- 影响：攻击者伪造失败 status 即可让 STA 继续使用旧密钥（**降级/状态问题**）；
  若旧密钥已泄露/过时，则数据面临泄露风险。
- 对照：`FILS_STATUS.pv`（正确实现）只出现 abort（DoS），密钥仍保密。

### 4.5 Session 未绑定进 KeyAuth/AAD → Session 替换

- 模型：`FILS_REPLAY.pv` 的建模过程
- 现象：未绑定 Session 时，ProVerif 找到“同一 PTK、不同 Session”的替换轨迹
  （PTK 一致性为 false）；把 Session 绑定进 KeyAuth/AAD 后，该轨迹消失（true）。
- 条件：实现未把 FILS Session 纳入 KeyAuth/AAD。
- 影响：**会话标识错绑**（不一定是密钥泄露，但破坏会话绑定/单射语义）。

### 4.6 EAP-RP SEQ 回绕未 rekey → 重放窗口

- 条件：RFC 6696 的 16-bit SEQ 回绕前未重新协商/更换 rMSK。
- 影响：旧 SEQ 可能重新“有效”，形成重放窗口。
- 说明：当前有界模型未展开 2^16 回绕，但这是文档层面的已知要求。

### 4.7 PMKID/PMK 未与身份绑定、缓存未校验（未完整建模）

- 条件：PMKID 查找/缓存实现未绑定 STA/AP 身份或未校验缓存条目。
- 影响：可能出现跨 STA/AP 的缓存误用（当前模型为简化缓存，未覆盖多条目/跨 AP）。

---

## 五、未覆盖 / 边界

- 未完整建模 status 的**定时器 113**、失败后的重试/换 AKM 策略；
- 未建模 **DoS 资源消耗**、速率限制、anti-clogging（ProVerif 无可用性语义）；
- 未建模 **EAP-RP 全协议**（rMSK 被抽象为后端共享私钥；AP↔AS 接口标准列为 out of scope）；
- 未建模 **多 AP / 移动性** 下的 PMKSA 复用、PMKID miss 回退、跨 AP 缓存；
- 未建模 **GTK rekey 完整状态机**（仅 epoch/KeyID 校验的微观模型）；
- 未建模**帧级攻击**（分片/聚合、实现内存错误）与**计算安全性/时序侧信道**；
- `FILS_PRIVACY.pv` 的 observational equivalence 在 2.05 下为 `cannot be proved`
  （但打印了区分轨迹）；确定性链接性结论以 `FILS_PMKID_LINK.pv` 的 false 为准；
- 未联网核对具体论文/CVE 编号；本文件只记录**本目录模型实际跑出的结果**与标准层面的通用结论。

---

## 六、复现方式

```powershell
# 单个模型
& "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode\proverifbin2.05\proverif.exe" `
  "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode\FILS_PK.pv"

# 生成 out/err 日志（若脚本执行策略受限，用 Bypass）
powershell -ExecutionPolicy Bypass -File `
  "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode\run_pv.ps1" `
  -PvExe "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode\proverifbin2.05\proverif.exe" `
  -Model "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode\FILS_PK.pv"
```

---

## 七、结论摘要

- **合规 + 正常 RNG**：FILS PK/SK 的机密性、双向认证、密钥确认、单射、
  PTK 一致性/唯一性、UKS 防护、跨 AKM 分离、缓存一致性均成立。
- **合规残余风险**：PMKID 可链接（隐私）、伪造 status 可 DoS、ANA=4 无 PFS
  （需 rMSK 泄露）。
- **不合规实现**：会出现 PTK/PMK 重用（RNG、SEQ）、GTK rekey 重放、
  失败回退旧密钥、Session 错绑等攻击。
