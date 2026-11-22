# FILS 扩展安全目标与三类攻击的形式化分析

- **日期**：2026-11-20
- **工具**：ProVerif 2.05（`proverifcode/proverifbin2.05/proverif.exe`）
- **对象**：IEEE 802.11-2024 §12.11 FILS；FILS SK（ANA=4/5/5C）与 FILS PK（ANA=6）
- **基线模型**：`FILS_SK.pv`（22 条查询全 true）、`FILS_PK.pv`（17 条查询全 true）
- **扩展模型**：
  - `FILS_SK_PRIVACY.pv`、`FILS_PK_PRIVACY.pv`、`FILS_PRIVACY_EQUIV.pv`
  - `FILS_DOS_M1M2.pv`
  - `FILS_KRACK_SK_bad.pv` / `FILS_KRACK_SK_good.pv`
  - `FILS_KRACK_PTK_bad.pv` / `FILS_KRACK_PTK_good.pv`（公钥分支，即 FILS PK）
  - `METHOD_4WAY_PAW_KIS_bad.pv` / `_good.pv`（方法可移植性：PAW-KI 套到 4-way）
- **结论文件**：本文；配套问题清单见 `FILS安全问题汇总.md`
- **论文整理**：`论文/01_论文素材_现有工作.md`（可写进论文的结论/表格/段落）、
  `论文/02_实现核查清单与代码定位.md`（实现关键点 + 代码位置）、
  `论文/03_未来工作.md`（工作包与时间表）

> 阅读顺序说明：三个问题的回答分别在 **§2（问题二：攻击目标编码）、
> §3（问题一：论文可行性与部署）、§4（问题三：专用方法）**；这个顺序是按
> 论证依赖排的（先有目标与结果，才能谈论文与方法），不是提问顺序。
> 想先看结论可直接读 §0。

---

## 0. 结论摘要

### 0.1 一句话结论

**FILS 在“标准列出的安全目标”上可以通过 ProVerif 验证（SK 22/22、PK 17/17 全 true）；但把隐私、预认证工作、密钥安装三类目标写成 ProVerif 查询后，三类目标全部可以被攻击轨迹否定。** 这不是“模型自相矛盾”，而是说明标准目标集合不包含这三类性质：

| 维度 | 标准目标 | 基线模型 | 扩展目标 | 扩展结果 |
|---|---|---|---|---|
| 机密性 | PMK/PTK/TK/GTK 保密 | true | 同左 | true |
| 认证 | 双向认证、单射、PTK 一致性 | true | 同左 | true |
| 隐私 | **未规定** | 未建模 | PMKID 不可链接 | **false** |
| 可用性 | **未规定** | 未建模 | 未认证 M1/M2 工作不可达 | **false（可达）** |
| 密钥安装 | 只强制组密钥抗重装 | 未建模 | PTK 只安装一次 | **false（可重装）** |

### 0.2 三类攻击的形式化结果

1. **PMKID 链接性 / MAC 随机化失效**
   - `FILS_SK_PRIVACY.pv`：G-P1（同一 PMKID 不跨会话）**false**；G-P2（同一 PMKID 不跨 MAC）**false**；GTK/TK 仍 true。
   - `FILS_PK_PRIVACY.pv`：同上，结论一致。
   - `FILS_PRIVACY_EQUIV.pv`：观察等价 **cannot be proved**（攻击者可区分“同一设备两次接入”与“两个不同设备”）。
2. **未认证 M1/M2 → AP 资源占用（DoS 前提）**
   - `FILS_DOS_M1M2.pv`：`ApWorkM1 ==> StaStart` **false**；`ApWorkM2 ==> StaStart` **false**；三个有限槽同时被同一伪造身份占满 **可达**；诚实路径 `HonestDone` **可达**（非空验证）。
3. **PTK 重安装（KRACK）**
   - `FILS_KRACK_SK_bad.pv`：`ApReinstalls` **可达**；`FILS_KRACK_SK_good.pv`：按 Session 去重后 **不可达**，且重放分支仍可达（非空验证）。
   - `FILS_KRACK_PTK_bad.pv` / `_good.pv`：公钥分支（FILS PK）同样“bad 可达、good 不可达”。
4. **方法可移植性（不是 FILS 专属）**
   - `METHOD_4WAY_PAW_KIS_bad/good.pv`：同一套 PAW/KIS 事件与查询套到 WPA2 4-way 上，得到 `PAW=false`、`KIS-1: bad=false / good=true`，即伪造 Msg1 的 STA 工作与重放 Msg3 的 PTK 重装都能被同一模板复现。

### 0.3 对论文与方法的含义

- **现在的工作**已经能支撑一篇“系统性形式化验证 + 三类目标反例”的论文骨架，但如果只写“我们验证了 FILS，标准目标成立、已知攻击成立”，在 CCF-C 级别会议上**偏弱**，因为三类攻击都已有公开的人工分析。
- **要达到 C 级**，建议把贡献从“验证 FILS”提升为：
  1. 首个覆盖 FILS 密钥建立 + 密钥安装语义的机器验证（限定表述，不主张“首个 FILS 形式化分析”）；
  2. 首个 PMKID 不可链接性的形式化反例，证明 MAC 随机化在 PMKSA 缓存场景下无效；
  3. 一个可复用的“预认证工作量 + 密钥安装”双层方法（本文称 **PAW-KI**）：已在 FILS SK/PK 与 WPA2 4-way 上落地建模（`METHOD_4WAY_PAW_KIS_bad/good.pv`），FT/TPK 为后续实例；
  4. 标准条款映射与实现一致性验证（hostapd/wpa_supplicant）。
- **FILS 的部署**：不属于“像 WPA2 4-way 那样无处不在”，但在 Passpoint/运营商热点、密集场馆、企业 802.1X、物联网（802.11ah）、车联网等场景有明确应用；标准仍在 2024 版中维护，预认证帧的攻击面与隐私问题真实存在，因此**有必要分析，但不宜宣称“应用非常广泛”**。

---

## 1. 基线：标准目标为什么全 true

### 1.1 FILS SK（`FILS_SK.pv`）

22 条查询全部 true，覆盖：

- GTK、TK、预置 PMK、后端 rMSK 的机密性；
- ANA=4、ANA=5、ANA=5+缓存三组的双向认证与单射性；
- `StaPTK ==> ApPTK`（PTK 一致性 + UKS 身份绑定）；
- 同一 PTK 不跨会话（唯一性）；
- ANA=4 与 ANA=5 不跨 AKM 重用；
- 同一会话不绑定两个 AKM。

### 1.2 FILS PK（`FILS_PK.pv`）

17 条查询全部 true，覆盖：

- GTK、TK、缓存 PMK 的机密性；
- 无缓存/缓存两组的双向认证与单射性；
- PTK 一致性与唯一性；
- `CacheUse ==> CacheStore`（缓存一致性）。

### 1.3 这些 true 的边界

ProVerif 的 true 只说明：**在模型抽象内，查询所表达的性质没有反例**。基线模型抽象掉了：

- 时间、CPU、内存、队列、会话槽数量；
- 密钥“何时安装”、安装几次、PN/重放计数器；
- PMKID 的可观察性与可链接性；
- 实现是否按标准的状态机执行。

因此，基线全 true 与第 2 节的三类攻击**不矛盾**：攻击命中的是模型没有量化的维度。

### 1.4 为什么把攻击目标放在独立文件

本项目的组织方式是“**基线全 true + 攻击模型单独 false**”，而不是把 false 查询塞进基线：

- ProVerif 的输出是逐查询的；如果基线文件里出现 `false`，读者容易误以为“标准目标失败”；
- 每个攻击模型只回答一个问题（隐私/DoS/重装），便于审稿人核对；
- 基线文件与攻击模型共享同一套协议消息、密钥派生和 AEAD 规则，结论可以横向比较；
- 如果要把它们合并，只需把对应的事件与查询复制到基线，并保持事件名不冲突即可；但论文/复现实验不建议这样做。

---

## 2. 问题二：三类攻击如何写成 ProVerif 目标

### 2.1 PMKID 链接性 / MAC 随机化失效

#### 2.1.1 协议事实

- PMKID 在 FILS Authentication 帧（M1/M2）中**明文**携带，值约为
  `Truncate-128(Hash(EAP-Initiate/Reauth))`（§12.11.2.5.2）。
- 对同一个 PMKSA，PMKID 保持不变；MAC 地址随机化只改变帧头地址，不改变 PMKID。
- AP 按 PMKID 查 PMKSA 缓存，不按 MAC 查，因此同一 PMKID 可以服务不同 MAC。

**适用范围要写清楚**：链接性成立的前提是“同一 PMKSA 被复用”。如果 STA 为每个 AP 建立不同的 PMKSA，PMKID 会不同；但这样就失去了 PMKSA 缓存/快速接入的意义。跨 AP 的链接性取决于 rRK/PMKSA 是否在 ESS 内共享。

#### 2.1.2 可达性目标

`FILS_SK_PRIVACY.pv` / `FILS_PK_PRIVACY.pv` 让 STA 每次会话 `new mac`，AP 按 `pmkid` 查缓存：

```proverif
(* G-P1：同一 PMKID 出现在两个会话 ⇒ 两个会话必须是同一个 *)
query m1:bitstring, s1:bitstring, m2:bitstring, s2:bitstring, p:bitstring;
  event(StaSession(m1,s1,p)) && event(StaSession(m2,s2,p))
  ==> s1 = s2.

(* G-P2：同一 PMKID 出现在两个会话 ⇒ 两个 MAC 必须相同 *)
query m1:bitstring, s1:bitstring, m2:bitstring, s2:bitstring, p:bitstring;
  event(StaSession(m1,s1,p)) && event(StaSession(m2,s2,p))
  ==> m1 = m2.
```

实际输出（两个模型一致）：

```text
RESULT event(StaSession(...)) && event(StaSession(...)) ==> s1 = s2 is false.
RESULT event(StaSession(...)) && event(StaSession(...)) ==> m1 = m2 is false.
RESULT not attacker(gtk[]) is true.
RESULT not attacker(probe[]) is true.
```

解释：

- 第一条 false：存在两个不同会话共用同一 PMKID 的轨迹 → **可链接**；
- 第二条 false：这两个会话的 MAC 不同 → **MAC 随机化没有消除链接性**；
- GTK/TK 仍 true：**隐私失败不等于机密性失败**，这是两个独立维度。

> SK 版与 PK 版的结论一致，不是重复劳动：一旦使用 PMKSA 缓存，两个
> AKM 都走“按 PMKID 查缓存 + ICK-HMAC KeyAuth”的路径，PMKID 的可观察性
> 与“用共享密钥还是公钥认证”无关。这正说明隐私问题位于缓存/标识层，
> 而不是某个 AKM 的密码学层。

**重要修正（2026-11-21）：这个结论依赖“AP 只按 PMKID 查缓存”的假设，是
实现相关的，不是标准层保证。** 参考实现（wpa_supplicant/hostapd 2.12）的
PMKSA 查找是 `(SPA, PMKID)` 匹配（`src/ap/pmksa_cache_auth.c:500-502`、
`src/rsn_supp/pmksa_cache.c:529-532`），STA 换了 MAC 后自己就找不到该
PMKSA，不会发送 PMKID。对应的实现忠实模型是
`FILS_SK_PRIVACY_MACBOUND.pv`：

```text
G-P1（同 PMKID ⇒ 同会话）  false   （缓存的正常语义）
G-P2（同 PMKID ⇒ 同 MAC）   true    ← 换 MAC 后不再共用 PMKID
attacker(gtk)/attacker(probe)  true
```

因此正确的表述是：**PMKID 的值不绑 MAC（标准层），但参考实现的缓存查找
绑 MAC（实现层）**；“MAC 随机化失效”只在“保留 PMKSA 却更换 MAC”的实现中
成立。标准对此没有规定，这是一个标准歧义。详见
`../论文/01_论文素材_现有工作.md` 与 `../论文/02_实现核查清单与代码定位.md`。

#### 2.1.3 观察等价目标

`FILS_PRIVACY_EQUIV.pv` 用 biprocess 表达“理想不可链接性”：

- 分支 A（同一设备）：两次接入的 PMKID 都是 `pmkid1`；
- 分支 B（不同设备）：第二次 PMKID 是 `pmkid2`；
- 两个分支的 MAC/会话都是新生成的（模拟 MAC 随机化）。

```proverif
out(c, (mac1, sess1, pmkid1));
out(c, (mac2, sess2, choice[pmkid1, pmkid2]))
```

实际输出：

```text
RESULT Observational equivalence cannot be proved.
A trace has been found.
```

攻击者只需比较两个 PMKID 是否相等，就能区分两个分支；MAC 随机化不提供保护。这是比“可达性反例”更强的隐私结论。

> 前提同样是“STA 在换 MAC 后仍发送同一 PMKID”。若实现按 `(SPA, PMKID)`
> 查找缓存，换 MAC 后 STA 不会发送该 PMKID，这个 biprocess 的攻击者就无法
> 区分——这也是为什么需要 `FILS_SK_PRIVACY_MACBOUND.pv` 作为对照。

#### 2.1.4 对策与权衡

- 每次接入轮换 PMKSA/PMKID（会失去缓存加速，或需要多 PMKID 池）；
- 在 M1 中省略 PMKID、改用完整 EAP 或 FILS SK（无缓存）；
- 对 PMKID 做网络侧不可关联的盲化（需要 AP/STA 共同改造，标准未规定）；
- 隐私与快速接入存在直接权衡，标准目前没有给出统一的隐私条款。

---

### 2.2 未认证 M1/M2 → AP 资源占用（DoS 前提）

#### 2.2.1 协议事实

FILS 的认证顺序是：

```text
M1 Auth(Seq=1, gSTA, SNonce, Session, ...)
M2 Auth(Seq=2, gAP, ANonce, Session, ...)      ← AP 已做 DH、派生 PTK、分配状态
M3 (Re)Assoc Request(KeyAuth_STA)              ← 才开始验证 STA 身份
M4 (Re)Assoc Response(KeyAuth_AP, GTK)
```

AP 在 M1/M2 阶段就必须做 DH、PTK 派生、状态分配，但此时没有验证对端身份。攻击者只发 M1、不发 M3，就能让 AP 保持半开状态直到超时。

#### 2.2.2 形式化目标

`FILS_DOS_M1M2.pv` 用两个事件标记 AP 的未认证工作：

```proverif
event ApWorkM1(ap, sta, sess, slot).   (* 分配状态、校验群元素 *)
event ApWorkM2(ap, sta, sess, slot).   (* DH、PTK 派生、回 M2 *)
event StaStart(sta, ap, sess).         (* 真实 STA 启动 *)
event SlotBusy(slot, sta).             (* 有限会话槽被某个身份占住 *)
```

`SlotBusy` 带 `sta` 参数是关键：它让“槽被占”这件事能归因到**具体身份**，因此下面的合取查询要求三个槽都是被伪造身份 `sta_fake` 占的，而不是被诚实 STA 占的。否则该查询可能被“三个诚实 STA 同时接入”满足，得出虚假的 DoS 结论。

目标：

```proverif
query a,s,se,sl; event(ApWorkM1(a,s,se,sl)) ==> event(StaStart(s,a,se)).
query a,s,se,sl; event(ApWorkM2(a,s,se,sl)) ==> event(StaStart(s,a,se)).
query event(SlotBusy(slot1,sta_fake)) && event(SlotBusy(slot2,sta_fake))
      && event(SlotBusy(slot3,sta_fake)).
query s,a,se; event(HonestDone(s,a,se)).
query a,s,se,sl; event(ApAuth(a,s,se)) ==> event(ApWorkM2(a,s,se,sl)).
```

实际输出：

```text
RESULT event(ApWorkM1(...)) ==> event(StaStart(...)) is false.
RESULT event(ApWorkM2(...)) ==> event(StaStart(...)) is false.
RESULT not (event(SlotBusy(slot1,sta_fake)) && event(SlotBusy(slot2,sta_fake))
            && event(SlotBusy(slot3,sta_fake))) is false.
RESULT not event(HonestDone(s,a,se)) is false.
RESULT event(ApAuth(a,s,se)) ==> event(ApWorkM2(a,s,se,sl)) is true.
```

解释：

- 前两条 false：存在“AP 已工作，但对应 STA 从未启动”的轨迹 → 未认证工作可达；
- 第三条：ProVerif 把裸事件查询自动取反为 `not (...)`；结果为 false，表示“三个槽同时被**同一伪造身份**占满”**可达**；
- 第四条：`HonestDone` 可达，排除“模型里根本没有诚实路径”的空验证；
- 第五条：认证完成前一定做过 M2 工作，说明攻击点确实是“工作早于认证”。

#### 2.2.3 模型边界

ProVerif 没有时间/CPU/内存/队列语义，因此本模型证明的是：

- **未认证的昂贵工作可达**；
- **有限个状态槽可以被未认证 M1 占满**。

它**不**证明“AP 一定被打垮”。实际 DoS 是否成立取决于：

- AP 的速率限制、状态上限、超时时间；
- 是否实现 anti-clogging（cookie/puzzle）；
- M1 的 DH 群元素校验成本；
- 多 AP/多信道下的负载均衡。

#### 2.2.4 对策与权衡

- M1 先做无状态 cookie/谜题，再分配状态（需要标准或实现扩展）；
- 限制半开会话数与每 STA 速率；
- 延迟 DH 到 M3（会破坏 FILS 的 PFS/快速接入设计）；
- AP 侧对 M1 的群元素做低成本预校验（只能降低单次成本，不能消除放大）。

---

### 2.3 PTK 重安装（KRACK）

#### 2.3.1 标准事实

- 802.11-2024 §12.11.2.1 只强制 **GTK/IGTK/BIGTK/WGTK** 抗重装，**没有强制 PTK**；
- FILS 没有重放计数器；`FILS Session` 只是 8 字节标识，只做相等比较；
- AEAD 的 AAD 不含序列号，重放同一条密文仍可通过解密/校验；
- §11.3.5.3(m)：成功关联会删除旧 PTKSA；重装后发送侧 PN 复位，可能导致 nonce/counter 重用。

Kraken CCS'18 的 FILS 攻击（Figure 6）就是：攻击者原样重放 `(Re)Association Request`，AP 再次安装同一 PTK。

#### 2.3.2 形式化目标

`FILS_KRACK_SK_bad.pv`（SK）与 `FILS_KRACK_PTK_bad.pv`（PK）用事件标记装钥：

```proverif
event ApInstalls(ap, sess, ptk).
event ApReinstalls(ap, sess, ptk).
event ApReplaySeen(ap, sess).
```

目标与结果：

```text
(* bad：查询为 false 表示 ApReinstalls 可达 *)
Query not event(ApReinstalls(a,se,k)) is false.
Query not event(ApReplaySeen(a,se)) is false.
Query not attacker(gtk[]) is true.
Query not attacker(probe[]) is true.
```

`good` 版按 FILS Session 去重：重放时只重发缓存的 M4，不再装钥。

```text
(* good：查询为 true 表示 ApReinstalls 不可达 *)
Query not event(ApReinstalls(a,se,k)) is true.
Query not event(ApReplaySeen(a,se)) is false.   (* 重放分支仍可达，非空验证 *)
```

#### 2.3.3 为什么“标准目标 true”与“KRACK 成立”不矛盾

Kraken 论文明确指出：4-way/group key 的形式化证明只保证：

- 会话密钥保密；
- 双方身份确认。

它们**不约束密钥安装次数**。KRACK 不泄露密钥、不破坏认证，只是让同一把密钥被安装两次并复位计数器。因此：

- 基线的 `not attacker(...)`、`StaFinish ==> ApFinish` 仍然 true；
- 新增的 `not ApReinstalls` 为 false。

这正是“把攻击写成新目标”的价值：它不是推翻基线，而是暴露基线的**性质缺口**。

#### 2.3.4 PN 复位的建模边界

ProVerif 不能直接建模 PN/重放计数器。本模型用 `ApReinstalls` 作为“PN 复位”的**充分条件**：

- 若同一 PTK 被安装两次，发送侧通常会把 PN 重置；
- 是否真的复位取决于实现；wpa_supplicant 等实现专门做了防重装，可能不复位。

因此：

- `ApReinstalls` 可达 = **存在重装风险**；
- 要证明“PN 一定复位”或“计数器单调”，需要 Tamarin 的 global state / 显式计数器模型，或代码级验证。

#### 2.3.5 wpa_supplicant 的位置

用户提到“wpa_supplicant 专门做了防重装实现，不会受到攻击”。这需要区分：

- **标准层**：802.11-2024 没有强制 PTK 只安装一次；
- **实现层**：wpa_supplicant 2.6+ 在 4-way 中加入了“只安装一次”的布尔状态（Kraken CCS'17 §6 的反制），FILS 路径也可能复用类似逻辑；
- **其他实现**：不一定有同样的去重；标准合规 ≠ 抗重装。

所以论文中应表述为：“标准合规实现仍可能重装；wpa_supplicant 是实现了额外加固的正面例子，但不能代表所有实现。” 这也为“实现一致性验证”提供了切入点。

---

## 3. 问题一：现在的工作能否支撑一篇 C 级论文？

### 3.1 现在的工作是什么

一句话：**一套可复现的 FILS 形式化验证集**，包含：

- FILS SK/PK 标准目标（22/17 条 true）；
- 证书/原始公钥、延迟认证、PFS、缓存、GTK rekey、PMKID 隐私、DoS、KRACK 等专项模型；
- 标准条款到模型规则的映射；
- 三类人工攻击的机器可检反例。

优点是覆盖面广、结果可复现、与标准条款对齐；缺点是**三类攻击都是已知的**，目前没有“新攻击”或“新协议缺陷”。

### 3.2 只靠现在的工作，够不够 C 级？

**偏弱。** 如果论文标题是“Formal Verification of FILS”，贡献是“标准目标成立 + 已知攻击成立”，审稿人很可能认为：

- 三类攻击分别已有 Kraken CCS'18、PMKID 隐私文献、Lee & Chung 2015 等人工分析；
- 形式化只是“重新验证已知结论”，缺少新方法或新发现；
- 没有实现测量，无法说明真实部署影响。

这类工作更适合：

- 工作坊（workshop）论文；
- 系统/测试类会议的短文；
- 作为一篇更大论文的“验证章节”。

### 3.3 怎样把它提升到 C 级

建议把论文主线从“验证 FILS”改成“**预认证协议的隐私、可用性与密钥安装：一个双层形式化框架**”，FILS 作为核心案例。四个贡献点：

1. **新的形式化结果**：
   - 证明“标准合规的 PMKID + MAC 随机化”无法提供不可链接性；
   - 给出观察等价反例，而不仅是“PMKID 明文可见”的定性论述；
   - 证明“未认证 M1/M2 工作可达”与“有限槽可占满”。
2. **新的方法**：
   - PAW-KI 双层框架（见第 4 节）；
   - 在 FILS SK/PK、4-way、FT、TPK 上做跨协议评估；
   - 给出性质模板、精化义务、攻击投影规则。
3. **标准与实现的对齐**：
   - 逐条标注 802.11-2024 条款；
   - 用 hostapd/wpa_supplicant 代码路径验证“重放 M3 是否真的重装”；
   - 给出标准修订建议（PTK 安装状态机、PMKID 轮换、M1 anti-clogging）。
4. **可复现 artifact**：
   - ProVerif 模型集 + 一键脚本 + 结果表；
   - 可选 Tamarin/ASMETA 交叉验证。

如果做到 1+2，C 级（如 IEEE ICC/GLOBECOM/WCNC、TrustCom、PST 等，具体以当年 CCF 目录为准）是有希望的；如果只做 1，可能还是工作坊水平；如果加上 3，审稿人对“真实影响”的质疑会小很多。

**与最接近的 prior art 的区别（写作时必须写明）**：Zhang 2018 NTU 博士论文的 Scyther 模型标题虽为 “FILS”，实际是两消息 FKR 重认证抽象（`protocol2`），只验证 `Secret`/`Nisynch`，没有标准四帧、KeyAuth、AEAD、PMKID、证书/原始公钥或密钥安装。因此可以主张“首个覆盖 FILS 密钥建立 + 密钥安装语义的机器验证”，但不能主张“首个 FILS 形式化分析”。

### 3.4 FILS 的应用是否广泛？有没有分析必要？

**准确说法：FILS 不是“无处不在”，但场景明确、标准仍在维护、攻击面真实。**

应用场景：

| 场景 | 为什么用 FILS | 现状 |
|---|---|---|
| Passpoint / 运营商热点 | 减少接入时延，支持热点分流 | 有部署，但公开规模数据有限 |
| 密集场馆（体育馆、车站、机场） | 大量 STA 同时接入，减少认证往返 | 典型目标场景 |
| 企业 802.1X / EAP | 快速重认证、减少漫游中断 | 取决于 AP/终端支持 |
| 物联网 / 802.11ah | 低功耗、大量设备、快速入网 | FILS 在 802.11ah 中有明确设计 |
| 车联网 / 802.11p 类 | 快速链路建立、减少切换中断 | 研究/试点为主 |
| 消费级 Wi-Fi | 普通家庭网络 | 不常见，4-way 仍是主流 |

部署判断：

- 802.11ai 于 2016 年发布，已合并进 802.11-2020/2024；
- hostapd/wpa_supplicant 提供 FILS 支持（`CONFIG_FILS`），但商用终端/AP 是否启用取决于厂商与网络配置；
- 没有像 WPA2 那样“默认必开”的普及度；
- 但 Passpoint、企业、IoT 场景对“快速接入”有刚需，FILS 仍是标准中的正式选项。

分析必要性：

1. **预认证帧的攻击面**：M1/M2 在身份认证之前，天然暴露 DoS/资源消耗面；
2. **隐私**：MAC 随机化是移动设备的基本隐私机制，PMKID 让它在 FILS 缓存场景下失效；
3. **KRACK 历史**：FILS 在 2016 标准中就受影响，2024 标准仍未强制 PTK 抗重装；
4. **标准化仍在进行**：如果论文能给出条款级修订建议，影响不止于“学术练习”。

因此：**有必要分析，但不要宣称“FILS 应用非常广泛”**；更稳妥的表述是“FILS 在特定高密度/快速接入场景有明确部署，且其预认证设计具有代表性”。

### 3.5 论文框架草案（如果决定冲 C 级）

**题目候选**：

- “When Standard Security Goals Are Not Enough: A State-Aware Formal Analysis of FILS”
- “PAW-KI: Formalizing Pre-Authentication Work and Key Installation in Wi-Fi Protocols”
- “MAC Randomization Is Not Enough: Formalizing PMKID Linkability in IEEE 802.11 FILS”

**摘要骨架**：

> FILS 将 Wi-Fi 接入压缩为四帧，但其安全目标（保密性、认证）由标准单独定义，未覆盖隐私、预认证工作量与密钥安装状态。我们用 ProVerif 对 FILS SK/PK 的密钥建立与安装建模：标准目标全部成立，但 PMKID 链接性、未认证 M1/M2 的 DoS 前提、PTK 重装三类新增目标均被反例否定。我们进一步提出 PAW-KI 双层方法，并在 4-way、FT、TPK 上实例化，说明该缺口不是 FILS 独有。

**贡献列表**：

1. 首个覆盖 FILS 密钥建立 + 密钥安装语义的机器验证（限定表述）；
2. 首个 PMKID 不可链接性的形式化反例（含观察等价），证明 MAC 随机化在 PMKSA 缓存下无效；
3. 首个 PMKID/M1-M2/PTK 重装三类目标的统一形式化，区分“标准目标”与“扩展目标”；
4. PAW-KI 方法 + 跨协议评估 + 标准条款映射/实现验证。

**评估表**（论文中至少要有）：

| 协议 | 标准目标 | PAW | KIS-1 | 本文已建模 | KIS-2（计划） |
|---|---|---|---|---|---|
| FILS SK | true | false | false | 是 | Tamarin |
| FILS PK | true | false | false | 是 | Tamarin |
| 4-way | true（经典证明） | false | bad=false / good=true | 是 | Tamarin |
| FT | 待验证 | 待验证 | 待验证 | 否 | Tamarin |
| TPK | 待验证 | 待验证 | false（Kraken） | 否 | Tamarin |
| SAE | 已有工作 | 对照 | 对照 | 否 | — |

**投稿策略**：

- 如果只完成 FILS 部分：投 workshop/short paper（如 ACM WiSec workshop、IEEE CNS workshop 等）；
- 如果完成 PAW-KI + 3 个以上协议 + 实现验证：投 C 级正会（ICC/GLOBECOM/WCNC/TrustCom/PST，按当年 CCF 目录确认）；
- 如果发现新的 FILS 变体（例如跨 AKM PMKID 链接、M2 放大、缓存不同步重装）：可以考虑更高一级会议。

---

## 4. 问题三：面向攻击 (2)(3) 的专用形式化方法（PAW-KI）

### 4.1 为什么需要新方法

攻击 (2)(3) 有共同点：

- 它们都不违反消息层的 secrecy/authentication；
- 它们取决于**工作/装钥发生的时机、次数、状态**；
- ProVerif 擅长消息逻辑，但不擅长计数器和全局状态；
- Tamarin 擅长 global state，但消息模型细节多、成本高；
- ASMETA/SPIN 擅长有限状态，但不擅长密码协议消息。

因此需要一个**分层的、可复用的**方法，而不是为 FILS 写一次性模型。

### 4.2 方法名与两个性质模板

本文建议称 **PAW-KI**（Pre-Authentication Work + Key Installation）：

#### PAW：预认证工作量模板

事件：

```text
Start(role, peer, sid)
Work(role, peer, sid, phase, cost)
Auth(role, peer, sid)
Slot(i)
```

性质：

| 编号 | 性质 | ProVerif 查询 |
|---|---|---|
| PAW-1 | 未认证工作不可达 | `event(Work(r,p,s,ph,c)) ==> event(Auth(p,s))` |
| PAW-2 | 工作一定对应真实启动 | `event(Work(r,p,s,ph,c)) ==> event(Start(p,r,s))` |
| PAW-3 | 有限槽可被占满 | `event(Slot(1)) && ... && event(Slot(n))` |
| PAW-4 | 工作成本标注 | 在事件中携带 `cost`，人工/脚本求和 |

PAW-1 是最强目标，很多协议会失败；PAW-2 是“非空性/真实性”目标；PAW-3 把“资源耗尽”降为可达性问题；PAW-4 把定量成本留给工程评估。

#### KIS：密钥安装状态模板

事件：

```text
Derive(key, sid)
Install(entity, key, sid, epoch)
Use(key, counter)
```

性质：

| 编号 | 性质 | 工具 |
|---|---|---|
| KIS-1 | 同一 key 在同一会话只安装一次 | ProVerif 事件查询 |
| KIS-2 | 同一 key 的计数器单调递增 | Tamarin global state |
| KIS-3 | 不同会话的 key 不同 | ProVerif 唯一性查询 |
| KIS-4 | 安装的 key 必须来自派生 | ProVerif `Install ==> Derive` |
| KIS-5 | 重装后不得复用旧计数器 | Tamarin/ASMETA |

KIS-1 的 ProVerif 表达：

```proverif
query e:bitstring, k:bitstring, s:bitstring;
  event(Install(e,k,s,ep1)) && event(Install(e,k,s,ep2)) ==> ep1 = ep2.
```

KIS-2 需要显式计数器，ProVerif 不适合；用 Tamarin 的 global state 或 ASMETA 的有限状态机。

### 4.3 双层工作流

```text
             ┌─────────────────────────────┐
             │ Layer 1: 消息逻辑（ProVerif） │
             │  secrecy / auth / agreement  │
             └──────────────┬──────────────┘
                            │ Derive(k,sid) 事件
                            │ 精化义务 R1/R2
             ┌──────────────▼──────────────┐
             │ Layer 2: 状态机（Tamarin/ASMETA）│
             │  Install / epoch / counter   │
             └──────────────┬──────────────┘
                            │ 反例投影
             ┌──────────────▼──────────────┐
             │ 攻击轨迹 + 标准条款映射       │
             └─────────────────────────────┘
```

**精化义务**：

- R1：Layer 2 的每个 `Install(e,k,sid,ep)` 必须对应 Layer 1 的一个 `Derive(k,sid)`；
- R2：Layer 1 的每个 `Derive(k,sid)` 必须能在 Layer 2 找到唯一的安装点（或明确标记“不安装”）；
- R3：Layer 2 的消息顺序必须与 Layer 1 的协议消息顺序一致；
- R4：Layer 2 的计数器/epoch 初值与标准条款一致。

**攻击投影**：

- Layer 2 找到 `Reinstall` 轨迹 → 按 R1/R3 投影回 Layer 1 的消息序列；
- Layer 1 找到 secrecy 反例 → 检查 Layer 2 是否有对应的状态泄漏；
- 两者不一致 → 说明模型抽象有误，而不是协议有攻击。

### 4.4 跨协议实例化

| 协议 | 预认证工作（PAW） | 装钥点（KIS） | 重放触发 | 本文结果 |
|---|---|---|---|---|
| FILS SK | M1/M2 的 DH、PTK、状态 | M4 后（AP 在 M3 校验后） | 重放 M3 | PAW 失败、KIS-1 失败（`FILS_DOS_M1M2.pv`、`FILS_KRACK_SK_*`） |
| FILS PK | 同上（签名在 M3） | 同上 | 重放 M3 | 同上（`FILS_KRACK_PTK_*`） |
| 4-way | Msg1（无 MIC）→ STA 算 PTK、回 Msg2 | STA 收 Msg3 后 | 重放 Msg3（客户端侧重装） | PAW 失败、KIS-1 失败（`METHOD_4WAY_PAW_KIS_*`） |
| FT | ReassocReq/Resp | ReassocResp 后 | 重放 ReassocReq | 未建模（模板可直接套用） |
| TPK | TPK Request/Response | TPK 完成后 | 重放 | 未建模（Kraken 已示受影响） |
| SAE | Commit/Confirm | Confirm 后 | 重放 Confirm | 未建模（有 anti-replay，作为对照） |

这张表是“方法可分析多种协议”的核心证据：同一个 PAW/KIS 模板，只需替换协议消息与装钥点。

#### 4.4.1 第二个协议的落地实例：WPA2 4-way

为了不只停留在表格上，本文用同一套事件/查询写了 4-way 的两个模型：

- `METHOD_4WAY_PAW_KIS_bad.pv`：无去重；
- `METHOD_4WAY_PAW_KIS_good.pv`：按 `(ANonce, SNonce)` 去重。

模型只保留与 PAW/KIS 相关的消息（Msg1–Msg4、PTK/KEK/KCK 派生、Msg3 用 KEK 加密 GTK），不重复 4-way 的完整密码学分析（那部分见 Cremers et al., USENIX Security 2020）。

关键结果：

```text
# bad 与 good 都有的 PAW 结果
RESULT event(StaWorkMsg2(s,a,an,k)) ==> event(ApSentMsg1(a,s,an)) is false.
# bad
RESULT not event(StaReinstalls(s,a,an,k)) is false.   ← 重装可达
RESULT not event(ReplaySeen(s,a,an))      is false.   ← 重放分支可达（非空验证）
# good
RESULT not event(StaReinstalls(s,a,an,k)) is true.    ← 去重后不可达
RESULT not event(ReplaySeen(s,a,an))      is false.   ← 仍会处理重放
# 两版共同的机密性
RESULT not attacker(probe[]) is true.
RESULT not attacker(gtk[])   is true.
```

三点值得注意：

1. **PAW 在 4-way 上确实失败**：Msg1 没有 MIC，攻击者可以自造 `ANonce`，STA 会照样算 PTK、分配状态、回 Msg2。这对应真实世界里的 “Msg1 泛洪/伪造”类拒绝服务面。
2. **KIS-1 的修复只影响重装，不影响 PAW**：good 版只把 `StaReinstalls` 的查询结果从 false 变成 true，PAW 查询仍为 false。这说明两个目标是**正交**的，必须分别验证，正好支撑“双层方法”的必要性。
3. **模型写错会立刻被机密性查询抓住**：第一版把 GTK 明文放在 Msg3 里，`attacker(gtk)` 立刻变成 false；改为 `enc((GTK, MIC), KEK)` 后才恢复 true。这可以作为“基线查询用于防建模错误”的实例写进论文的可信度讨论。

### 4.5 工具与评估计划

1. **ProVerif 模板**：
   - PAW：`Work`/`Auth`/`Slot` 事件 + 查询；
   - KIS-1/3/4：`Derive`/`Install` 事件 + 查询；
   - 复用本项目的 `FILS_DOS_M1M2.pv`、`FILS_KRACK_*` 作为 FILS 实例，
     `METHOD_4WAY_PAW_KIS_*` 作为 4-way 实例。
2. **Tamarin 模板**：
   - 用 global state 建模 `INSTALLED`/`WAIT_M4`/`DONE`；
   - 用 `Counter` 或 `epoch` 建模 PN/重放计数器；
   - 证明 KIS-2/KIS-5。
3. **ASMETA/SPIN**：
   - 把 802.11 状态机抽成有限状态；
   - 验证“成功关联删除旧 PTKSA”与“缓存重发”的交互；
   - 验证槽耗尽。
4. **评估指标**：
   - 属性数、模型行数、运行时间、反例长度；
   - 跨协议覆盖率；
   - 与人工分析（Kraken）的一致性；
   - 实现验证（hostapd/wpa_supplicant 代码路径）。

### 4.6 有效性威胁

- **完美密码假设**：ProVerif 的 Dolev-Yao 模型不覆盖 AES-SIV/AEAD 的计算安全性；
- **状态机忠实性**：Layer 2 的状态机是否与标准/实现一致，需要人工审计；
- **成本抽象**：PAW 只证明“工作可达”，不证明“资源耗尽”；
- **PMKID 范围**：链接性依赖 PMKSA 复用；不同 PMKSA/不同 AP 的结论不同；
- **实现差异**：wpa_supplicant 的防重装不代表所有实现。

---

## 5. 建议的下一步

### 5.1 短期（1–2 周）

1. 用 `reverify_all.ps1` 重跑全部模型，并把本文的三个扩展模型补进
   `FILS安全问题汇总.md` 的扩展表（§15 已补）；
2. 用 Tamarin 复现 `FILS_KRACK_SK_bad` 的轨迹，验证 KIS-2（计数器单调）；
3. 为 `FILS_DOS_M1M2.pv` 增加“成本标注”版本（`ApWorkM1(cost1)`、`ApWorkM2(cost2)`），为工程评估提供输入；
4. 在 hostapd/wpa_supplicant 中定位 FILS 的 M3 处理与装钥路径，确认“重放是否重装”。

### 5.2 中期（1–2 月）

1. 把 PAW-KI 模板推广到 FT/TPK（4-way 已完成，见 §4.4.1）；
2. 给出标准条款映射表（每条规则对应 §12.11.x）；
3. 形成论文初稿：方法 + FILS 案例 + 跨协议评估 + 实现验证；
4. 评估目标会议（C 级：ICC/GLOBECOM/WCNC/TrustCom/PST 等，按当年 CCF 目录确认）。

### 5.3 风险与取舍

- 如果只做 FILS，不建议投 C 级正会；工作坊更合适；
- 如果做 PAW-KI + 跨协议 + 实现验证，C 级有希望，但需要 2–3 个月的额外工作；
- 如果能发现**新的** FILS 变体（例如 PMKID 跨 AKM 链接、M2 放大、缓存不同步导致的重装），则可以考虑更高一级的会议。

---

## 6. 复现命令

```powershell
$exe = "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode\proverifbin2.05\proverif.exe"
$dir = "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode"

# 基线
& $exe "$dir\FILS_SK.pv"
& $exe "$dir\FILS_PK.pv"

# 隐私
& $exe "$dir\FILS_SK_PRIVACY.pv"
& $exe "$dir\FILS_SK_PRIVACY_MACBOUND.pv"
& $exe "$dir\FILS_PK_PRIVACY.pv"
& $exe "$dir\FILS_PRIVACY_EQUIV.pv"

# DoS
& $exe "$dir\FILS_DOS_M1M2.pv"

# KRACK
& $exe "$dir\FILS_KRACK_SK_bad.pv"
& $exe "$dir\FILS_KRACK_SK_good.pv"
& $exe "$dir\FILS_KRACK_PTK_bad.pv"
& $exe "$dir\FILS_KRACK_PTK_good.pv"

# 方法可移植性：4-way 上的 PAW + KIS
& $exe "$dir\METHOD_4WAY_PAW_KIS_bad.pv"
& $exe "$dir\METHOD_4WAY_PAW_KIS_good.pv"

# 一键重跑全部模型（含上面所有文件）
& "$dir\reverify_all.ps1"
```

---

## 7. 结果总表

| 模型 | 目标 | 结果 | 含义 |
|---|---|---|---|
| `FILS_SK.pv` | 标准 SK 目标（22 条） | 全 true | 标准目标成立 |
| `FILS_PK.pv` | 标准 PK 目标（17 条） | 全 true | 标准目标成立 |
| `FILS_SK_PRIVACY.pv` | G-P1 同 PMKID 不跨会话 | false | 可链接 |
|  | G-P2 同 PMKID 不跨 MAC | false | MAC 随机化无效 |
|  | GTK/TK 保密 | true | 隐私失败≠机密性失败 |
| `FILS_PK_PRIVACY.pv` | 同上 | 同上 | 结论一致 |
| `FILS_SK_PRIVACY_MACBOUND.pv` | G-P2 同 PMKID 不跨 MAC（按 (SPA,PMKID) 查找） | **true** | 参考实现下不再跨 MAC 链接；结论实现相关 |
| `FILS_PRIVACY_EQUIV.pv` | 观察等价 | cannot be proved | 在“换 MAC 仍发同一 PMKID”前提下可区分 |
| `FILS_DOS_M1M2.pv` | ApWorkM1 ⇒ StaStart | false | 未认证工作可达 |
|  | ApWorkM2 ⇒ StaStart | false | M2 阶段同样可达 |
|  | 3 个槽被同一伪造身份占满 | 可达 | 有限槽可被未认证方耗尽 |
|  | HonestDone | 可达 | 非空验证 |
| `FILS_KRACK_SK_bad.pv` | ApReinstalls 不可达 | false | 可重装 |
| `FILS_KRACK_SK_good.pv` | ApReinstalls 不可达 | true | 去重修复有效 |
| `FILS_KRACK_PTK_bad.pv` | ApReinstalls 不可达 | false | PK 分支可重装 |
| `FILS_KRACK_PTK_good.pv` | ApReinstalls 不可达 | true | PK 去重有效 |
| `METHOD_4WAY_PAW_KIS_bad.pv` | PAW：StaWorkMsg2 ⇒ ApSentMsg1 | false | 伪造 Msg1 可让 STA 做工作 |
|  | KIS-1：StaReinstalls 不可达 | false | 重放 Msg3 可重装 PTK |
|  | GTK/TK 保密 | true | 重装不泄露密钥 |
| `METHOD_4WAY_PAW_KIS_good.pv` | KIS-1：StaReinstalls 不可达 | true | 去重修复有效 |
|  | PAW：StaWorkMsg2 ⇒ ApSentMsg1 | false | 去重不修复 PAW（两目标正交） |

---

## 8. 参考文献（与本文直接相关）

1. IEEE Std 802.11-2024, §12.11（FILS）。
2. M. Vanhoef, F. Piessens, “Release the Kraken: New KRACKs in the 802.11 Standard,” CCS 2018.
3. M. Vanhoef, F. Piessens, “Key Reinstallation Attacks: Forcing Nonce Reuse in WPA2,” CCS 2017.
4. C. Cremers, B. Kiesl, N. Medinger, “A Formal Analysis of IEEE 802.11's WPA2,” USENIX Security 2020.
5. R. R. Singh et al., “Modelling of 802.11 4-Way Handshake Attacks and Analysis of Security Properties,” STM 2020.
6. L. Zhang, “Design of efficient and secure authentication schemes in IEEE 802.11ah networks,” NTU Ph.D. thesis, 2018.
7. S. Lee, B. H. Chung, “Denial of Service Attack against IEEE 802.11 WLAN Fast Initial Link Setup Technology,” IJCSEE 2015.
8. 本项目：`FILS形式化分析调研.md`（研究现状与新颖性定位）。
