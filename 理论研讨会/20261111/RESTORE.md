# 恢复说明（在另一台电脑上重建这次的工作）

本目录是为「AutoGLM 安装与快速上手」这次会话导出的记录与可复用资产。

## 本目录新增的文件

| 文件 | 说明 |
| --- | --- |
| `session_transcript.md` | 本次会话的完整可读记录（用户/助手/工具调用/思考过程）。 |
| `session_export.json` | 本次会话的完整结构化数据（session + messages + parts），可用于归档或二次处理。 |
| `phone-copilot-run.ps1` | Phone Copilot 启动脚本，运行时会自动从 opencode 的 `auth.json` 读取 DeepSeek key。 |
| `Open-AutoGLM/` | 克隆的 Open-AutoGLM 仓库（含其 `venv`）。 |
| `phone-copilot-env/` | 为 phone-copilot 单独创建的 Python 虚拟环境。 |
| `RESTORE.md` | 本文件。 |

> 注意：`venv` / `*-env` 虚拟环境**不可跨机直接复制使用**（脚本内写死了本机的 Python 绝对路径与解释器路径）。换电脑后请按下面步骤重建虚拟环境。

## 新电脑的前置条件

1. Python 3.12+（`python --version` 验证）
2. Git
3. Android SDK Platform Tools（`adb`，加入 PATH），`adb version` 验证
4. （可选）有 Android 手机：开启「开发者模式 + USB 调试」，中文输入需装 ADB Keyboard

## 一、恢复会话记录

- 直接用编辑器/Markdown 阅读 `session_transcript.md` 即可了解这次做了什么、每一条命令与结果。
- `session_export.json` 为原始数据备份，不影响使用。

## 二、重建运行环境

把整个 `20261111` 目录拷到新电脑（建议保持相同目录结构），然后在该目录下执行：

### 1. Phone Copilot（本次最终采用的方案）

```powershell
python -m venv phone-copilot-env
.\phone-copilot-env\Scripts\python.exe -m pip install --upgrade pip
.\phone-copilot-env\Scripts\python.exe -m pip install phone-copilot -i https://mirrors.aliyun.com/pypi/simple/
```

### 2. Open-AutoGLM（第一版方案，可选）

```powershell
cd Open-AutoGLM
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
.\venv\Scripts\python.exe -m pip install -e . -i https://mirrors.aliyun.com/pypi/simple/
cd ..
```

依赖版本：phone-copilot 0.1.2（openai==2.20.0）；Open-AutoGLM 核心为 Pillow、openai。

## 三、恢复 DeepSeek/模型 API Key

`phone-copilot-run.ps1` 每次运行都会从下面这个文件读取 DeepSeek key：

```
%USERPROFILE%\.local\share\opencode\auth.json   ->   .deepseek.key
```

在新电脑上二选一：

- 用 opencode 重新登录/配置 DeepSeek，会自动生成该 `auth.json`；或
- 手动创建该文件，内容形如：`{ "deepseek": { "type": "api", "key": "你的key" } }`

> 出于安全考虑，本记录**不**包含明文 key。

## 四、使用（本机同款一条命令）

```powershell
powershell -ExecutionPolicy Bypass -File .\phone-copilot-run.ps1 "打开高德地图，导航至南京南高铁站"
```

## 重要限制（实测结论）

DeepSeek 的模型（`deepseek-chat` / `deepseek-flash`）**不接受图片**；`deepseek-v4-pro` 虽接受图片格式，但模型本身返回 “image unsupported”，**无法真正看到手机屏幕**。
而 Phone Copilot 依赖「截图 → 视觉模型理解界面」，因此用纯 DeepSeek 无法真正驱动手机。

要真正可用，把模型换成视觉模型（改命令参数即可），例如 ModelScope 的 AutoGLM-Phone-9B：

```powershell
.\phone-copilot-env\Scripts\phone-copilot.exe "打开微信，给文件传输助手发送：你好" `
  --base-url https://api-inference.modelscope.cn/v1 `
  --model ZhipuAI/AutoGLM-Phone-9B --api-key <ModelScope Token> --ccf 1000
```
