# 金融制度 RAG 后端

## 启动

使用工作区 Python 安装依赖：

```powershell
python -m pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，然后启动服务：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

接口文档：`http://127.0.0.1:8000/docs`

## 当前接口

- `GET /health`：健康检查
- `GET /documents`：查看已导入文档
- `POST /documents/upload`：上传并解析 PDF/TXT
- `POST /documents/ingest-directory`：导入 `data/raw` 中的文件
- `POST /query`：检索并生成答案

示例请求：

```json
{
  "question": "证券交易规则主要规范什么内容？",
  "top_k": 5,
  "only_valid": true
}
```

## 当前运行模式

默认使用 SQLite 和本地哈希向量检索，LLM 使用可运行的摘录式兜底回答。这样可以在没有外部模型和数据库服务的情况下验证完整后端链路。

正式接入模型时，在 `.env` 中设置：

```text
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=模型服务地址
LLM_API_KEY=模型密钥
LLM_MODEL=模型名称
```

后续可以将存储层替换为 MySQL 和 Milvus，而不改变前端调用的 API。
