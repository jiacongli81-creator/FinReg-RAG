# 金融制度 RAG 后端

Docker + Milvus Standalone 部署见 [docker/README.md](docker/README.md)。容器中 MySQL 保存文档与历史，Milvus 执行向量检索；本机原有运行方式仍可使用 `VECTOR_BACKEND=local`。

## 工作台功能

打开 `http://127.0.0.1:8000/test`：

- **问答历史**：每次成功问答会保存问题、回答和当时的引用来源；可搜索、回看和删除。接口为 `GET /history`、`GET /history/{id}`、`DELETE /history/{id}`，`POST /query` 返回 `history_id`。
- **我的收藏**：在回答或历史记录上点击收藏，保存独立副本；删除历史后收藏仍可查看。接口为 `GET /favorites`、`POST /favorites`（请求体 `{"history_id": 1}`）、`DELETE /favorites/{id}`。
- **标签管理**：创建、重命名、删除标签；在知识库文档列表为文档分配标签。接口为 `GET/POST /tags`、`PUT/DELETE /tags/{id}`、`GET/PUT /documents/{id}/tags`。
- **更新管理**：点击“扫描资料目录”检查 `data/raw` 和 `data/converted` 中支持的文件类型。相同内容跳过；内容变化时导入新文档、转移标签并把旧版本标为失效；失败文件会出现在扫描记录中，下一次可重试。接口为 `GET /updates`、`POST /updates/scan`。首次扫描会按唯一文件名为已导入资料建立基线；如果两个目录存在同名的已导入文件，会提示先重命名区分，避免误认来源。旧数据库没有保存原始文件哈希，因此首次基线是按文件名推断的，请先核对目录中已导入文件的名称。

## 启动

### 数据库存储

默认继续使用本地 SQLite 数据库 `data/app.db`。如需切换到 MySQL，先在 `.env` 中设置 `DATABASE_BACKEND=mysql`、`MYSQL_HOST`、`MYSQL_PORT` 和 `MYSQL_DATABASE`。数据库账号从 `MYSQL_CREDENTIALS` 指定的 JSON 文件读取，默认位置为 `mineru_runtime/mysql/credentials.json`；格式为 `{"app_user":"账号","app_password":"密码"}`。该目录不受 Git 跟踪。账号需具有目标库建表和读写权限，MySQL 服务需先启动。本机 MySQL 8.0.44 使用 3306 端口。

从现有 SQLite 数据迁移到**空的** MySQL 数据库前，先停止项目写入，再执行：

```powershell
.\.venv\Scripts\python.exe scripts\migrate_sqlite_to_mysql.py --snapshot data\backups\sqlite-before-mysql.db
```

脚本先生成 SQLite 快照，再逐表复制并校验；目标表非空时拒绝覆盖。迁移完成后，将 `DATABASE_BACKEND=mysql` 写入 `.env` 并重启服务。向量保存在 MySQL 文本字段中，检索仍在 Python 中计算。原测试页保留在 `/legacy-test`，新知识工作台位于 `/test`。

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
- `GET /search?query=关键词&limit=20&only_valid=true`：独立关键词检索，返回排序后的文档片段，不调用语义向量或回答模型
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
  "mode": "fast",
  "top_k": 4,
  "only_valid": true
}
```

## 当前运行模式

“制度检索”页面现使用独立 `GET /search` 接口。输入关键词后，系统用 jieba 分词和现有关键词相关度算法排序，返回最多 20 个知识库片段及文档标题、页码、章节和匹配分；默认只检索有效或效力未知的文档。它不生成回答，也不访问 Ollama、reranker 或外部 LLM。此接口检索原知识库的 `documents`、`chunks`，独立法规条文库仍在 `/laws-ui` 查询。

普通问答由 LangChain LCEL 串联候选召回、排序、回答生成和历史记录保存。`POST /query` 的 `mode` 分为两档：`fast`（默认）从语义与关键词检索各取前 5 个候选做 RRF 融合，返回前 5 个来源，跳过交叉编码器，再调用配置的回答模型；`smart` 从两路各取前 20 个候选融合后运行 BGE 交叉编码器重排，返回前 4 个来源，再调用同一回答模型。测试页可直接切换档次；响应包含实际使用的 `mode`、`llm_provider` 和 `elapsed_ms`。智能档需要 `RERANK_ENABLED=true`，否则接口会明确报错。

语义检索由本机 Ollama 的 `shaw/dmeta-embedding-zh:latest` 生成向量，关键词检索使用 jieba，二者通过倒数排名融合（RRF）合并候选片段。智能档的 BGE 交叉编码器对“问题＋候选片段原文”重新打分；首次使用会下载模型到 `mineru_runtime/reranker`。重排推理批次默认是 16，可用 `RERANK_BATCH_SIZE` 调整，以减少本机内存占用。若未配置外部 LLM，两档会使用摘录式兜底回答。问答来源中的 `score` 是当前排序模型的分数，不是答案准确率。多步骤查询尚未接入；条文关联查询使用下述独立页面。

服务启动时会预热关键词索引和已启动的 Ollama 嵌入模型；`EMBEDDING_KEEP_ALIVE` 默认保持模型加载 1 小时。此前快速档不调用回答模型时的耗时记录已不适用于当前实现；重新计时需同时计入回答模型的耗时。

对同一套 100 道证据题，扫描快速档每路候选 N=1–50、返回 K=1–10 后，选择 N=5、K=5：离线和实际 `/query` 都命中 89/100。旧设置 N=20、K=4 的快速档命中 78/100；智能档 N=20、K=4 的历史实测为 99/100。评测检查的是返回来源片段包含标注证据，**不衡量生成回答的正确率**。这 100 题也用于选参，需要另用未参与选参的新题验证泛化。扫描结果见 `data/test/fast_topn_k_sweep_20261102.json`；实际接口计时及逐题命中见 `data/test/fast_n5_k5_api_20261102.json`，其中的快速档回答与耗时使用旧实现。

快速档的默认 N=5、K=5，使用 `RETRIEVAL_FAST_CANDIDATE_N` 和 `RETRIEVAL_FAST_TOP_K` 调整；智能档维持 N=20、K=4，使用 `RETRIEVAL_CANDIDATE_N` 和 `RETRIEVAL_TOP_K` 调整。两档仍需扫描当前语料做向量与关键词检索。`/query` 请求若显式传入 `top_k`，会覆盖所选档次的默认 K。前端测试页使用后端默认值。

首次切换嵌入模型或已有片段仍使用旧向量时，先启动 Ollama 并确认 `ollama list` 中有该模型，再运行：

```powershell
ollama serve
```

在另一个 PowerShell 窗口运行向量重建。脚本会先生成并校验全部片段向量，再备份 `data/app.db` 到 `data/backups`，最后一次性更新向量；失败时不会改写数据库。文档文本和 OCR 结果不会重新处理。

```powershell
cd D:\信雅达rag
.\.venv\Scripts\python.exe .\scripts\rebuild_embeddings.py
```

此后新增文档会在导入时自动生成 Ollama 向量；运行服务和导入文档前需确保 Ollama 已启动。

在 `.env` 中配置 Qwen API：

```text
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=模型服务地址
LLM_API_KEY=模型密钥
LLM_MODEL=模型名称
```

当前支持 SQLite 和 MySQL 存储；向量仍由 Python 在检索时计算。

## 独立条文库与关联查询

条文库使用同一个 MySQL 数据库中的独立 `law_documents`、`law_articles`、`law_references` 表；它不会改动原来的 `documents`、`chunks` 或问答评测数据。`law_documents` 保存官方网页原文、网址、抓取时间、内容哈希与版本说明；`law_articles` 保存完整条文；`law_references` 保存同一法规内明确出现的条号引用。页面另用文本相似度推荐相近条文，并明确标注其并非法定引用关系。

已收录八部有可追溯官方来源的法规全文，共 740 条：

| 法规 | 本库版本 | 条数 | 官方来源 |
| --- | --- | ---: | --- |
| 中华人民共和国人民币管理条例 | 2018 年修订 | 47 | [国务院公报](https://www.gov.cn/gongbao/content/2019/content_5468922.htm) |
| 中华人民共和国银行业监督管理法 | 2006 年修正 | 52 | [中国人民银行](https://www.pbc.gov.cn/tiaofasi/144941/144951/3808036/index.html) |
| 中华人民共和国证券法 | 2019 年修订 | 226 | [全国人大](http://www.npc.gov.cn/npc/c2/c30834/201912/t20191231_304436.html) |
| 中华人民共和国反洗钱法 | 2024 年修订 | 65 | [中国政府网](https://www.gov.cn/yaowen/liebiao/202411/content_6985765.htm) |
| 中华人民共和国保险法 | 2015 年修正 | 185 | [国家金融监督管理总局](https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId=879931&itemId=4248&generaltype=0) |
| 中华人民共和国商业银行法 | 2015 年修正 | 95 | [国家金融监督管理总局](https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId=879929&itemId=927&generaltype=0) |
| 存款保险条例 | 2015 年施行 | 23 | [中国政府网](https://www.gov.cn/zhengce/content/2015-03/31/content_9562.htm) |
| 征信业管理条例 | 2013 年施行 | 47 | [中国政府网](https://www.gov.cn/zwgk/2013-01/29/content_2322231.htm) |

项目旧资料可能采用不同修订版本；查询时以结果展示的版本与官方网址为准。导入脚本会校验标题和连续条号。若官方网页内容变化，脚本会停止更新，要求先核对版本。金融监管总局页面通过其公开 JSON 接口提供正文，导入程序保存该页面正文与可打开的官方页面网址。

MySQL 启动后，可运行以下命令验证官方网页并导入；重复运行相同内容不会重复建条文：

```powershell
.\.venv\Scripts\python.exe .\scripts\import_official_laws.py --validate-only
.\.venv\Scripts\python.exe .\scripts\import_official_laws.py
```

启动后在 [条文查询页](http://127.0.0.1:8000/laws-ui) 选择法规，输入“第四十四条”或条文关键词，也可留空分页浏览全部条文。查询结果展示完整条文、它引用的条文、引用它的条文、文本相近推荐以及官方原文链接。接口为 `GET /laws`、`GET /laws/articles?law_id=...&query=...&limit=30&offset=0`、`GET /laws/articles/{article_id}`。当前明确引用仅解析同一版本法规内的条号；跨法规引用需要先收录目标法规并人工核对名称、版本后才能建立可靠关联。

## 检索评测

运行当前 40 道带标准答案、原文证据和来源标注的问答评测集：

```powershell
.\.venv\Scripts\python.exe .\scripts\evaluate_retrieval.py --input .\data\test\finance_qa_40.json --output-dir .\data\test --cases-output .\data\test\finance_qa_40_cases_parsed.json --top-k 5
```

脚本会比较语义检索、关键词检索和混合检索，并输出答案关键词覆盖率及目标来源命中率。报告保存在 `data/test/retrieval_evaluation_<时间>.json`。这些指标用于检查检索证据覆盖，不等同于模型生成答案的正确率。

启动 API 后，还可以将同一批 40 题逐题发送到 `/query`，检查实际回答、接口成功数及返回来源：

```powershell
.\.venv\Scripts\python.exe .\scripts\evaluate_api.py --input .\data\test\finance_qa_40.json --base-url http://127.0.0.1:8000 --top-k 5
```

报告保存在 `data/test/api_evaluation_<时间>.json`。核心指标 `evidence_hit_at_k` 检查每题标注的证据文字是否出现在同一个返回片段的 `content` 中；遇到 `……` 时要求省略号前后的原文依次匹配。来源文件名命中率与证据片段命中率分开报告。答案词覆盖率和字面完全匹配仅是辅助诊断，证据命中率也不直接等同于生成答案的语义正确率。

对已有评测报告，可直接用其中的 `chunk_id` 从当前数据库读取对应片段并核对证据，无须重新请求 `/query`：

```powershell
.\.venv\Scripts\python.exe .\scripts\evaluate_api.py --from-report .\data\test\api_evaluation_20261026-131201.json --input .\data\test\finance_qa_40.json --top-k 5
```

离线复核结果保存在 `data/test/api_evidence_evaluation_<时间>.json`；若数据库中的片段已被替换，脚本会提示缺失的 `chunk_id`。

比较原始混合检索与关键词加权 RRF 重排的证据命中率：

```powershell
.\.venv\Scripts\python.exe .\scripts\evaluate_rerank.py --input .\data\test\finance_qa_40.json --top-k 5 --candidate-k 50
```

报告保存在 `data/test/rerank_evaluation_<时间>.json`，同时列出语义、关键词、原混合检索及重排后的命中数、改善和退步题号。该脚本比较的是规则式关键词加权 RRF。

比较原始 RRF 与真正的交叉编码器重排：

```powershell
.\.venv\Scripts\python.exe .\scripts\evaluate_cross_encoder.py --input .\data\test\finance_qa_40.json --top-k 5
```

该脚本对相同的语义 Top 50、关键词 Top 50 候选进行“问题＋片段”联合打分，检查最终 Top 5 的 `source` 是否包含标注证据；证据不参与打分。报告保存在 `data/test/cross_encoder_evaluation_<时间>.json`。模型默认是 `BAAI/bge-reranker-v2-m3-int8`，约 0.57 GB，首次运行需要下载。40 题是探索性评测集，不能据此推断新题表现。

2026-11-01 的本机评测中，原 RRF 命中 35/40，交叉编码器命中 39/40；单题平均耗时约 25 秒。新方法已找回 qa-08、qa-22、qa-23、qa-26、qa-28，qa-02 从命中变为未命中。完整逐题结果见 `data/test/cross_encoder_evaluation_20261101.json`。

新增独立的 60 道带原文证据题，编号 qa-41 至 qa-100，保存在 `data/test/finance_qa_60.json`。需要在这套题上比较不同 Top K 时运行：

```powershell
.\.venv\Scripts\python.exe .\scripts\evaluate_topk_60.py --max-k 10
```

脚本先确认每条证据存在于标注来源的有效片段中，再使用相同的语义 Top 50 与关键词 Top 50 候选，输出原 RRF 和交叉编码器在 K=1 至指定上限时的证据命中曲线。标准是完整引文或省略号分隔的各段按顺序出现在同一个片段中；标准证据不参与检索和重排。报告会写到 `data/test/topk_60_evaluation_<时间>.json`。2026-11-02 的结果见 `data/test/topk_60_evaluation_20261102.json`。

100 题的当前配置评测使用语义 Top 20、关键词 Top 20、交叉编码器重排。K=4 时证据命中 99/100，K=7 时命中 100/100；完整逐题名次见 `data/test/topk_100_n20_current_20261102.json`。N=10/20/30/40/50 的候选池证据分析见 `data/test/candidate_n_analysis_20261102.json`。5 道题的配对计时中，N=20 的平均重排耗时约 10.8 秒，N=50 约 27.8 秒；这不包含检索、回答生成和模型首次加载。计时详情见 `data/test/candidate_n_benchmark_20261102.json`。如需用当前模型重新评测，可运行：

```powershell
.\.venv\Scripts\python.exe .\scripts\evaluate_topk_n_100.py --candidate-n 20 --max-k 10 --output .\data\test\topk_100_n20_recheck.json
```

仅复核 60 条标注证据而不启动检索时，运行 `.\.venv\Scripts\python.exe .\scripts\evaluate_topk_60.py --validate-only`。

## 旧版 Word 和 WPS 转换

Windows 上如果已安装 Microsoft Word，可将旧版 `.doc`/`.wps` 转成 `.docx`。原文件不会修改，输出会保存在 `data/converted`，并保留原目录结构。推荐使用 PowerShell 脚本，不需要额外安装 Python 包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\convert_legacy_office.ps1
```

转换报告位于 `data/conversion_report.csv`，转换后的文件位于 `data/converted`。然后在中文测试页点击“批量导入”对应的接口，或在 `/docs` 中执行 `POST /documents/ingest-directory`，系统会递归读取 `data/raw` 和 `data/converted`。`.wps` 是否能转换取决于本机 Word 对该文件的兼容性；失败文件会记录在报告中。

## 版本分支

发布新版本时新建对应的版本分支并推送该分支，不直接推送到 `main`。当前版本分支为 `1.0`。
