# 恢复说明（在另一台电脑上重建这次的工作）

本目录是「AutoGLM / Phone Copilot」这次工作的记录与可复用资产。
**2026-11-11 已在本机重新恢复并跑通真机演示**，下面以最新状态为准。

## 本目录文件

| 文件 | 说明 |
| --- | --- |
| `session_transcript.md` | 上一次会话的完整可读记录（安装与配置过程）。 |
| `session_export.json` | 上一次会话的结构化数据备份。 |
| `phone-copilot-run.ps1` | Phone Copilot 启动脚本，自动从 opencode 的 `auth.json` 读取 DeepSeek key。 |
| `phone-copilot-env/` | 重建后的 Python 3.12 虚拟环境（已装 phone-copilot 0.1.2）。 |
| `demo_home.png` | 演示前的手机桌面截图。 |
| `demo_calculator_12x31.png` | 计算器任务执行到 12×31（Agent 真实点击的结果）。 |
| `demo_settings.png` | 成功打开系统设置的截图。 |
| `phone-copilot-report.json/.html` | 最近一次任务的执行报告（可逐步骤回放）。 |
| `Open-AutoGLM/` | 第一版方案目录（当前为空，可选重装）。 |
| `RESTORE.md` | 本文件。 |

> 注意：虚拟环境**不可跨机直接复制使用**（脚本里写死了本机 Python 绝对路径）。换电脑后请重建 venv。

## 新电脑的前置条件

1. **Python 3.12+**（phone-copilot 源码使用 3.12 的 `type` 语法，3.10/3.11 跑不了）
2. Git
3. Android SDK Platform Tools（`adb` 加入 PATH）
4. Android 手机：开启「开发者模式 + USB 调试」；中文输入建议装 ADB Keyboard

## 一、重建 Phone Copilot 环境（推荐流程）

```powershell
# 1) 安装 Python 3.12（本机装在 C:\apps\path\python312）
#    可从 https://mirrors.huaweicloud.com/python/3.12.10/python-3.12.10-amd64.exe 下载

# 2) 重建 venv 并安装
C:\apps\path\python312\python.exe -m venv phone-copilot-env
.\phone-copilot-env\Scripts\python.exe -m pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/
.\phone-copilot-env\Scripts\python.exe -m pip install phone-copilot -i https://mirrors.aliyun.com/pypi/simple/

# 3) 验证
.\phone-copilot-env\Scripts\phone-copilot.exe --help
```

### 必做的 Windows 修复：截图必须用 exec-out

在 Windows 上，`adb shell screencap -p` 会把二进制 PNG 做 CRLF 转换，导致
`cannot identify image file`。`xpdc` 默认用的是 `shell`，需要改成 `exec-out`：

文件：`phone-copilot-env\Lib\site-packages\xpdc\adb\device.py`（约第 90 行）

```python
# 改前
cmd = [self._adb, '-s', self.device_id, 'shell', 'screencap', '-p']
# 改后
cmd = [self._adb, '-s', self.device_id, 'exec-out', 'screencap', '-p']
```

> 重装/升级 xpdc 后这个补丁会丢失，需要重新打。

## 二、恢复模型 API Key

`phone-copilot-run.ps1` 每次运行都会从下面文件读取 DeepSeek key：

```
%USERPROFILE%\.local\share\opencode\auth.json   ->   .deepseek.key
```

在新电脑上二选一：

- 用 opencode 重新登录/配置 DeepSeek，会自动生成该 `auth.json`；或
- 手动创建：`{ "deepseek": { "type": "api", "key": "你的key" } }`

## 三、运行演示

```powershell
# 打开系统设置（Launch 动作，稳定成功）
powershell -ExecutionPolicy Bypass -File .\phone-copilot-run.ps1 -MaxSteps 6 "打开系统设置应用"

# 计算器任务（依赖模型坐标定位，可能点错）
powershell -ExecutionPolicy Bypass -File .\phone-copilot-run.ps1 -MaxSteps 12 "打开计算器，计算 12 乘以 34"
```

## 实测结论（2026-11-11 更新）

- 本机网关的 **`deepseek-chat` 具备视觉能力**：能准确读出手机截图中的时间、电量和全部应用名。
  - `deepseek-flash` 对图片返回空内容；`deepseek-v4-pro` 明确返回“无法读取图片”。**请用 `deepseek-chat`**。
- 2026-11-10 会话里“DeepSeek 完全无视觉”的结论**已过时**，以本次实测为准。
- **设备控制闭环已验证可用**：截图 → 模型推理 → ADB 点击/启动 → 再截图。
- 失败案例：计算器任务中模型把“4”误判成“1”、把“+”坐标定位错，导致 12×31 而不是 12×34。
  这是 DeepSeek 的 GUI 坐标定位能力不足，不是链路问题；要稳定完成精细点击，建议换用
  `AutoGLM-Phone-9B` 等专用 GUI 模型。

## 重要限制

Phone Copilot 依赖「截图 → 视觉模型理解界面 → 输出 0-999 坐标 → 点击」。
`deepseek-chat` 能看懂界面，但**坐标精度一般**；简单任务（启动 App、单步点击）可用，
需要精确点按的复杂任务建议换视觉 GUI 专用模型：

```powershell
.\phone-copilot-env\Scripts\phone-copilot.exe "打开微信，给文件传输助手发送：你好" `
  --base-url https://api-inference.modelscope.cn/v1 `
  --model ZhipuAI/AutoGLM-Phone-9B --api-key <ModelScope Token> --ccf 1000
```
