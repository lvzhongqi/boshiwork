# 归档模型（非标准级问题 / 历史版本）

这里的模型**仍然可以运行**，只是不再属于“证明标准本身有问题”的主集。
按 2026-11-14 的整理，主集只保留：

- 合规基线：`FILS_PK.pv`、`FILS_SK.pv`
- 标准级问题：`FILS_DOS_UNAUTH.pv`、`FILS_PMKID_LINK.pv`、`FILS_STATUS.pv`、`FILS_PFS.pv`
- 密钥重装：`FILS_KRACK_PTK_bad/good.pv`、`FILS_GTK_REPLAY_bad/good.pv`
- 标准依赖项：`FILS_EAPRP_SEQ.pv`、`FILS_EAPRP_SEQ_bad.pv`

## 归档原因

| 文件 | 类别 | 归档原因 |
|---|---|---|
| `FILS_PK_old.pv` | 历史版本 | STA/AP 写在同一进程自问自答，认证查询恒真，结论不可用 |
| `FILS_PRIVACY.pv` | 冗余 | 观测等价在 2.05 下 `cannot be proved`；可链接性的确定性结论由 `FILS_PMKID_LINK.pv` 给出 |
| `FILS_REPLAY.pv` | 冗余 | 消息重放已被 `FILS_PK.pv` / `FILS_SK.pv` 的 injective agreement 覆盖 |
| `FILS_CACHE.pv` | 冗余 | 缓存分支已被 PK/SK 的 C 分支覆盖；这里只测“不同步只失败” |
| `FILS_KEYREUSE.pv` | 实现偏差 | RNG/nonce 复用属于实现错误，不是标准允许的行为 |
| `FILS_STATUS_faulty.pv` | 实现偏差 | “失败后回退旧 PTK”违反 §12.11.2.6.2/6.3 |
| `FILS_PK_CERT.pv` / `_bad.pv` | 信任锚对照 | 证书主体绑定属于部署/实现策略；主集用 `FILS_PK.pv` 的可信公钥白名单抽象 |
| `FILS_PK_RAW.pv` / `_bad.pv` | 信任锚对照 | 原始公钥固定（TOFU vs 带外预置）属于部署问题 |
| `FILS_LATEAUTH.pv` / `_nobind.pv` | 实现偏差 | KeyAuth 漏绑 `gSTA/gAP` 属于不符合标准的实现 |

## 恢复方法

把这些 `.pv` 移回上一级目录即可，例如：

```powershell
Move-Item .\archive\FILS_PK_CERT_bad.pv ..
```

`reverify_all.ps1` 只扫描当前目录的 `*.pv`，不会自动运行归档模型。
