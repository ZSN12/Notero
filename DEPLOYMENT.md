# Notero 部署指南

本文档涵盖生产环境部署所需的数据库、缓存、消息队列和向量搜索组件。

---

## 1. 环境变量

复制 `.env.example` 为 `.env` 并填写以下关键变量：

```bash
# Database
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<strong_password>
POSTGRES_DB=notero
DATABASE_URL=postgresql://postgres:<strong_password>@localhost:5432/notero

# Redis (Celery broker / backend)
REDIS_URL=redis://localhost:6379/0

# JWT
SECRET_KEY=<random_32_bytes_hex>

# LLM APIs
DEEPSEEK_API_KEY=sk-...
DASHSCOPE_API_KEY=sk-...
OPENAI_API_KEY=sk-...

# Admin (首次启动自动创建)
ADMIN_DEFAULT_EMAIL=admin@example.com
ADMIN_DEFAULT_PASSWORD=<change_me>

# Optional
LOG_LEVEL=INFO           # DEBUG | INFO | WARNING | ERROR
LOG_FORMAT=text          # text | json
SKIP_ASR_PRELOAD=0       # 1 = 禁止启动时预加载 FunASR 模型
```

---

## 2. PostgreSQL + pgvector

### 2.1 安装 PostgreSQL 16+

**Docker（推荐）**
```bash
docker run -d \
  --name notero-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=<strong_password> \
  -e POSTGRES_DB=notero \
  -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data \
  ankane/pgvector:latest
```

**本地安装（Ubuntu/Debian）**
```bash
# 安装 PostgreSQL
sudo apt install postgresql-16 postgresql-contrib

# 安装 pgvector 扩展
sudo apt install postgresql-16-pgvector
# 或编译安装：
# git clone --branch v0.7.0 https://github.com/pgvector/pgvector.git
# cd pgvector && make && sudo make install
```

### 2.2 创建数据库与扩展

```bash
psql -U postgres -c "CREATE DATABASE notero;"
psql -U postgres -d notero -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 2.3 运行迁移

```bash
cd backend
alembic upgrade head
```

> **注意**：迁移会自动创建 `vector(1536)` 列和 HNSW 索引。如果之前手动运行过旧版迁移导致列类型为 `TEXT`，请执行：
> ```sql
> ALTER TABLE vector_chunks ALTER COLUMN embedding_vector TYPE vector(1536) USING embedding_vector::vector(1536);
> ```

---

## 3. Redis

**Docker**
```bash
docker run -d --name notero-redis -p 6379:6379 redis:7-alpine
```

**本地安装**
```bash
sudo apt install redis-server
sudo systemctl enable redis
sudo systemctl start redis
```

验证连接：
```bash
redis-cli ping  # 应返回 PONG
```

---

## 4. 启动服务

### 4.1 开发模式（单进程）

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload --reload-dir app --reload-exclude tests
```

### 4.2 生产模式（多 worker）

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8003 --workers 4
```

### 4.3 启动 Celery Worker（必须）

Agent 任务（AI 整理、知识导图、测验生成）**依赖 Celery Worker** 执行。不启动 Worker 会导致任务永远处于 `pending` 状态。

```bash
cd backend
celery -A app.core.celery_app worker --loglevel=info --concurrency=2
```

> `--concurrency=2` 表示同时运行 2 个 Agent 任务。根据 GPU/CPU 资源调整。

### 4.4 Docker Compose（一键启动）

```bash
docker-compose up -d
```

这会启动：
- `postgres` (含 pgvector)
- `redis`
- `notero` (FastAPI)
- `celery-worker`

---

## 5. 健康检查

```bash
curl http://localhost:8003/api/health
```

期望响应：
```json
{
  "status": "ok",
  "database": "connected",
  "redis": "connected",
  "celery": {
    "broker": "connected",
    "workers_online": 1
  }
}
```

---

## 6. 日志与监控

### 6.1 请求链路追踪

每个 HTTP 响应头都包含 `X-Request-ID`：
```bash
curl -I http://localhost:8003/api/health
# X-Request-ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

前端可在请求时传入自定义 `X-Request-ID` 以实现端到端追踪。

### 6.2 结构化日志

设置 `LOG_FORMAT=json` 可输出 JSON 格式日志，便于接入 ELK / Loki：
```bash
LOG_FORMAT=json uvicorn app.main:app --host 0.0.0.0 --port 8003
```

输出示例：
```json
{"asctime": "14:32:01", "levelname": "INFO", "name": "notero.access", "message": "request", "request_id": "abc-123", "method": "GET", "path": "/api/health", "status_code": 200, "latency_ms": 12.34}
```

### 6.3 降低噪音

SQLAlchemy 引擎日志和 urllib3 日志默认设为 `WARNING`，如需调试数据库查询：
```bash
LOG_LEVEL=DEBUG python -m app.main
```

---

## 7. 故障排查

| 现象 | 排查步骤 |
|---|---|
| Agent 任务一直处于 `pending` | 检查 Celery Worker 是否启动：`celery -A app.core.celery_app status` |
| 向量搜索极慢 | 确认 HNSW 索引已创建：`\di idx_vector_chunks_embedding_hnsw` |
| pgvector 迁移失败 | 确认 PostgreSQL 已安装 pgvector 扩展，且版本 >= 0.5.0 |
| Redis 连接失败 | 检查 `REDIS_URL` 环境变量和防火墙规则 |
| 应用启动时白屏 | 检查浏览器控制台错误；后端已添加 React Error Boundary |

---

## 8. 前端构建

```bash
npm install
npm run build
```

静态文件输出到 `dist/`，可由 FastAPI 直接托管或部署到 CDN。
