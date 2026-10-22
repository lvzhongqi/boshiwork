# FILS 认证协议 UML 序列图（Mermaid）

> 版式参照 WCNC 2019 论文 Figure 1；消息内容按 IEEE 802.11ai / 802.11-2024 §12.11 与最初整理的 FILS 流程。

## 路径 A：FILS Public Key Authentication（算法 6，无 TTP）

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "fontFamily": "Microsoft YaHei, Noto Sans SC, sans-serif",
    "fontSize": "15px",
    "primaryColor": "#ffffff",
    "primaryTextColor": "#111111",
    "primaryBorderColor": "#111111",
    "lineColor": "#111111",
    "secondaryColor": "#f7f7f7",
    "tertiaryColor": "#ffffff",
    "actorBkg": "#ffffff",
    "actorBorder": "#111111",
    "actorTextColor": "#111111",
    "actorLineColor": "#333333",
    "signalColor": "#111111",
    "signalTextColor": "#111111",
    "noteBkgColor": "#ffffff",
    "noteBorderColor": "#444444",
    "noteTextColor": "#111111",
    "activationBkgColor": "#f2f2f2",
    "activationBorderColor": "#999999",
    "sequenceNumberColor": "#111111"
  },
  "themeCSS": "rect.note { fill:#ffffff !important; stroke:#444444 !important; stroke-dasharray:6 4 !important; }",
  "sequence": {"wrap": true, "width": 180, "height": 55, "mirrorActors": false, "showSequenceNumbers": false, "messageMargin": 42, "noteMargin": 12}
}}%%
sequenceDiagram
    title FILS Public Key Authentication（算法 6，无 TTP）
    participant STA
    participant AP

    Note over STA,AP: 发现 + 共享知识<br/>FILS Indication（AKM=6）<br/>STA：skSTA + AP 可信公钥<br/>AP：skAP + STA 可信公钥<br/>无 TTP；群来自 DLCGroupTable

    Note over STA,AP: ① 发送前计算<br/>选群 G、生成 (skSTA,gSTA)<br/>生成 SNonce、FILS Session<br/>可选 PMKID List<br/>gSTA 编码进 FFE

    STA->>AP: Auth (Seq=1)<br/>ANA=6, G, FFE=gSTA, SNonce, Session, RSNE<br/>（1 个 Pairwise Cipher + 1 个 AKM）<br/>可选 PMKID List
    Note over STA,AP: ② AP 接收后处理<br/>G 不支持 → Status 77<br/>NIST SP 800-56A 校验 gSTA<br/>生成 ANonce、(skAP,gAP)<br/>DHss = scalar-op(<br/>skAP, gSTA)

    AP->>STA: Auth (Seq=2)<br/>ANA=6, Status=0, G, FFE=gAP, ANonce, Session, RSNE<br/>（缓存时含选中的 PMKID）
    Note over STA,AP: ③ STA 接收后处理<br/>校验 G/Session、gAP<br/>DHss = scalar-op(<br/>skSTA, gAP)<br/>推导 PMK/PMKID/PTK<br/>删除 DHss

    Note over STA,AP: ④ 双方独立执行密钥推导<br/>PMK = HMAC-Hash(SNonce ‖ ANonce, DHss)<br/>PMKID = Truncate-128(Hash(gSTA ‖ gAP))<br/>PTK = PRF-X(PMK, "FILS PTK Derivation",<br/>SPA ‖ AA ‖ SNonce ‖ ANonce)<br/>→ ICK / PTK-KEK / TK

    STA->>AP: (Re)Assoc Request<br/>KeyAuth = Sig-STA(gSTA‖gAP‖SNonce‖ANonce‖<br/>STA-MAC‖AP-BSSID)<br/>AAD=Capability…Session<br/>AEAD(PTK-KEK)；FILS Public Key = STA 证书/公钥
    Note over STA,AP: ⑤ AP 接收后处理<br/>校验 Session / AEAD / RSNE<br/>RFC 5280 验证书链并验签<br/>失败 → Status 112<br/>成功 → 安装 PTKSA

    AP->>STA: (Re)Assoc Response<br/>KeyAuth = Sig-AP(gAP‖gSTA‖ANonce‖SNonce‖<br/>AP-BSSID‖STA-MAC)<br/>Key Delivery = GTK/IGTK/BIGTK/WIGTK<br/>AEAD(PTK-KEK)
    Note over STA,AP: ⑥ STA 接收后处理<br/>校验 Session / AEAD / RSNE<br/>验证 AP 签名<br/>安装 TK、GTK<br/>PTKSA 完成

    Note over STA,AP: FILS PK 认证完成：4 帧完成认证 + 关联 + 密钥确认；无 TTP、无 4 次 EAPOL 握手

```

## 路径 B：FILS Shared Key Authentication（算法 4/5，有 TTP）

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "fontFamily": "Microsoft YaHei, Noto Sans SC, sans-serif",
    "fontSize": "15px",
    "primaryColor": "#ffffff",
    "primaryTextColor": "#111111",
    "primaryBorderColor": "#111111",
    "lineColor": "#111111",
    "secondaryColor": "#f7f7f7",
    "tertiaryColor": "#ffffff",
    "actorBkg": "#ffffff",
    "actorBorder": "#111111",
    "actorTextColor": "#111111",
    "actorLineColor": "#333333",
    "signalColor": "#111111",
    "signalTextColor": "#111111",
    "noteBkgColor": "#ffffff",
    "noteBorderColor": "#444444",
    "noteTextColor": "#111111",
    "activationBkgColor": "#f2f2f2",
    "activationBorderColor": "#999999",
    "sequenceNumberColor": "#111111"
  },
  "themeCSS": "rect.note { fill:#ffffff !important; stroke:#444444 !important; stroke-dasharray:6 4 !important; }",
  "sequence": {"wrap": true, "width": 180, "height": 55, "mirrorActors": false, "showSequenceNumbers": false, "messageMargin": 42, "noteMargin": 12}
}}%%
sequenceDiagram
    title FILS Shared Key Authentication（算法 4/5，有 TTP）
    participant STA
    participant AP
    participant TTP as TTP / AS

    Note over STA,AP: 发现 + 共享知识<br/>FILS Indication<br/>AKM=4/5、PFS 位、TTP realm<br/>STA↔TTP 共享 rRK<br/>AP 经安全信道取 rMSK<br/>AP 可选缓存 PMKSA

    Note over STA,AP: ① 发送前计算<br/>生成 SNonce、FILS Session<br/>构造 EAP-Initiate/Reauth<br/>（B=0,L=1,ID=0）<br/>PFS：选 G、(skSTA,gSTA)<br/>可选 PMKID List

    STA->>AP: Auth (Seq=1)<br/>ANA=4/5, SNonce, Session<br/>RSNE[+PMKID List]<br/>Wrapped Data=EAP-Initiate/Reauth<br/>[G, FFE=gSTA]（仅 PFS）
    Note over AP,TTP: ② AP 接收后处理<br/>G 不支持 → 77<br/>PFS 校验 gSTA<br/>PMKID 命中 → 用缓存 PMK<br/>跳过 TTP<br/>无 EAP-Initiate → 53<br/>否则转发 TTP

    AP->>TTP: EAP-Initiate/Reauth<br/>（RADIUS/Diameter）
    Note over AP,TTP: ③ TTP 接收后处理<br/>验证 rRK / EAP-RP<br/>失败 → R=1<br/>成功 → 派生 rMSK<br/>返回 EAP-Finish(R=0)

    TTP->>AP: EAP-Finish/Reauth (R=0/1) + rMSK<br/>rRK/rMSK 生命周期 (L=1)
    Note over AP,TTP: ④ AP 处理<br/>保存 rMSK<br/>PFS：DHss=scalar-op(<br/>skAP,gSTA)<br/>构造 Auth (Seq=2)

    AP->>STA: Auth (Seq=2)<br/>ANA=4/5, Status=0, ANonce, Session<br/>Wrapped Data=EAP-Finish/Reauth<br/>[G, FFE=gAP]；[PMKID]
    Note over STA,AP: ⑤ STA 接收后处理<br/>校验 ANA/PMKID/Session<br/>PFS 参数对称<br/>EAP-Finish R=0 → rMSK<br/>校验 gAP；计算 DHss<br/>推导 PMK/PMKID/PTK<br/>删除 rMSK、DHss

    Note over STA,AP: ⑥ 双方独立执行密钥推导<br/>无 PFS：PMK=HMAC(SNonce‖ANonce,rMSK)<br/>有 PFS：PMK=HMAC(SNonce‖ANonce,rMSK‖DHss)<br/>PMKID=Truncate-128(Hash(EAP-Initiate/Reauth))<br/>PTK=PRF-X(PMK, "FILS PTK Derivation",<br/>SPA‖AA‖SNonce‖ANonce)<br/>→ ICK / PTK-KEK / TK

    STA->>AP: (Re)Assoc Request<br/>KeyAuth=HMAC-ICK(SNonce‖ANonce‖<br/>STA-MAC‖AP-BSSID[‖gSTA‖gAP])<br/>AAD=Capability…FILS Session<br/>AEAD(PTK-KEK)
    Note over AP,TTP: ⑦ AP 接收后处理<br/>校验 Session/AEAD/RSNE<br/>构造 KeyAuth' 比对<br/>失败 → Status 112<br/>删 ICK/KEK/TK/PTKSA

    AP->>STA: (Re)Assoc Response<br/>KeyAuth=HMAC-ICK(ANonce‖SNonce‖<br/>AP-BSSID‖STA-MAC[‖gAP‖gSTA])<br/>Key Delivery=GTK/IGTK/BIGTK/WIGTK<br/>AEAD(PTK-KEK)
    Note over STA,AP: ⑧ STA 接收后处理<br/>校验 Session/AEAD/RSNE<br/>校验 KeyAuth<br/>安装 TK、GTK<br/>PTKSA 完成

    Note over STA,TTP: FILS SK 认证完成：4 帧完成认证 + 关联 + 密钥确认；TTP 交互不增加 STA 往返<br/>变体：PMKSA 缓存命中时跳过 TTP，不新建 PMKSA、仍新建 PTKSA；无 PFS 时无 G/FFE；2024 缓存+DH 时 PTK 追加 DHss

```
