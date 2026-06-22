# 后端测试数据库配置

> 每次运行后端测试前，请先阅读本文档。

## 1. 什么是 TEST_DATABASE_URL

`TEST_DATABASE_URL` 是后端 pytest 测试使用的 PostgreSQL 连接字符串。测试框架通过它连接到一个**独立的测试数据库**，避免写入或清空你的开发/生产数据库。

项目已在 `backend/tests/conftest.py` 中强制校验：
- 必须设置 `TEST_DATABASE_URL`
- 数据库名必须包含 `test`
- 未设置或连接非测试库时，pytest 会直接报错，不会 fallback

## 2. 本地数据库信息

- **用户名**：`postgres`（或你安装时设置的用户名）
- **密码**：使用你本机 PostgreSQL 的测试数据库密码（不要提交真实密码）
- **主机**：`localhost`
- **端口**：`5432`
- **测试库名**：`notero_test`

## 3. 创建测试数据库

在 psql 或任意 PostgreSQL 客户端中执行：

```sql
CREATE DATABASE notero_test;
```

如果数据库已存在，可跳过此步。

## 4. 设置环境变量

### Windows PowerShell

```powershell
$env:TEST_DATABASE_URL="postgresql://postgres:<password>@localhost:5432/notero_test"
```

### Windows CMD

```cmd
set TEST_DATABASE_URL=postgresql://postgres:<password>@localhost:5432/notero_test
```

### Git Bash / WSL / Linux / macOS

```bash
export TEST_DATABASE_URL="postgresql://postgres:<password>@localhost:5432/notero_test"
```

## 5. 运行后端测试

在设置好环境变量后，进入 `backend` 目录运行：

```bash
cd backend
pytest
```

或只运行某个测试文件：

```bash
pytest tests/test_auto_agents.py
```

## 6. 常见问题

### 提示 `TEST_DATABASE_URL is required`

说明环境变量没有设置成功。请检查当前终端是否执行了第 4 步的命令。

### 连接失败

1. 确认 PostgreSQL 服务已启动：
   ```bash
   pg_isready -h localhost -p 5432
   ```
2. 确认用户名、密码、端口正确。
3. 确认 `notero_test` 数据库已创建。

### 测试库数据需要清理

测试框架会在每次测试后回滚事务，一般不需要手动清理。如果测试库出现脏数据，可以重建：

```sql
DROP DATABASE notero_test;
CREATE DATABASE notero_test;
```
