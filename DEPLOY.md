# AutoPM3 部署与本地测试指南

本项目是一个基于 Streamlit 的多页面应用，入口为 `app/main.py`（DeepSeek 页面）和 `app/pages/` 下的其它页面。下面分别说明：

0. [项目结构速览](#0-项目结构速览)
1. [本地直接用 Python 跑（开发推荐）](#1-本地直接用-python-跑开发推荐)
2. [用 Docker Compose 跑（最省事）](#2-用-docker-compose-跑最省事)
3. [用 `scripts/build.sh` 打版本化镜像](#3-用-scriptsbuildsh-打版本化镜像)
4. [手动 `docker build` / `docker run`](#4-手动-docker-build--docker-run)
5. [配置项 & 优先级](#5-配置项--优先级)

---

## 0. 项目结构速览

```
AutoPM3/
├── app/                       # 所有 Python 源码（包）
│   ├── main.py                # Streamlit 入口（DeepSeek 页面）
│   ├── pages/                 # 其它 Streamlit 页面（如 OpenAI Compatible）
│   ├── core/                  # 核心逻辑（query、table_functions、utils、streamlit_helpers）
│   ├── data_io/               # 离线工具（如 download_papers.py）
│   └── mineru/                # MinerU API 客户端（含 tests/）
│
├── data/                      # 运行时数据
│   ├── protein.txt            # 蛋白缩写映射（app 启动时读）
│   ├── xml_papers/            # download_papers.py 的输出
│   └── pdf_convert/           # MinerU 转换示例
│
├── benchmarks/                # PM3-Bench 评测数据集
├── docs/                      # 架构图 / 会议记录 / 开发计划
├── scripts/build.sh           # 版本化打 tag 工具
├── docker/                    # Dockerfile + docker-compose.yml
└── config/                    # 凭据模板（.env.example, secrets.toml.example）
```

注意：

- **真实 `secrets.toml` 必须在项目根的 `.streamlit/secrets.toml`**（Streamlit 默认搜索路径），不能放到 `config/`。
- **`.dockerignore` 必须在项目根**（Docker 工具链约束，从 build context 根读取）。
- **Dockerfile 用 `COPY app ./app` + `COPY data/protein.txt ./data/protein.txt`**：只把运行时需要的部分塞进镜像，docs/、benchmarks/、config/ 等不进镜像。

---

## 1. 本地直接用 Python 跑（开发推荐）

最快的本地调试方式：起一个虚拟环境，装依赖，跑 Streamlit。

### 1.1 前置条件

- Python 3.11（与 `Dockerfile` 中的基镜像保持一致）
- `git`

### 1.2 创建虚拟环境并安装依赖

```bash
# 克隆项目（如果还没有）
git clone https://github.com/ZzzPanda/AutoPM3.git
cd AutoPM3

# 建 venv
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 装依赖
pip install -r requirements.txt
```

> **关于 pip 安装慢/失败**：`requirements.txt` 里的 `lxml`、`greenlet` 等包在某些环境下需要本地编译。如果 `pip install` 报错，安装系统级编译工具后再试：
> - macOS：`xcode-select --install`
> - Ubuntu/Debian：`sudo apt-get install -y build-essential python3-dev`
> - Windows：安装 [Build Tools for Visual Studio](https://visualstudio.microsoft.com/visual-cpp-build-tools/)

### 1.3 配置 API 凭据

有两种方式，二选一即可（环境变量优先于 secrets 文件，详见 [§5](#5-配置项--优先级)）。

**方式 A：`.streamlit/secrets.toml`（Streamlit 原生方式，推荐本地用）**

```bash
# 模板在 config/，但真实的 secrets.toml 必须放在项目根的 .streamlit/ 下
# （Streamlit 启动时只从入口脚本所在目录或 ~/.streamlit 读 secrets.toml）
cp config/.streamlit/secrets.toml.example .streamlit/secrets.toml
# 编辑 .streamlit/secrets.toml，填入真实 Key
```

模板：

```toml
# DeepSeek 页面
deepseek_api_key = "sk-xxx"

# OpenAI Compatible 页面默认值
openai_api_url   = "https://api.openai.com/v1"
openai_model     = "gpt-4o-mini"
openai_api_key   = "sk-xxx"
```

**方式 B：导出环境变量**

```bash
export DEEPSEEK_API_KEY="sk-xxx"
export OPENAI_API_URL="https://api.openai.com/v1"
export OPENAI_MODEL="gpt-4o-mini"
export OPENAI_API_KEY="sk-xxx"
```

> 不想配任何 Key 也可以——打开页面后在输入框里手动填即可。

### 1.4 启动

```bash
streamlit run app/main.py
```

控制台会打印类似：

```
You can now view your Streamlit app in your browser.
  Local URL: http://localhost:8501
  Network URL: http://<your-lan-ip>:8501
```

浏览器打开 `http://localhost:8501` 即可使用。改代码后 Streamlit 会热重载。

### 1.5 常见坑

- **改了 secrets 不生效**：`secrets.toml` 是启动时读取的，保存后 Streamlit 会自动重启；如果没重启，手动 `Ctrl+C` 终止再 `streamlit run app/main.py`。
- **`ModuleNotFoundError`**：没激活 venv，或者装错环境。`which python` 看一下是不是 `.venv/bin/python`。
- **端口被占用**：`streamlit run app/main.py --server.port=8502`。

---

## 2. 用 Docker Compose 跑（最省事）

不写代码、只部署运行时，Docker Compose 是最干净的路径。

### 2.1 前置条件

- Docker Desktop（macOS / Windows）或 Docker Engine（Linux）
- `docker compose` v2（即 `docker compose`，不是老版 `docker-compose`）

### 2.2 可选：创建 `.env` 预置默认值

```bash
cp config/.env.example config/.env
# 编辑 config/.env，填入真实 Key
# docker-compose.yml 已经配好 env_file: ../config/.env，compose up 时自动读取
```

模板：

```env
# DeepSeek 页面默认值
DEEPSEEK_API_KEY=sk-xxx

# OpenAI Compatible 页面默认值
OPENAI_API_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-xxx
```

> 不配置 `.env` 也可以打开页面；运行查询时在页面里手动填 Key 即可。

### 2.3 启动 / 停止 / 看日志

```bash
# 启动（后台）
docker compose up -d

# 看日志
docker compose logs -f

# 停止
docker compose down

# 重建并启动（依赖或代码变更后）
docker compose up -d --build
```

启动后访问 `http://localhost:8501`。

---

## 3. 用 `scripts/build.sh` 打版本化镜像

`scripts/build.sh` 是项目自带的镜像构建脚本，会自动生成 OCI 元数据标签（version / git SHA / build date）并按 semver 打多个 tag。

### 3.1 前置条件

- Docker（已启动的 daemon）
- `scripts/build.sh` 需要从 git 仓库里跑（要读 `git rev-parse HEAD`），所以目录必须在 git 仓库内
- `--save` 需要 `docker buildx`

### 3.2 用法速查

```bash
./scripts/build.sh                       # 默认: autopm3:dev
./scripts/build.sh 1.0.0                 # autopm3:1.0.0 + 1.0 + 1 + latest + SHA
./scripts/build.sh v1.0.0                # 自动去掉前导 'v'
./scripts/build.sh 1.0.0 --no-latest     # 不打 :latest
./scripts/build.sh 1.0.0 --save          # 导出 linux/amd64 + linux/arm64 的 .tar
./scripts/build.sh 1.0.0 --save --platforms linux/amd64,linux/arm64
./scripts/build.sh 1.0.0 --push myuser   # 推到 Docker Hub 的 myuser/autopm3
./scripts/build.sh -h                    # 看帮助
```

### 3.3 生成的 tag 说明

对于 `1.2.3` 这种 semver 形如 `X.Y.Z` 的版本，会自动生成：

| Tag                          | 用途                              |
| ---------------------------- | --------------------------------- |
| `autopm3:1.2.3`              | 精确版本                          |
| `autopm3:1.2`                | minor 滚动                        |
| `autopm3:1`                  | major 滚动                        |
| `autopm3:latest`             | 最新的稳定版本（除非 `--no-latest`） |
| `autopm3:1.2.3-abc1234`      | 不可变 SHA tag（永远指向同一次构建） |

对于 `dev` 或非 semver 的 tag，只生成 `autopm3:dev` 和 `autopm3:dev-<SHA>`。

### 3.4 `--save` 模式：导出 tar

导出单平台或多平台的 `.tar` 文件，方便离线分发：

```bash
./scripts/build.sh 1.0.0 --save
# 生成：
#   autopm3-1.0.0-<sha>-linux-amd64.tar
#   autopm3-1.0.0-<sha>-linux-arm64.tar
```

> ⚠️ `--save` 和 `--push` 不能同时用（前者落盘 tar，后者推到 registry，行为互斥）。

### 3.5 `--push` 模式：推到 Docker Hub

需要先 `docker login`：

```bash
docker login
./scripts/build.sh 1.0.0 --push myuser
# 推送:
#   myuser/autopm3:1.0.0
#   myuser/autopm3:1.0.0-<sha>
#   myuser/autopm3:latest
```

### 3.6 验证镜像元数据

构建完会打印 OCI 标签，也可以手动查看：

```bash
docker inspect autopm3:1.0.0 --format '{{ index .Config.Labels "org.opencontainers.image.version" }}'
# 输出: 1.0.0
```

这些标签在 `Dockerfile` 里通过 `ARG VERSION / GIT_SHA / BUILD_DATE` 注入，并作为 `ENV` 暴露给运行中的应用。

---

## 4. 手动 `docker build` / `docker run`

如果不想用 `build.sh`，直接调 `docker build` 也可以（build context 是项目根，Dockerfile 在 `docker/`）：

```bash
# 从项目根运行（build context 是 .）
docker build -f docker/Dockerfile -t autopm3 .
docker run -p 8501:8501 --rm autopm3
```

带环境变量启动：

```bash
docker run -p 8501:8501 --rm \
  -e DEEPSEEK_API_KEY="sk-xxx" \
  -e OPENAI_API_URL="https://api.openai.com/v1" \
  -e OPENAI_MODEL="gpt-4o-mini" \
  -e OPENAI_API_KEY="sk-xxx" \
  autopm3
```

---

## 5. 配置项 & 优先级

应用读取配置的优先级（从高到低）：

1. **进程环境变量**（`os.environ`，来自 `docker compose` 的 `environment` / `docker run -e` / shell 导出）
2. **Streamlit `secrets.toml`**（`st.secrets`，仅本地 `streamlit run` 时生效）
3. **代码内置默认值**（比如 `OPENAI_API_URL` 默认 `https://api.openai.com/v1`）

| 环境变量                | secrets.toml key        | 用途                       |
| ----------------------- | ----------------------- | -------------------------- |
| `DEEPSEEK_API_KEY`      | `deepseek_api_key`      | `app/main.py` 页面 DeepSeek Key |
| `OPENAI_API_URL`        | `openai_api_url`        | OpenAI 兼容页面 base URL   |
| `OPENAI_MODEL`          | `openai_model`          | OpenAI 兼容页面模型名      |
| `OPENAI_API_KEY`        | `openai_api_key`        | OpenAI 兼容页面 Key        |

> **Docker 里为啥用 `.env` 而不是 `secrets.toml`？**
> Streamlit 的 `secrets.toml` 只有 `streamlit run` 启动的进程才会读，挂载进容器也不生效。容器里靠环境变量注入更靠谱。

---

## 排错速查

| 现象                                              | 大概率原因                                        | 解决                                                              |
| ------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------------- |
| `docker compose up` 报 `port is already allocated` | 8501 被占                                         | `lsof -ti:8501 \| xargs kill`；或改 `docker-compose.yml` 的端口映射 |
| 容器起得来但页面 502 / 一直转圈                   | Streamlit 还没就绪                                | 等 5–10 秒，Streamlit 启动较慢                                     |
| `streamlit run` 提示找不到模块                    | venv 没装好                                       | 确认 `which python` 指向 `.venv/bin/python`，重新 `pip install -r requirements.txt` |
| 改完代码页面没刷新                                | Streamlit 没在监听文件                            | 编辑器自动保存了吗？手动 `Ctrl+C` 再启动                           |
| `pip install lxml` 失败                           | 缺 C 编译器                                       | 见 [§1.2](#12-创建虚拟环境并安装依赖) 的编译工具说明              |
| Docker 构建卡在 pip 阶段                          | 网络问题拉不到包                                  | 重试，或在 `Dockerfile` 的 `pip install` 前加国内镜像              |
