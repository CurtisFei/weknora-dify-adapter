# WeKnora–Dify 知识库适配器

这是一个独立部署的 FastAPI 服务，把 [Dify External Knowledge API](https://github.com/langgenius/dify-docs/blob/main/en/cloud/use-dify/knowledge/external-knowledge-api.mdx) 转换为 WeKnora 的知识库检索 API。它不会复制文档，也不修改 WeKnora 或 Dify。

```text
Dify -- POST /retrieval --> 本适配器 -- hybrid-search --> WeKnora
```

## 工作方式

- Dify 请求中的 `knowledge_id` 直接对应 WeKnora 知识库 ID。
- `query` 转换为 WeKnora 的 `query_text`。
- `top_k` 转换为 `match_count`，允许范围为 1–100。
- `score_threshold` 转换为 `vector_threshold`，允许范围为 0–1。
- 默认关闭关键词召回，使用纯向量检索，使返回分数与 Dify 的阈值语义一致。
- WeKnora 的 `knowledge_title` 或 `knowledge_filename` 转换为 Dify 的 `title`。

## 准备 WeKnora API Key

在 WeKnora 中创建一把独立的 API Key：

1. 只授予 `retrieve` 能力，不授予 `chat`、`ingest` 或管理权限。
2. 使用知识库白名单，只允许 Dify 需要访问的知识库。
3. 不要把该 Key 直接填写到 Dify；它只保存在适配器环境变量中。

## 配置

复制示例文件：

```bash
cp .env.example .env
```

| 环境变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `WEKNORA_BASE_URL` | 是 | — | WeKnora 地址，可带或不带 `/api/v1` |
| `WEKNORA_API_KEY` | 是 | — | WeKnora `retrieve` 权限 Key |
| `DIFY_ADAPTER_API_KEY` | 是 | — | Dify 调用适配器时使用的独立 Bearer Key |
| `WEKNORA_TIMEOUT_SECONDS` | 否 | `15` | 上游超时，范围 1–120 秒 |
| `LOG_LEVEL` | 否 | `INFO` | `CRITICAL/ERROR/WARNING/INFO/DEBUG` |
| `PORT` | 否 | `8000` | 监听端口 |

生产环境请为 `DIFY_ADAPTER_API_KEY` 生成高强度随机值，例如：

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

## Docker 部署

```bash
docker build -t weknora-dify-adapter .
docker run --rm --env-file .env -p 8000:8000 weknora-dify-adapter
```

也可以使用 Compose 示例：

```bash
docker compose -f compose.example.yml --env-file .env up -d --build
```

镜像使用非 root 用户运行，并内置 `/healthz` 健康检查。Compose 示例进一步启用只读根文件系统和 `no-new-privileges`。

## 本地开发

需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync --extra dev
cp .env.example .env
uv run uvicorn app.main:app --reload
```

质量检查：

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python -m build
```

## 配置 Dify

在 Dify 的知识库设置中注册 External Knowledge API：

- API Endpoint：`https://adapter.example.com`
- API Key：填写 `DIFY_ADAPTER_API_KEY` 的值

Dify 会自动调用：

```http
POST https://adapter.example.com/retrieval
Authorization: Bearer <DIFY_ADAPTER_API_KEY>
```

创建外部知识库时，将 External Knowledge ID 设置为对应的 WeKnora 知识库 ID。

## 手工验证

```bash
curl -sS http://localhost:8000/healthz
```

```bash
curl -sS http://localhost:8000/retrieval \
  -H "Authorization: Bearer $DIFY_ADAPTER_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "knowledge_id": "your-weknora-kb-id",
    "query": "退款流程是什么？",
    "retrieval_setting": {
      "top_k": 5,
      "score_threshold": 0.5
    }
  }'
```

成功响应：

```json
{
  "records": [
    {
      "content": "检索到的分块正文",
      "score": 0.91,
      "title": "退款流程.pdf",
      "metadata": {
        "knowledge_base_id": "kb-id",
        "knowledge_id": "document-id",
        "chunk_id": "chunk-id",
        "chunk_index": 2,
        "source": "file",
        "filename": "退款流程.pdf",
        "weknora_metadata": {},
        "weknora_chunk_metadata": {}
      }
    }
  ]
}
```

无匹配时返回 HTTP 200 和 `{"records":[]}`。

## 元数据过滤

第一版仅支持能够无损转换到 WeKnora 的条件：

| 字段 | 操作符 | 映射 |
| --- | --- | --- |
| `knowledge_base_id` | `is` | 必须等于请求中的 `knowledge_id` |
| `knowledge_id` | `is`、`in` | WeKnora `knowledge_ids` |
| `tag_id` / `tag_ids` | `is`、`in` | WeKnora `tag_ids` |

只支持 `and`。不支持的字段、操作符、`or` 或冲突条件会返回 400，不会被静默忽略。

## 错误状态

| 场景 | 状态码 |
| --- | ---: |
| 缺少或错误的适配器 Bearer Key | 401 |
| 请求校验或元数据条件失败 | 400 |
| WeKnora 返回 401 / 403 | 401 / 403 |
| WeKnora 超时 | 504 |
| WeKnora 无法连接、返回 5xx、无效 JSON 或无效响应结构 | 502 |

错误响应使用稳定格式：

```json
{
  "error_code": "upstream_unavailable",
  "message": "WeKnora could not be reached"
}
```

适配器不会向 Dify 转发 WeKnora 的错误正文。日志只记录请求 ID、状态、耗时和经过清理的资源标识，不记录 API Key、Authorization、完整查询或召回正文。

## 当前边界

- 一个 Dify 外部知识库对应一个 WeKnora 知识库。
- 不提供文档同步、Dify Dataset API、缓存、限流或管理界面。
- 需要混合检索时，应先针对 RRF 分数做单独标定，再修改适配器的检索策略。
