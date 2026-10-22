# SEF（Secure and Efficient FILS）认证协议 UML 序列图

> 依据：L. Zhang & M. Ma, “Secure and Efficient Fast Initial Link Setup Scheme Design”, IEEE WCNC 2019, Figure 1（SEF Mechanism）。
>
> 记法：`{…}rIK` = 用 rIK 计算的 MIC（仅完整性保护，不加密）；`{…}PTK` = 用 PTK/KEK 的 AEAD 加密；`Seq` = 单调递增序列号，用于防重放。

```mermaid
sequenceDiagram
    participant STA
    participant AP
    participant AS

    Note over STA: ① 由 rRK 派生 rIK<br/>rRK 来自此前完整 802.1X/EAP（ERP）

    STA->>AP: Msg1　{SNonce, KeyName-NAI, Seq, Cryptosuite}rIK
    Note right of AP: ② 校验 Seq 单调递增<br/>AP 不持有 rIK，无法验证 MIC<br/>追加 ANonce，转发 Msg1'

    AP->>AS: Msg1'　ANonce, {SNonce, KeyName-NAI, Seq, Cryptosuite}rIK
    Note right of AS: ③ 由 KeyName-NAI 定位 rRK → 派生 rIK<br/>验证 Msg1' 的 MIC 与 Seq
    Note right of AS: ④ 验证成功：以 SNonce / ANonce 派生<br/>rMSK、PMK、PTK；计算 Auth-field（Key-auth）

    AS->>AP: Msg2'　PMK, PTK, rMSK, rIK, Auth-field, {KeyName-NAI, Seq, Cryptosuite}rIK
    Note right of AP: ⑤ 保存 PMK / PTK / rMSK / rIK / Auth-field<br/>构造并发送 Msg2；AP 不重复执行密钥派生

    AP->>STA: Msg2　{ANonce, {GTK, Auth-field}PTK, KeyName-NAI, Seq, Cryptosuite}rIK
    Note left of STA: ⑥ 用 rMSK、SNonce、ANonce 派生 PMK / PTK<br/>用 PTK 解密内层 {GTK, Auth-field}PTK
    Note left of STA: ⑦ 验证 Auth-field；成功则发送 ACK（Msg3）

    STA->>AP: Msg3　{Auth-field, Nonce, Seq}PTK
    Note right of AP: ⑧ 用 PTK 验证 Auth-field 与 Seq<br/>成功 → 认证完成；失败 → 回到初始状态等待新 Msg1<br/>已接受有效 Msg3 后不再回退或重装密钥（抗 KRA）

    Note over STA,AS: SEF 认证完成：PMK / PTK 已确认，GTK 已分发，进入数据保护
```
