# Docker 部署

## 快速启动

```bash
# 1. 复制并编辑 secrets
cp .streamlit/secrets.toml.example .streamlit/secrets.toml

# 2. 一键启动
docker compose up -d
```

访问 `http://localhost:8501`

## 使用 .env 文件预置默认值

创建 `.env` 文件：

```env
# DeepSeek API
DEEPSEEK_API_KEY=sk-xxx

# OpenAI Compatible 默认值
OPENAI_API_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-xxx
```

Docker Compose 会自动读取 `.env` 并注入到环境变量中。

## 手动 Docker 构建

```bash
docker build -t autopm3 .
docker run -p 8501:8501 autopm3
```
