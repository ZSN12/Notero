# Contributing to Notero

感谢你对 Notero 的兴趣！以下是参与项目的指南。

## 开发环境

- **Node.js** 20+
- **Python** 3.10+ 或 3.11+
- **PostgreSQL** 15+
- **FFmpeg**

### 快速启动

```bash
# 1. 前端依赖
npm install

# 2. 后端依赖
cd backend && pip install -r requirements.txt

# 3. 环境变量
cp .env.example .env
# 编辑 .env，填入 DATABASE_URL 和 AI API Keys

# 4. 启动数据库（Docker）
docker run -d --name notero-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 postgres:16-alpine

# 5. 启动后端
cd backend
uvicorn app.main:app --reload --reload-dir app --reload-exclude tests --port 8000

# 6. 启动前端
npm run dev
```

## 提交规范

我们使用常规的 Commit Message 格式：

```
<type>(<scope>): <subject>

<body>
```

类型：
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `style`: 代码格式（不影响功能）
- `refactor`: 重构
- `test`: 测试相关
- `chore`: 构建/工具链

## 测试

### 后端测试

需要 PostgreSQL 测试数据库（名称必须包含 `test`）：

```bash
# Windows
set TEST_DATABASE_URL=postgresql://postgres:<password>@localhost:5432/notero_test
python -m pytest backend/tests/ -v

# macOS/Linux
export TEST_DATABASE_URL=postgresql://postgres:<password>@localhost:5432/notero_test
python -m pytest backend/tests/ -v
```

### 前端测试

```bash
npm run test
```

## 代码规范

- **Python**: 使用项目现有的代码风格，保持类型注解
- **TypeScript**: 启用 strict 模式，避免 `any`
- **数据库**: 所有 schema 变更必须通过 Alembic 迁移，禁止直接修改 `Base.metadata`

## 架构原则

- **三层转写兜底**: 任何修改转写流程的 PR 必须保证 `raw_text → local_clean → ai_corrected` 的降级路径可用
- **状态机**: 长任务状态必须落库，支持刷新后恢复
- **权限**: 所有数据访问必须校验 `Notebook.user_id`，不存在"公共数据"

## 提交 PR

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feat/my-feature`)
3. 确保测试通过
4. 提交 PR 并描述改动动机和影响范围

## 问题反馈

发现 Bug 或需要新功能？请开 Issue 并包含：
- 复现步骤
- 期望行为 vs 实际行为
- 环境信息（OS、Python/Node 版本、数据库版本）

## 行为准则

- 保持尊重和建设性
- 接受不同观点和经验水平
- 关注对社区最有利的事情
