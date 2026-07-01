# pm3_bun — Bun / Node 子项目

这是仓库里的 **Bun / Node** 重写版:Vue 3 + Vite 前端,Fastify + Postgres 后端,Postgres 用 MinIO 做对象存储。同一产品还有 [Python / Streamlit](../pm3_streamlit/README.md) 的实现(论文对应版本),两份代码互不兼容,按需选一个。

## 目录速览

```
pm3_bun/
├── server/                    # Fastify 后端
│   ├── main.js                #   - 路由 + DB schema 初始化
│   ├── pm3-worker.js          #   - PM3 文档处理 worker
│   └── .env.example           #   - 环境变量模板
├── web/                       # Vue 3 + Vite + TypeScript 前端
│   ├── src/
│   │   ├── App.vue
│   │   ├── api.ts             # 后端 API 客户端
│   │   └── views/             # 页面组件
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts         # 默认代理 /api → http://localhost:3017
├── docker-compose.storage.yml # Postgres(5433) + MinIO(9010) for the server
├── package.json               # 根 package.json,scripts 用相对路径调 web/ 和 server/
├── package-lock.json
└── README.md                  # 本文件
```

## 快速开始

### 1. 起 Postgres + MinIO

```bash
cd pm3_bun
docker compose -f docker-compose.storage.yml up -d
```

这会启动两个本地容器:
- **Postgres** 监听 `localhost:5433`,数据库 `autopm3`、用户/密码 `postgres / postgres`
- **MinIO** 监听 `localhost:9010`(API)和 `localhost:9011`(Console),`minioadmin / minioadmin`

### 2. 配置后端环境变量

```bash
cd pm3_bun
cp server/.env.example server/.env
# 按需修改 PORT / DATABASE_URL / S3_* / MINERU_*
```

### 3. 装依赖

```bash
cd pm3_bun
npm install
```

`npm install` 会在 `pm3_bun/node_modules/` 装后端依赖,在 `pm3_bun/web/node_modules/` 装前端依赖(`web/package.json` 由 `postinstall` 或 `npm install --workspaces` 触发;当前根 `package.json` 用 `cd web && npm install` 工作流)。

### 4. 跑起来

```bash
# 一个终端:后端
npm run dev:server          # 默认 :3017

# 另一个终端:前端
npm run dev:web             # 默认 :5177,自动代理 /api → :3017
```

打开 `http://localhost:5177/` 即可使用。

## 端口约定

| 服务        | 端口  | 说明                                      |
| ----------- | ----- | ----------------------------------------- |
| Fastify 后端 | 3017  | API + 上传 / 列表 / 下载 PM3 文档         |
| Vite 前端    | 5177  | dev server,proxy `/api` → `:3017`         |
| Postgres    | 5433  | `localhost:5433` (避开本机 5432)          |
| MinIO API   | 9010  | S3 兼容对象存储                           |
| MinIO Console| 9011 | Web UI                                    |

## API 路由(由 `server/main.js` 定义)

`server/main.js` 启动时自动跑 schema 迁移(`CREATE TABLE IF NOT EXISTS autopm3_documents ...`),并把 `pm3-worker.js` 用 `new Worker()` 拉起来做后台 PM3 处理。完整路由列表直接看 [server/main.js](server/main.js)。

## 与 Python 套的关系

- **数据流独立**:Python 套用 `data/xml_papers/` + `data/protein.txt` 跑 PM3 推理,结果存内存或流式返回;Bun 套把每篇文档存进 Postgres + MinIO,走异步 worker。
- **共享资产**:仓库根的 `benchmarks/PM3_Bench_data.json`、`docs/` 是两边都可能参考的项目级资源,不属于任一套。
- **互不依赖**:可以单独 `rm -rf` 其中一套,不影响另一套。

## 关键脚本

`package.json` 里定义:

```jsonc
{
  "scripts": {
    "dev:server": "node server/main.js",
    "dev:web":    "cd web && npm run dev",
    "build:web":  "cd web && npm run build"
  }
}
```

所有相对路径都假设你在 `pm3_bun/` 目录里。
