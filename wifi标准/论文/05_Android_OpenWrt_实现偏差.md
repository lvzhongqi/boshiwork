# Android / OpenWrt / mac80211 的 FILS 实现偏差分析

- **日期**：2026-11-22
- **对象**：
  - `第三方hostapd/android_wpa_supplicant_8/`（LineageOS 镜像，含 hostapd + wpa_supplicant + src）
  - `第三方hostapd/openwrt_hostapd/`（OpenWrt 包 + 上游 hostap 2.12 固定提交 + 225 个补丁）
  - `第三方hostapd/other/mac80211/`（Linux `net/mac80211/fils_aead.c`）
- **基线**：`wpa_supplicant-2.12/`、`hostapd-2.12/`
- **配套**：`04_实现偏差与安全影响.md`（偏差 D1–D9 的详细论证与 ProVerif 结果）

---

## 0. 结论摘要

| 实现 | FILS 是否编译 | 关键偏差 | 与基线相比 |
|---|---|---|---|
| **Android（LineageOS 镜像）** | STA：**开**（`wpa_supplicant/android.config: CONFIG_FILS=y`）<br>AP：**关**（`hostapd/android.config` 无 FILS） | D1、D2、D3、D4、D5、D6、D7、D8 全部存在 | 与 2.12 **同源同行为**；无 OpenWrt 的 820 去重补丁 |
| **OpenWrt（main + 225 补丁）** | STA：**开**（`wpa_supplicant-full.config: CONFIG_FILS=y`）<br>AP：**关**（`hostapd-full.config: #CONFIG_FILS=y`） | D2–D8 全部存在；D1 被 **820 补丁部分收窄**（仅 pending response 的 1 秒窗口）；**另有独有偏差 O1**（patch 021 绕过 `tk_already_set` 保护） | 比基线多 225 个下游补丁；唯一改变 FILS 安全语义的是 **021**，方向是**变差** |
| **mac80211（Linux 内核）** | 只实现 FILS AEAD（关联帧保护） | **不是偏差**：严格校验 8 字节 Session、AAD 覆盖 MACs/nonces/Capab…Session，解密失败返回 `-EINVAL` | 为 D2/D4 提供驱动层兜底（仅 mac80211 系） |
| **INET-FILS（OMNeT++）** | 仿真，不是空口实现 | 不适用（应用层模拟） | 不下载/不评价为标准实现 |

**一句话**：Android 与 OpenWrt 的 wpa/hostapd **没有修复** 04 文档中的 FILS 偏差；Android 的代码与 2.12 逐函数一致（只有宏重命名），其“独有”仅体现在 **STA 侧默认启用 FILS** 的构建配置；OpenWrt 除了用 **820 补丁**把 D1 的窗口从“任意时刻”缩到“响应等待 TX status 的 1 秒内”，还用 **021 补丁**引入了上游没有的 **O1**——重放 Association Request 时先清除 `tk_already_set`，把 D1 的“断开”变成**同一 TK 的静默重装（PN 复位）**。mac80211 的 `fils_aead.c` 是唯一在代码层强制 Session/AAD 绑定的实现，但只覆盖 mac80211 系驱动。

---

## 1. 下载内容与版本

### Android

- 仓库：`https://github.com/LineageOS/android_external_wpa_supplicant_8`
- 分支/提交：`lineage-24.0` / `4d70ee052a9f65038a24ec7ea2f2bb3f92b17277`（2026-05-28）
- 目录：`hostapd/`、`wpa_supplicant/`、`src/`
- 构建开关：
  - `wpa_supplicant/android.config`：`CONFIG_FILS=y` → **STA 侧默认启用**
  - `hostapd/android.config`：无 `FILS` → **AP 侧默认不启用**
  - 通用 `defconfig` 中 `#CONFIG_FILS=y`、`#CONFIG_FILS_SK_PFS=y` 均为注释
- 规模：约 19.9 MB；`wpa_supplicant/wpa_supplicant.c` 中 `FILS` 108 次，`wpa_supplicant/sme.c` 71 次

### OpenWrt

- 仓库/提交：`openwrt/openwrt` main / `ef37e5ba83873cf321e44d4fcde07743aa769fc0`（2026-11-10）
- 包：`package/network/services/hostapd`（225 个补丁、配置、ubus/ucode 覆盖）
- 上游 pin：`w1.fi/hostap.git` / `831364bf02710ad09c2f27d3efa92abeeb5634c0`（2.12，2026-08-07）
- 补丁应用：`src/` overlay + GNU `patch -p1 --fuzz=3`，**225/225 成功**
- FILS 开关：
  - `files/wpa_supplicant-full.config`：`CONFIG_FILS=y`
  - `files/hostapd-full.config`：`#CONFIG_FILS=y`
- 与 FILS 相关的补丁：18 个；关键的是 **820-AP-Drop-a-Re-Association-Request-frame-while-a-respo.patch**

### mac80211

- `net/mac80211/fils_aead.c` / `.h`（Linux master，约 8.4 KB）
- 只做关联帧的 AES-SIV 加解密，不包含认证状态机

---

## 2. 与标准不符的点（按实现）

> 编号沿用 `04_实现偏差与安全影响.md`：
> D1 重放 M3 → AP 断开；D2 Session 不一致只打印；D3 AP 不做 Auth↔Assoc RSNE 比较；
> D4 接受缺失 RSNE；D5 状态码 53/15/113 被统一为 1；D6 FILS-FT MDE/FTE 未校验；
> D7 RSNXE 宽松；D8 Session 长度宽松。

### 2.1 Android（STA 侧偏差可实际触发）

| 偏差 | Android 代码 | 判定 |
|---|---|---|
| **D1** | `src/ap/wpa_auth.c:3586` `tk_already_set` → `-1`；`src/ap/ieee802_11.c:7297-7300` `fils_set_tk() < 0` → `ap_sta_disconnect` | **存在**；且 Android **没有** OpenWrt 的 `assoc_resp_pending` 去重（grep 为 0） |
| **D2** | `src/rsn_supp/wpa.c:6891-6894` 只打印 “FILS Session mismatch” | **存在** |
| **D3** | `src/ap/wpa_auth_ie.c:1360-1361` 直接覆盖 `sm->wpa_ie` | **存在** |
| **D4** | `src/rsn_supp/wpa.c:6900-6905` 缺 RSNE 继续接受（interop workaround） | **存在** |
| **D5** | 与 2.12 相同的 `UNSPECIFIED_FAILURE` 分支 | **存在** |
| **D6** | `src/rsn_supp/wpa.c:6341` `TODO: Check MDE and FTE payload` | **存在** |
| **D7** | `src/rsn_supp/wpa.c:6925-6935` RSNXE 宽松 | **存在** |
| **D8** | AP `wpa_fils_validate_fils_session` 仍接受 `ie[1] >= 1+8` | **存在** |
| FILS PK | 4 处 `TODO: FILS PK` | **未实现** |

**Android 特有风险**：`wpa_supplicant/android.config` 默认开 FILS，意味着 **STA 侧的 D2/D4/D6/D7 在 Android 设备上可达**（取决于厂商是否覆盖 `CONFIG_FILS`）；AP 侧默认不开，D1/D3 主要影响把 Android 当 AP/热点的场景。

### 2.2 OpenWrt（补丁没有修 FILS 语义）

| 偏差 | OpenWrt 状态 | 说明 |
|---|---|---|
| **D1** | **部分收窄** | 820 补丁在 `handle_assoc()` 中增加 `assoc_resp_pending`：成功响应等待 TX status 期间（最多 1 秒）丢弃新的 `(Re)Association Request`。这解决的是 MLO 关联竞态，**不是** FILS Session 已完成后的去重；窗口过后重放仍会进入 `fils_set_tk` → `ap_sta_disconnect`。 |
| **D2** | 存在 | 与上游相同的 log-only |
| **D3** | 存在 | `wpa_validate_wpa_ie` 覆盖，无 Auth↔Assoc 比较 |
| **D4** | 存在 | 缺 RSNE 继续接受 |
| **D5** | 存在 | 状态码仍统一为 1 |
| **D6** | 存在 | `TODO: Check MDE and FTE payload` |
| **D7** | 存在 | RSNXE 宽松 |
| **D8** | 存在 | Session 长度宽松 |

**18 个触碰 FILS 的补丁**中，绝大多数是 MLO/DSCP/MSCS/ubus 相关；只有 820 与关联/去重有关，且只覆盖 pending 窗口。没有补丁修复 D2–D8。

### 2.3 mac80211（唯一的“正向”实现）

`fils_aead.c` 在解密 `(Re)Association Response` 时：

- 要求 FILS Session 元素 **`datalen == 1 + 8`**，否则 `-EINVAL`；
- AAD 使用 5 个分量：AP BSSID、STA MAC、ANonce、SNonce、Capab…Session（含 Session）；
- `aes_siv_decrypt()` 失败即返回错误，帧被丢弃。

因此：**在 mac80211 系驱动上，D2/D4 的“会话/配置错绑”被内核 AAD 兜底**，supplicant 的 log-only 不会成为唯一防线。  
但：

- 只覆盖 mac80211（softMAC）；Android 大量使用 FullMAC/厂商驱动，是否校验 AAD 取决于驱动；
- 不覆盖 D1（重放仍可到 hostapd 并触发 deauth）、D3、D5–D8；
- 不覆盖 FILS PK。

### 2.4 其它实现

- **hostap 上游 2.12**：与 Android/OpenWrt 同源；D1–D9 同样存在。
- **FILS PK**：hostap 上游、Android、OpenWrt 全部 `TODO: FILS PK`；没有完整开源实现。
- **INET-FILS（ToyotaInfoTech）**：OMNeT++ 仿真，README 明确是应用层 EAP/FILS 模拟，不是空口实现；未纳入“标准一致性”评价。
- **商用 FullMAC 固件**：FILS（尤其 PK）可能在固件内实现，但闭源、不可审计。

---

## 3. 独有的不符合项（OpenWrt / Android / 上游 2.12 三方对比）

> **判定口径**
> - **独有**：只在 Android 或只在 OpenWrt 出现，上游 2.12 与另一实现都没有；
> - **共有**：D1–D8，三套实现同源同行为，不计入本节；
> - **配置差异**：代码相同，只是构建/默认值不同，单列为“暴露面”，不当作代码级不符。

| 编号 | 归属 | 证据（file:line） | 与 2.12 的差异 | 性质 | 影响 |
|---|---|---|---|---|---|
| **O1** | **OpenWrt 独有**（下游 patch 021） | 补丁后 `src/ap/ieee802_11.c:6943-6951`；`src/ap/wpa_auth.c:2609-2611`、`3723-3726`、`3731-3733`；`src/ap/ieee802_11.c:9315-9331`；补丁 `patches/021-fix-sta-add-after-previous-connection.patch:20-29` | `add_associated_sta()` 的删除条件增加 `(!reassoc && (sta->flags & WLAN_STA_AUTHORIZED))`，绕过 2.12 的 `!ft_tk && !fils_tk` 保护 | **不符合**：同一 PTK 被重复下装 | **中–高**：把 D1 的“断开”变成“静默重装同一 TK”，PN 复位 |
| **O2** | **OpenWrt 独有**（下游 patch 820） | `src/ap/ieee802_11.c:7382`、`7656`、`7972`、`8868`；`src/ap/sta_info.h`（`assoc_resp_pending_since`） | 成功响应等待 TX status 的 1 秒内丢弃重复 `(Re)Association Request` | 下游加固，**不是**不符合项 | 只把 D1 的时间窗从“任意时刻”缩到 1 秒；不修 D1 |
| **A1** | **Android 独有**（构建配置） | `wpa_supplicant/android.config` `CONFIG_FILS=y`；`hostapd/android.config` 无 FILS；`wpa_supplicant/Android.mk:17,302-303` | STA 侧默认编译 FILS，AP 侧默认不编译 | 配置选择，不是代码不符 | Android 终端默认暴露 D2/D4/D6/D7；热点不暴露 AP 侧 D1/D3 |
| **A2** | **Android 独有**（快照差异） | `src/rsn_supp/wpa.c:7072` `wpa_sm_store_ptk(sm, sm->bssid, ...)`；2.12 对应 `wpa_sm_get_auth_addr(sm)` | MLO 下 PTK 以 link BSSID 而非 MLD/auth 地址索引 | 802.11be MLO 互操作问题 | 功能问题，非直接安全偏差；源于 Android 2.12-devel 快照早于该修正 |
| **—** | 共有 | D1–D8 | 与 2.12 相同 | 见 04 文档 | 不重复计入 |

> 下表及 3.1 中未特别标注的 OpenWrt 行号，均指 `第三方hostapd/openwrt_hostapd/upstream-hostap-831364b/`（2.12 + 225 补丁后的树）。

### 3.1 O1：OpenWrt patch 021 把 D1 变成“静默 TK 重装”

**调用链（OpenWrt 补丁后）**

1. 已授权的 FILS STA 被重放一条 **Association Request**（不是 Reassociation）。FILS 关联帧的 AES-SIV AAD 只覆盖 `Capability Information … FILS Session`，**不覆盖 MAC 头/seq_ctrl**（`src/ap/wpa_auth.c:3488-3507`），因此攻击者可修改 Retry/seq 后原样注入，`fils_decrypt_assoc()` 仍然通过。
2. `handle_assoc()` → `add_associated_sta()`（`src/ap/ieee802_11.c:8087-8089`）。此时 `added_unassoc=0`、`AUTHORIZED=1`、`reassoc=0`，patch 021 新增的子句成立 → `hostapd_drv_sta_remove()` + `wpa_auth_sm_event(WPA_DRV_STA_REMOVED)`（`6949-6951`）。
3. `WPA_DRV_STA_REMOVED` 只执行 `sm->tk_already_set = false`（`src/ap/wpa_auth.c:2609-2611`），**不清 `PTK_valid`**。
4. 响应发出后 `handle_assoc_cb()` 调用 `fils_set_tk()`（`src/ap/ieee802_11.c:9322-9331`）；`tk_already_set` 已被清除 → 通过 `3723` 的检查 → `wpa_auth_set_key(..., KEY_FLAG_PAIRWISE_RX_TX)` 用**同一个 `sm->PTK.tk`** 再次下装（`3731-3733`）。驱动删除 STA 时已删除旧密钥，重装后 PN 从 0 开始。

**上游 2.12 在同一输入下的行为**

`add_associated_sta()` 的删除条件因 `fils_tk_already_set=1` 为假（`hostapd-2.12/src/ap/ieee802_11.c:6537-6541`），不删除、不复位；随后 `fils_set_tk()` 命中 `tk_already_set` → 返回 -1 → `ap_sta_disconnect()`，也就是 04 文档中 D1 的“断开”。

**结论**：O1 不是“新增一个可注入点”，而是把 D1 的失败方式从**可观测的断开**改成**不可观测的密钥重装**，从而可能把可用性故障升级为密钥流复用/旧数据帧重放。

**前提与边界**

- AP 侧必须启用 FILS（OpenWrt 默认 `#CONFIG_FILS=y`，需显式打开）；
- 与 D1 相同，需要 SA Query 未兜底（非 PMF 部署）；PMF+FILS 部署下 `check_sa_query()` 会先临时拒绝（`src/ap/ieee802_11.c:5575-5615`）；
- 只对 `Association`（`reassoc=0`）生效；FILS-FT 的 Reassociation 不触发该子句；
- 未做实机验证，结论来自代码路径分析；是否形成 PN 复位还取决于驱动在 `sta_remove` 时删密钥、`set_key` 时重置 PN（mac80211/nl80211 符合该行为，FullMAC 需另测）。

**修复建议**

- 把 patch 021 的子句收窄为 `(!reassoc && AUTHORIZED && !wpa_key_mgmt_fils(...))`，或在删除前判断 `fils_tk_already_set` 并保留 D1 的断开/去重语义；
- 更彻底：`WPA_DRV_STA_REMOVED` 同时清 `PTK_valid`/`fils_completed`，使重放无法复用旧 PTK。

### 3.2 O2：patch 820 是“独有缓解”，不是“独有偏差”

820 补丁在 `handle_assoc()` 入口增加 `assoc_resp_pending()` 判断：成功响应等待 TX status 期间（最多 `ASSOC_RESP_PENDING_MAX_SEC=1` 秒）丢弃新的 `(Re)Association Request`。它解决的是 MLO 下“响应尚未发出、STA 又发来第二份请求”的竞态，不是 FILS 会话完成后的去重；1 秒窗口过后重放仍会进入 O1/D1 的路径。因此它只能算“把 D1 的触发窗口变窄”，不能算修复，也不是新的不符合项。

### 3.3 为什么 Android 没有独有的代码级偏差

对 `fils_build_auth`、`fils_process_auth`、`fils_process_assoc_resp`、`fils_set_tk`、`fils_auth_pmk_to_ptk`、`fils_decrypt_assoc`、`fils_encrypt_assoc`、`handle_auth_fils`、`handle_assoc_cb` 逐函数对比后，Android 与 2.12 的差异只有两类：

1. **宏重命名**：`NONCE_LEN`→`FILS_NONCE_LEN`（都是 16）、`WLAN_EID_EXT_NONCE`→`WLAN_EID_EXT_FILS_NONCE`（都是 13），语义相同；
2. **缺少 2.12 新增分支**：`CONFIG_ENC_ASSOC`、`CONFIG_IEEE8021X_AUTH`、PMKSA-privacy 等（Android 的 hostapd 构建也未启用这些特性）。

`add_associated_sta()` 的条件与 2.12 完全一致（`src/ap/ieee802_11.c:5335-5342`），没有 patch 021 的子句。因此 Android 的“独有”只在**默认配置**：STA 开、AP 关（A1），以及快照较早带来的 MLO 地址索引差异（A2）。

### 3.4 审计边界

- 只审计了 LineageOS 镜像的 `hostapd/`、`wpa_supplicant/`、`src/` 与 OpenWrt 主仓库的 `package/network/services/hostapd`；厂商 `BoardConfig.mk`、内核驱动、闭源固件不在范围内。
- Android 厂商可能用 `BoardConfig.mk`/`device.mk` 覆盖 `CONFIG_FILS`，实际发货配置需按机型确认。
- O1 依赖驱动在 `sta_remove` 时删除成对密钥；若某驱动保留密钥或拒绝重装，表现会不同。

---

## 4. 对论文/审计的用法

1. **Android**：可作为“终端侧默认启用 FILS（STA）”的证据；D2/D4/D6/D7 在 Android 上可达，适合做“实现偏差”案例。
2. **OpenWrt**：可作为“发行版默认 STA 开、AP 关”的证据；820 补丁可作为“下游已注意到重复关联问题，但只修了 MLO 竞态、没修 FILS 重放”的论据；021 补丁则应作为“下游补丁引入新偏差（O1）”的反例——它把 D1 的断开改成静默 TK 重装。
3. **mac80211**：可作为“驱动层 AAD 兜底”的正向对照；说明 D2/D4 的可利用性依赖驱动，而不是 supplicant 单独决定。
4. **FILS PK**：三套实现都没有，继续作为“标准有、实现无”的发现。

---

## 5. 复现与文件位置

```text
第三方hostapd/
├── android_wpa_supplicant_8/        # Android: hostapd + wpa_supplicant + src
├── openwrt_hostapd/
│   ├── package/network/services/hostapd/   # 225 patches + configs + src overlay
│   ├── upstream-hostap-831364b/            # 2.12 + overlay + 225/225 patches
│   └── PATCH_STATUS.txt
├── other/mac80211/                  # fils_aead.c/.h
└── README.md
```

- Android：`wpa_supplicant/android.config` 的 `CONFIG_FILS=y` 是 STA 侧默认启用的直接证据。
- OpenWrt：`files/hostapd-full.config` 与 `files/wpa_supplicant-full.config` 的 FILS 开关差异。
- mac80211：`fils_aead.c` 的 `session->datalen != 1 + 8` 与 5 个 AAD 分量。

---

## 6. 结论

- **Android 与 OpenWrt 没有修复 04 文档中的 FILS 偏差**；Android 的 STA 侧还默认启用 FILS，使 D2/D4/D6/D7 更容易落地。
- **OpenWrt 的 820 补丁只收窄了 D1 的窗口**（pending response 的 1 秒），不是 FILS 会话去重；重放仍可导致 deauth。
- **OpenWrt 的 021 补丁引入了上游没有的 O1**：重放 Association Request 时先清 `tk_already_set`，把 D1 的“断开”变成“同一 TK 静默重装”，是本轮对比中唯一新增的、方向为负的 FILS 语义偏差；其可达性依赖“AP 开 FILS + 非 PMF + Association（非 Reassociation）”。
- **Android 没有独有的代码级 FILS 偏差**：逐函数对比只有宏重命名和缺少 2.12 新特性；其独有性在构建配置（STA 开、AP 关）。
- **mac80211 的 `fils_aead.c` 在驱动层强制 Session/AAD 绑定**，是唯一能兜底 D2/D4 的公开实现；但仅限 mac80211 系，且不覆盖 D1/D3/D5–D8。
- **FILS PK 在所有公开实现中仍为 TODO**；相关结论只能停留在规范级分析。
