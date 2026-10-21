# 金融制度 RAG 后端

## 启动

在 Windows PowerShell 中进入项目根目录。先准备可用的 Python 3.12，再在 D 盘克隆本仓库。首次安装运行：

```powershell
cd D:\信雅达rag
powershell -ExecutionPolicy Bypass -File .\scripts\setup_mineru.ps1
```

如果 `python` 命令指向 Windows 应用商店占位程序，使用 `-Python 'D:\路径\到\python.exe'` 指定 Python 3.12。克隆到其他 D 盘目录时，将上面的 `cd` 改为实际路径。

脚本会建立项目 Python 环境、安装本仓库中的 MinerU 源码，并下载 basic ONNX 模型。之后启动服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

中文测试页：`http://127.0.0.1:8000/test`；接口文档：`http://127.0.0.1:8000/docs`。如需配置外部 LLM，先复制 `.env.example` 为 `.env`。

## 当前接口

- `GET /health`：健康检查
- `GET /documents`：查看已导入文档
- `POST /documents/upload`：上传并解析受支持文档与图片
- `POST /documents/ingest-directory`：递归导入 `data/raw` 和 `data/converted`
- `POST /query`：检索并生成答案

PDF、扫描 PDF 和图片由本仓库 `vendor/MinerU` 的 basic 模型识别。Office、RTF、OpenDocument、EPUB、OFD 和网页文件由 MinerU flash 解析；TXT、Markdown、CSV、TSV 和 DOCX 使用项目内置解析器。文字、标题和表格会进入知识库，base64 图片不会写入数据库。MinerU 的原始许可文件保留在 `vendor/MinerU/LICENSE.md`。

仓库提交 MinerU 源码；`mineru_runtime` 保存模型、环境和缓存，由 `.gitignore` 排除。GitHub 克隆后执行上述脚本即可重新构建本地 OCR 能力；GitHub 上的源码本身不包含模型文件。

注意：本项目的 `data/raw` 中已有文件受 Git 跟踪。发布仓库前请确认这些文档允许公开；`.env`、数据库、模型和虚拟环境均不会随正常的 Git 提交上传。

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

## 旧版 Word 和 WPS 转换

Windows 上如果已安装 Microsoft Word，可将旧版 `.doc`/`.wps` 转成 `.docx`。原文件不会修改，输出会保存在 `data/converted`，并保留原目录结构。推荐使用 PowerShell 脚本，不需要额外安装 Python 包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\convert_legacy_office.ps1
```

转换报告位于 `data/conversion_report.csv`，转换后的文件位于 `data/converted`。然后在中文测试页点击“批量导入”对应的接口，或在 `/docs` 中执行 `POST /documents/ingest-directory`，系统会递归读取 `data/raw` 和 `data/converted`。`.wps` 是否能转换取决于本机 Word 对该文件的兼容性；失败文件会记录在报告中。
