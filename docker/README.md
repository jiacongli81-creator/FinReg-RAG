# Docker 部署

`compose.yaml` 启动 FastAPI、MySQL、Ollama 和 Milvus Standalone。Milvus 使用官方嵌入式 etcd 与本地存储模式，端口 `19530` 仅绑定本机。智能档仍使用现有交叉编码器和配置的回答模型。

## D 盘存储

项目放在 D 盘。`docker-data/` 保存 MySQL、Milvus、Ollama、MinerU 与重排模型的数据。Docker Desktop 的 **Disk image location** 也必须设在 D 盘，否则镜像层仍可能下载到 C 盘。本机目前将 Docker 的 `wsl/disk` 目录链接到 `D:\信雅达rag\docker-data\docker-desktop\disk`；换机器部署时需重新设置其磁盘位置。

首次部署先将 `docker/api.env.example`、`docker/mysql.env.example` 分别复制为 `docker/api.env`、`docker/mysql.env`，为两处 `MYSQL_PASSWORD` 设置同一个强密码，再设置独立的 `MYSQL_ROOT_PASSWORD`。这两个实际配置文件受 `.gitignore` 和 `.dockerignore` 排除。智能档如需调用外部模型，在 `api.env` 中设置 `LLM_PROVIDER=openai_compatible` 及 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`；否则保持 `LLM_PROVIDER=mock` 使用摘录式回答。

## 启动

在项目根目录运行：

```powershell
docker compose config --quiet
docker compose pull milvus mysql ollama
docker compose up -d --build
docker compose ps
```

首次构建会安装 MinerU，首次启动会下载其 basic ONNX 模型及 Ollama 嵌入模型，均持久化在 D 盘。页面为 `http://127.0.0.1:8000/test`；健康检查为 `http://127.0.0.1:8000/health`。

新建的 MySQL 是空库。如需将本项目的 SQLite 数据导入，仅在 **MySQL 目标库为空** 时执行：

```powershell
docker compose stop api
docker compose run --rm --no-deps api python scripts/migrate_sqlite_to_mysql.py --snapshot data/backups/sqlite-before-docker.db
docker compose up -d --no-deps api
```

如果 MySQL 已有数据，不执行迁移脚本。`api` 每次启动时只把 MySQL 中缺失的片段向量同步至 Milvus。新增文档导入时会同步写入 Milvus；MySQL 仍保留向量副本供原评测脚本与恢复使用。更换 embedding 模型并重建 MySQL 向量后，运行 `docker compose exec api python scripts/sync_milvus.py --force` 覆盖 Milvus 向量。已有 MySQL 实例的数据需要先备份并导入此容器，不能通过空库迁移脚本覆盖。

停止服务使用 `docker compose down`。此命令不删除 D 盘的持久化数据。
