# docker/

Docker 构建和编排文件。

| 文件 | 用途 |
| ---- | ---- |
| `Dockerfile`        | 镜像构建：基于 `python:3.11-slim`，只 `COPY app/` 和 `data/protein.txt` |
| `docker-compose.yml`| 一键启动；`env_file: ../config/.env` 自动读取凭据 |

## 关键约定

**build context 是项目根**（`docker-compose.yml` 里 `context: ..`），不是 `docker/`。
所以 `.dockerignore` 必须在项目根，不能挪到 `docker/`。

最常见用法：

```bash
# 1. 准备凭据
cp config/.env.example config/.env
# 编辑 config/.env，填入 API Key

# 2. 一键起
cd docker
docker compose up -d
docker compose logs -f

# 3. 停
docker compose down
```

不用 compose、直接 build 也可以：

```bash
# 在项目根运行
docker build -f docker/Dockerfile -t autopm3 .
docker run -p 8501:8501 --rm autopm3
```

打 tag 用 `scripts/build.sh`（推荐，能自动生成 OCI 元数据标签）：

```bash
./scripts/build.sh 1.0.0
```
