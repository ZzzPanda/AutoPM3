# pm3_streamlit — Python / Streamlit 子项目

这是仓库里的 **Python / Streamlit** 实现,对应 AutoPM3 论文([Bioinformatics 2025](https://academic.oup.com/bioinformatics/article/41/7/btaf382/8178584))中发布的版本。同一产品还有 [Bun + Vue](../pm3_bun/README.md) 的并行重写,两份代码互不兼容,按需选一个。

## 目录速览

```
pm3_streamlit/
├── app/                       # 全部 Python 源码(Streamlit 包)
│   ├── main.py                # Streamlit 入口(DeepSeek 页面)
│   ├── pages/                 # 其它 Streamlit 页面
│   ├── core/                  # 核心逻辑:query、table_functions、streamlit_helpers
│   ├── data_io/               # 离线脚本(download_papers 等)
│   └── mineru/                # MinerU API 客户端
├── tests/                     # pytest
├── data/                      # protein.txt、pdf_convert/ 示例
├── config/                    # 凭据模板
├── docker/                    # Dockerfile + docker-compose.yml
├── scripts/build.sh           # 版本化 Docker 镜像构建
├── .streamlit/secrets.toml    # 真实凭据(gitignored)
├── .dockerignore              # 必须在 build context 根
├── pyproject.toml             # pytest 配置:pythonpath = ["."], testpaths = ["tests"]
├── requirements.txt
├── README.md                  # 本文件
└── DEPLOY.md                  # 完整部署 + Docker + scripts/build.sh 指南
```

## 快速开始(本地 Python)

```bash
cd pm3_streamlit

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 配凭据(可选;不配也能在页面里手动填)
cp config/.env.example config/.env             # 给 Docker 用
cp config/.streamlit/secrets.toml.example .streamlit/secrets.toml   # 给 streamlit run 用

streamlit run app/main.py                      # 浏览器访问 http://localhost:8501
```

## 运行测试

```bash
cd pm3_streamlit
pytest -q
```

`pyproject.toml` 里 `pythonpath = ["."]` 让你从 `pm3_streamlit/` 目录跑 `pytest` 时,`from app.core...` 这类顶层包导入能解析。

## Docker / 部署

详细文档见 [DEPLOY.md](DEPLOY.md)。要点:

```bash
cd pm3_streamlit

# 方式 1: Docker Compose
docker compose -f docker/docker-compose.yml up -d --build

# 方式 2: 用 scripts/build.sh 打版本化镜像
./scripts/build.sh 1.0.0            # autopm3:1.0.0 + 1.0 + 1 + latest + SHA tag
./scripts/build.sh 1.0.0 --push myuser

# 方式 3: 直接 docker build
docker build -f docker/Dockerfile -t autopm3 .
```

Docker build context 是 `pm3_streamlit/`(不是 `docker/`、不是仓库根)。`.dockerignore` 必须留在 `pm3_streamlit/` 下面。

## 路径解析说明

`app/core/query.py:106` 用 `Path(__file__).resolve().parents[2]` 反推项目根,以便加载 `data/protein.txt`。这意味着:

- CWD 不重要——只要 `app/` 在 `pm3_streamlit/app/` 下面,`protein.txt` 路径就能解析对。
- 镜像构建和本地 `streamlit run` 都用这个机制,所以行为一致。
- 不要把 `app/` 单独移走(会破坏路径解析)。

## 关键文档

- [DEPLOY.md](DEPLOY.md) — 完整部署指南(venv / Docker / scripts/build.sh / 配置优先级)
- [docker/README.md](docker/README.md) — Docker 镜像细节
- [config/.streamlit/secrets.toml.example](config/.streamlit/secrets.toml.example) — 凭据模板
- [app/mineru/README.md](app/mineru/README.md) — MinerU 客户端子模块
- 仓库根的 [docs/](../docs/) — 架构图、会议纪要、开发计划(项目级共享)
- 仓库根的 [benchmarks/](../benchmarks/) — PM3-Bench 评测数据集(项目级共享)
