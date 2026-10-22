# 在容器里运行 Orrery

[English](README.md)

一个镜像里装好了运行 Orrery 需要的全部环境：按 `pyproject.toml` 钉死版本的
Python 依赖、从官方源码编译的 ProVerif 2.05（构建时校验源码包哈希），以及 web
控制台。用的人只需要装 Docker，再准备一个自己的 API key。

镜像里**刻意不放**三样东西，它们都在挂载进来的工作目录里：

- **语料库正文。** ISO 标准的正文受版权保护，公开发布的镜像不能带。
- **录制好的 run。** 按需放进工作目录即可回放。
- **任何 key。** key 属于使用者本人，只写在他自己工作目录的 `config.yaml` 里。

## 工作目录

容器里的一切产出都落在一个目录里，它挂载到容器的 `/work`。这是唯一需要保留和
备份的目录，删掉容器、升级镜像都不影响它。

```
orrery-work/              挂载到容器的 /work
├── config.yaml           第一次启动时自动生成；在设置面板里填的 key 保存在这里
├── docs/                 自己的协议文档，一个协议一个子目录
│   └── MyProtocol/
│       ├── spec.md       主文档：.md / .txt / .pdf / .docx / .doc 都可以
│       └── refs/         可选：主文档引用的其他文档
├── runs/                 每次运行的全部产物：runs/<协议>/<run 名>/
├── recordings/           可选：用来回放的 run，结构和 runs/ 一样
└── corpus/               可选：VerdictBench 语料库，控制台的启动面板会扫描它
```

`config.yaml` 里有 key，所以不要把整个工作目录发给别人；要分享结果，只分享
`runs/` 下的某一个 run 目录。

## 使用

1. 安装 Docker：Mac 和 Windows 装 Docker Desktop，Linux 装 Docker Engine。
2. 新建一个空目录，放入拿到的 `compose.yaml`。Linux 用户先在里面建好
   `orrery-work` 目录；如果 `id -u` 不是 1000，再在同一目录建一个 `.env` 文件，
   写上 `ORRERY_UID=` 和 `ORRERY_GID=` 两行，值是自己的 `id -u` 和 `id -g`。
3. 在这个目录里启动：

   ```bash
   docker compose up -d
   ```

4. 浏览器打开 <http://127.0.0.1:8000>。控制台默认是回放模式，不需要 key。
5. 左上角切到 live，在 Config 面板里选模型后端、填自己的 key。
6. 把协议文档放进 `orrery-work/docs/<协议名>/`，在启动面板里浏览到
   `/work/docs/<协议名>`，选中文档，开始运行。
7. 停止：

   ```bash
   docker compose down
   ```

   正在跑的 run 会在下一个安全点停下并保存已有的结果，之后可以在页面上从某一步
   重入。

习惯命令行的也可以不开页面，直接跑一个协议：

```bash
docker compose run --rm orrery run --name MyProtocol --dir /work/docs/MyProtocol
```

## 交作业与回放

- **交什么：** `orrery-work/runs/<协议>/<run 名>/` 这一个目录，打包成 zip。不要交
  `latest`，那是一个指向最新 run 的链接。run 目录里的配置已经脱敏，不含 key。
- **怎么看：** 解压到自己工作目录的 `recordings/<协议>/<run 名>/`，打开控制台，
  回放模式下的列表里就有它。模型怎么提取的、每一轮说了什么、每个 verdict 从哪来，
  都能完整重放。

## 构建与发布

所有命令都在仓库根目录执行。`.dockerignore` 是白名单，只有源码进入构建上下文，
`config.yaml`、`runs/`、`tests/`、`experiments/` 都不会离开本机。

```bash
docker build -t orrery:1.0.1 .
```

同时出两种架构并推到镜像仓库。只出一种的话，另一种机器要在模拟层上跑
ProVerif，会慢很多：

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t <registry>/orrery:1.0.1 --push .
```

发出去的 `compose.yaml` 里，把 `image:` 的默认值改成上面推送的地址。如果对方
所在的网络访问 Docker Hub 不稳定，就推到他们能访问的仓库；或者导出成文件分发，
对方用 `docker load` 导入：

```bash
docker save orrery:1.0.1 | gzip > orrery-1.0.1.tar.gz
```

几个固定的约定：

- **镜像版本号**跟 `orrery/version.py` 的 `PROJECT_VERSION` 一致。
- **升级 ProVerif** 要同时改 `PROVERIF_VERSION` 和 `PROVERIF_SHA256` 两个构建参数。
  只改版本不改哈希，构建会失败；这是有意的，另一个版本可能给出不同的结论。
- **升级 Python 基础镜像**要同时改标签和摘要。
- **页面上锁定的配置项**由镜像的 `ORRERY_READ_ONLY` 决定，现在是求解器路径和
  run 目录。它们是镜像本身的事实，只能在 `config.yaml` 里改，页面上改不了。
- **许可证：** ProVerif 是 GPL-2.0。它的许可证和编译所用的源码包原样放在镜像的
  `/usr/local/share/doc/proverif/` 下。

镜像用常规方式把 Orrery 装进 `/opt/venv` 虚拟环境，不带源码树。
`ORRERY_HOME=/work` 告诉安装好的副本数据在哪里：默认的 `config.yaml`，以及配置里
相对路径的锚点。

## 常见问题

- **端口被占用：** 在 `.env` 里写 `ORRERY_PORT=8001`，然后打开 8001 端口。
- **Linux 上启动报工作目录不可写：** 工作目录要由自己创建，并按上面第 2 步设置
  `ORRERY_UID` 和 `ORRERY_GID`。目录不存在时 Docker 会以 root 身份创建它，容器里
  的用户就写不进去了。
- **大协议求解被判为内存超限：** 单个 ProVerif 最多用容器可用内存的 90%。在
  Docker Desktop 的资源设置里调大内存即可。
- **不要把端口开给其他机器：** 控制台没有登录，能连上端口的人就能用你的 key
  发起运行。`compose.yaml` 里的 `127.0.0.1` 必须保留。
