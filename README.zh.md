# AutoPM3：基于 LLM 驱动的 PM3 证据提取，增强变异解读

[English](./README.md) | **简体中文**

[![License](https://img.shields.io/badge/license-MIT-blue)](https://opensource.org/license/mit/)
[![DOI](https://zenodo.org/badge/872230347.svg)](https://doi.org/10.5281/zenodo.15629003)


联系方式：Ruibang Luo、Shumin Li

邮箱：rbluo@cs.hku.hk、lishumin@connect.hku.hk


## 简介
我们提出 AutoPM3，一种利用开源大语言模型（LLM）从科学文献中自动提取 ACMG/AMP PM3 证据的方法。它结合了面向文本理解的优化版 RAG 系统和配备 Text2SQL 的 TableLLM 用于数据抽取。我们使用自建的 PM3-Bench（在 ClinGen 证据库基础上构建，包含 1,027 个变异-文献配对）评估了 AutoPM3；得益于四大关键模块，它在变异命中和反式变异识别上显著优于其他方法。此外，我们为 AutoPM3 封装了用户友好的界面以提高易用性。本研究为提升罕见病诊断流程提供了有力工具，能更高效地从科学文献中提取 PM3 相关证据。

AutoPM3 的算法与结果描述已发表在 [Bioinformatics](https://academic.oup.com/bioinformatics/article/41/7/btaf382/8178584)。

![](./docs/images/img1.png)
---

## 项目结构

> **说明**：本仓库根目录现在被拆成两个独立的子项目：`pm3_streamlit/`（Python / Streamlit，对应论文中的实现）和 `pm3_bun/`（Bun + Vue 同一产品的重写版，后端用 Fastify + Postgres）。**两者互不兼容**，按需选一个跑。根目录只保留共享资源（README、docs、benchmark 数据集、license）。

```
AutoPM3/
├── pm3_streamlit/             # Python / Streamlit 实现（论文对应版本）
│   ├── app/                   # Streamlit 多页面应用
│   ├── tests/                 # pytest 套件
│   ├── data/, config/         # 运行期数据 + 凭据模板
│   ├── docker/, scripts/      # Dockerfile、compose、版本化镜像构建脚本
│   ├── .streamlit/            # 真实 secrets.toml（已 gitignore）
│   ├── .dockerignore          # 必须位于 build context 根
│   ├── pyproject.toml, requirements.txt
│   ├── README.md              # 子项目入口——只关心 Python 版看这里
│   └── DEPLOY.md              # 完整的 Python 侧部署 + Docker + scripts/build.sh
│
├── pm3_bun/                   # Bun / Node 实现（Fastify 后端 + Vue/Vite 前端）
│   ├── server/                # Fastify + Postgres + MinIO + MinerU worker
│   ├── web/                   # Vue 3 + Vite + TypeScript 前端
│   ├── docker-compose.storage.yml  # Postgres(5433) + MinIO(9010) for the server
│   ├── package.json, package-lock.json
│   └── README.md              # 子项目入口——只关心 Bun 版看这里
│
├── benchmarks/                # PM3-Bench 评测数据集 + 使用说明（共享）
├── docs/                      # 内部文档（架构图、开发计划、会议纪要、图片）
├── README.md / README.zh.md
├── LICENSE / TODO.md / plan.md
└── .gitignore / .dockerignore / .claude/
```

**关键路径约定**（Python 侧完整列表见 [pm3_streamlit/DEPLOY.md](pm3_streamlit/DEPLOY.md)）：
- **Python / Streamlit**：所有命令都在 `pm3_streamlit/` 内执行（`cd pm3_streamlit` 后 `streamlit run app/main.py`）。
- **Bun / Node**：所有命令都在 `pm3_bun/` 内执行（`cd pm3_bun` 后 `npm install` + `npm run dev:server` / `npm run dev:web`）。
- Python 镜像的 Docker build context 是 **`pm3_streamlit/`**（因此 `.dockerignore` 也在那里）。

---

## 目录

- [项目结构](#项目结构)
- [最新更新](#最新更新)
- [在线 Demo](#在线-demo)
- [子项目](#子项目)
- [安装](#安装)
    - [依赖安装](#依赖安装)
    - [使用 Ollama 托管 LLM](#使用-ollama-托管-llm)
- [使用](#使用)
    - [快速开始](#快速开始)
    - [Python 脚本的高级用法](#python-脚本的高级用法)
- [PM3-Bench](#pm3-bench)
- [TODO](#todo)
---

## 最新更新
* v0.1（2024 年 10 月）：首次发布。
---
## 在线 Demo
* 在线体验：[AutoPM3-demo](https://www.bio8.cs.hku.hk/autopm3-demo/)。请注意，由于算力资源有限，建议本地部署 AutoPM3 以避免长时间排队。

## 子项目
* **Python / Streamlit** — 论文中对应的实现版本。详见 [pm3_streamlit/README.md](pm3_streamlit/README.md) 与 [pm3_streamlit/DEPLOY.md](pm3_streamlit/DEPLOY.md) — 本地运行、Docker、镜像构建都在这里。
* **Bun / Node** — 同一产品的 Fastify + Vue 重写版。详见 [pm3_bun/README.md](pm3_bun/README.md)。

本文档余下部分只介绍 **Python / Streamlit** 子项目（论文对应版本）。要看 Bun/Node 版请走上面的链接。

## 安装
> 下面所有命令都在 `pm3_streamlit/` 内执行。
### 依赖安装
```bash
cd pm3_streamlit
conda create -n AutoPM3 python=3.10
conda activate AutoPM3
pip3 install -r requirements.txt
```

### 使用 Ollama 托管 LLM
1. 下载 Ollama：[官方指南](https://github.com/ollama/ollama)
2. 修改 Ollama 模型目录：
```bash
# 请按需修改目标文件夹
mkdir ollama_models
export OLLAMA_MODELS=./ollama_models
```


```bash

ollama serve

```

3. 下载 sqlcoder-mistral-7B 模型和微调后的 Llama3：
```bash
cd $OLLAMA_MODELS
wget https://huggingface.co/MaziyarPanahi/sqlcoder-7b-Mistral-7B-Instruct-v0.2-slerp-GGUF/resolve/main/sqlcoder-7b-Mistral-7B-Instruct-v0.2-slerp.Q8_0.gguf?download=true
mv 'sqlcoder-7b-Mistral-7B-Instruct-v0.2-slerp.Q8_0.gguf?download=true' 'sqlcoder-7b-Mistral-7B-Instruct-v0.2-slerp.Q8_0.gguf'
echo "FROM ./sqlcoder-7b-Mistral-7B-Instruct-v0.2-slerp.Q8_0.gguf" >Modelfile1
ollama create sqlcoder-7b-Mistral-7B-Instruct-v0.2-slerp -f Modelfile1

wget http://bio8.cs.hku.hk/AutoPM3/llama3_loraFT-8b-f16.gguf
echo "FROM ./llama3_loraFT-8b-f16.gguf" >Modelfile2
ollama create llama3_loraFT-8b-f16 -f Modelfile2

```

5. 查看已创建的模型：

```bash

ollama list

```

6. （可选）下载其他模型作为 RAG 系统的后端：
```
# 例如下载 Llama3:70B
ollama pull llama3:70B

```

## 使用

### 快速开始

* 第 1 步：启动本地 Web 服务：
```bash
cd pm3_streamlit
streamlit run app/main.py
```
* 第 2 步：把 `http://localhost:8501` 复制到浏览器，开始使用。

### Python 脚本的高级用法

* 查看 `app.core.query` 的帮助：
```bash
cd pm3_streamlit
python -m app.core.query -h
```
* 运行 Python 脚本的示例：
```bash
cd pm3_streamlit
python -m app.core.query
--query_variant "NM_004004.5:c.516G>C" ## HVGS 格式的查询变异
--paper_path ./data/xml_papers/20201936.xml ## 文献路径
--model_name_text llama3_loraFT-8b-f16 ## 按需换成 llama3:70b 或其他 Ollama 托管模型作 RAG 后端，注意需要在 Ollama 中先 pull
```

## PM3-Bench
* 我们公开了研究中使用的 PM3-Bench，详见 [PM3-Bench 教程](benchmarks/README.md)。

## TODO
* 一键快速部署 AutoPM3。
