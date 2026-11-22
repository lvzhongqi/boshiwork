# Android / OpenWrt 的 hostapd 代码（本地副本）

本目录只保留了 **hostapd 相关部分**，不是完整 Android / OpenWrt 源码树。

- 下载方式：`git clone --depth 1 --filter=blob:none --sparse` + `git sparse-checkout`
- 日期：2026-11-22

---

## 1. `android_wpa_supplicant_8/`（19.9 MB）

**来源（AOSP 的镜像）**

- 仓库：`https://github.com/LineageOS/android_external_wpa_supplicant_8`
- 分支：`lineage-24.0`
- 提交：`4d70ee052a9f65038a24ec7ea2f2bb3f92b17277`（2026-05-28）
- 对应 AOSP 路径：`platform/external/wpa_supplicant_8`
  - 官方：`https://android.googlesource.com/platform/external/wpa_supplicant_8/`
  - 说明：本机访问 `android.googlesource.com` 超时，故用 LineageOS 的 GitHub 镜像；代码结构一致，厂商补丁可能略有差异。

**包含**

```text
hostapd/          ← Android 的 hostapd 主程序与 Android.mk/Android.bp
wpa_supplicant/   ← Android 的 wpa_supplicant 主程序（STA 侧）
src/              ← hostapd 与 wpa_supplicant 共享的协议/密码学代码
Android.bp / Android.mk / board_config_wpa_supplicant.mk
```

**FILS 相关**

- `hostapd/defconfig` 中：
  ```text
  # Fast Initial Link Setup (FILS) (IEEE 802.11ai)
  #CONFIG_FILS=y
  # FILS shared key authentication with PFS
  #CONFIG_FILS_SK_PFS=y
  ```
  默认**未启用**；`hostapd/android.config` 未出现 `FILS`，`hostapd/Android.mk` 也没有 `-DCONFIG_FILS`。
- 因此：**Android 树里有 FILS 源码，但默认构建不一定打开**；是否启用取决于设备 `BoardConfig.mk` / 厂商配置。
- 代码量核对：`src/ap/wpa_auth.c` 中 `FILS` 出现 167 次，`src/rsn_supp/wpa.c` 中 304 次，
  `wpa_supplicant/wpa_supplicant.c` 108 次，`wpa_supplicant/sme.c` 71 次。
- **STA 侧默认启用**：`wpa_supplicant/android.config` 中 `CONFIG_FILS=y`；
  `hostapd/android.config` 没有 FILS（AP 侧默认关）。

**用途**

- 对比 Android 与上游 hostap 的 FILS 实现差异；
- 检查 Android 的 `android.config` / `BoardConfig` 是否开启 FILS；
- 作为“终端侧实现”的证据。

---

## 2. `openwrt_hostapd/`（30.2 MB）

**来源**

- OpenWrt 仓库：`https://github.com/openwrt/openwrt`
- 分支：`main`
- 提交：`ef37e5ba83873cf321e44d4fcde07743aa769fc0`（2026-11-10）
- 包路径：`package/network/services/hostapd`

**包含**

```text
openwrt_hostapd/
├── package/network/services/hostapd/
│   ├── Makefile                 ← 固定上游 commit、构建变体、FILS 配置
│   ├── Config.in
│   ├── files/                   ← hostapd-full/mini/basic.config、wpad 脚本等
│   ├── patches/                 ← 225 个 OpenWrt 补丁
│   └── src/                     ← OpenWrt 自己的 ubus/ucode/build_features 覆盖文件
└── upstream-hostap-831364b/     ← 上游 hostap 源码（已 overlay + 打补丁）
```

**上游 pin**

- `PKG_SOURCE_URL=https://w1.fi/hostap.git`
- `PKG_SOURCE_VERSION=831364bf02710ad09c2f27d3efa92abeeb5634c0`
- 该 commit：`Update version number to 2.12`（2026-08-07）

**补丁应用结果**

- 先执行 `package/.../src/` 覆盖到源码树（OpenWrt 的 build 流程就是这样做的，例如 `src/utils/build_features.h`）。
- 再用 GNU `patch -p1 --fuzz=3` 应用 `patches/*.patch`：
  - **225 / 225 全部成功**
  - 状态：PATCH_STATUS.txt（225/225 成功，0 失败）
- 打完后 `src/ap/wpa_auth.c` 中 `FILS` 出现 161 次，`src/`、`hostapd/`、`wpa_supplicant/` 均为完整树。

**FILS 配置**

- `files/hostapd-full.config`：
  ```text
  # Fast Initial Link Setup (FILS) (IEEE 802.11ai)
  #CONFIG_FILS=y
  ```
  → **OpenWrt 的 hostapd 默认不编 FILS**。
- `files/wpa_supplicant-full.config`：
  ```text
  CONFIG_FILS=y
  ```
  → **wpa_supplicant 默认编 FILS**（STA 侧开、AP 侧关，生态不对称）。

**用途**

- 分析 OpenWrt 实际构建的 hostapd（含 225 个下游补丁）；
- 对照上游 2.12 与 OpenWrt 的差异（尤其是 ubus/ucode、mbedtls、mesh/DFS 补丁）；
- 作为“发行版实现”的证据。

---

## 3. 如何恢复 / 重建

### Android

```bash
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/LineageOS/android_external_wpa_supplicant_8.git
cd android_external_wpa_supplicant_8
git sparse-checkout set hostapd src
```

### OpenWrt 包

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/openwrt/openwrt.git
cd openwrt
git sparse-checkout set package/network/services/hostapd
```

### OpenWrt 上游 + 补丁

```bash
git init upstream && cd upstream
git remote add origin https://w1.fi/hostap.git
git fetch --depth 1 origin 831364bf02710ad09c2f27d3efa92abeeb5634c0
git checkout FETCH_HEAD
cp -r ../package/network/services/hostapd/src/* .
for p in ../package/network/services/hostapd/patches/*.patch; do
  patch -p1 --forward --fuzz=3 --no-backup-if-mismatch < "$p"
done
```

> 注意：OpenWrt 官方构建请在完整 OpenWrt 树里执行
> `make package/network/services/hostapd/{clean,compile}`，
> 它会自动处理 overlay、补丁顺序和配置；本目录的补丁树只是便于阅读/审计。

---

## 4. 重要提醒

1. **FILS 默认不编译**：Android 的 `hostapd/defconfig` 与 OpenWrt 的 `hostapd-full.config` 都把 `CONFIG_FILS` 注释掉了；分析“实现是否安全”前先确认目标固件的编译开关。
2. **Android 是镜像**：LineageOS 分支可能含厂商/社区补丁；若要严格对应 AOSP，请用官方 `android.googlesource.com` 或 `repo` 工具。
3. **OpenWrt 补丁树**是本机用 GNU patch 复现的；官方构建可能因配置变体（hostapd-full/mini/basic、mbedtls/wolfssl）略有不同。
4. 本目录只含 hostapd 相关代码；`wpa_supplicant/` 在 OpenWrt 上游树中有，但 Android 树未 sparse-checkout（如需可执行
   `git sparse-checkout add wpa_supplicant`）。

---

## 5. 补充：`other/mac80211/` 与 Android wpa_supplicant

### `other/mac80211/`

- 文件：`fils_aead.c`、`fils_aead.h`（Linux `net/mac80211/`）
- 作用：实现 FILS `(Re)Association Request/Response` 的 AES-SIV 加解密
- 关键点：
  - 要求 FILS Session 元素 `datalen == 1 + 8`；
  - AAD 使用 5 个分量：AP BSSID、STA MAC、ANonce、SNonce、Capab…Session；
  - 解密失败返回 `-EINVAL`，帧被丢弃。
- 它是目前**唯一在代码层强制 Session/AAD 绑定**的公开实现，但只覆盖 mac80211 系驱动。

### Android `wpa_supplicant/`

- 已从 codeload zip 补齐（`wpa_supplicant/` 目录），约 6 MB。
- `wpa_supplicant/android.config` 含 `CONFIG_FILS=y`，因此 Android 终端默认编译 FILS（STA 侧）；
  `wpa_supplicant/defconfig` 中仍是 `#CONFIG_FILS=y`。
- Android 的 FILS 关键函数与上游 2.12 同源，仍保留：
  - `fils_completed` 去重（好）
  - Session 不一致只打印（D2）
  - 缺 RSNE 继续接受（D4）
  - RSNXE 宽松（D7）
  - `TODO: FILS PK`、`TODO: Check MDE and FTE payload`（D6）

### 其它实现

- **INET-FILS（ToyotaInfoTech）**：OMNeT++ 仿真，应用层 FILS 模拟，不是空口实现；未下载（子模块较大）。
- **FILS PK**：hostap 上游、Android、OpenWrt 均未实现（`TODO: FILS PK`）。
- **商用 FullMAC 固件**：可能实现 FILS/PK，但闭源、不可审计。

详细偏差对照见 `../论文/05_Android_OpenWrt_实现偏差.md`。

