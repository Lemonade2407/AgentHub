# AgentHub 接口契约文档

> **项目名称：AgentHub**
> **文档类型：接口契约（Interface Contract）/ 详细接口设计**
> **版本：V1.0 MVP · Contract v1.3**
> **上游文档：AgentHub_系统设计文档.md**
> **日期：2026 年 9 月**

---

## 0. 文档说明

### 0.1 目的

系统设计文档已确定架构与模块边界，但 A / B / C / D 四人要并行开发，必须先把**跨模块的固定接口**冻结成书面契约。

本文档是**唯一接口事实来源（Single Source of Truth）**，覆盖四类契约：

| 类别 | 消费方 | 章节 |
|---|---|---|
| REST API 契约 | 前端 C ↔ 后端 D | §4 |
| SSE 事件契约 | 前端 C ↔ TraceService（D/A） | §5 |
| 内部 Python 接口契约 | A ↔ B ↔ D 之间 | §6 |
| 公共 DTO / 枚举契约 | 全体 | §2、§3 |

### 0.2 冻结规则

1. **冻结时点**：Week 1 Day 1 结束前冻结 §2、§3、§4、§5、§6，冻结后进入实现。
2. **变更流程**：任何字段增删改 → 在小组群发起变更说明 → 至少 2 名成员确认 → 更新本文档并升 **Contract 小版本号** → 同步通知受影响方。
3. **兼容性规则**：
   - 允许：新增可选字段、新增枚举值（消费方必须容忍未知枚举值）、新增接口。
   - 破坏性：删除/重命名字段、改字段类型、改语义、收紧必填 → 必须升大版本并同步改代码。
4. **实现偏差判定**：当代码与本文档不一致时，以本文档为准；确有必要改代码的，先改文档。
5. **未定义即禁止**：本文档未定义的接口，不得由任何一方私自调用或假设其行为。

### 0.3 命名与字段约定

| 项 | 约定 |
|---|---|
| 传输字段命名 | 全链路 `snake_case`（后端原生输出，前端不做自动驼峰转换） |
| 路径前缀 | `/api` |
| 时间格式 | ISO 8601 UTC，带 `Z`，如 `2026-09-10T08:30:00Z` |
| ID 类型 | `agent` / `mcp_server` / `mcp_tool` / `agent_step` 为 `int64`；`run_id` 为字符串 |
| run_id 格式 | `r_` + 12 位小写十六进制，如 `r_7f3a91c2b4e0` |
| thread_id 格式 | `t_` + 12 位小写十六进制；V1 每次 Run 新建 |
| 空值 | 可选字段缺失与 `null` 等价，消费方须同时兼容 |
| 大整数 | JSON 中的 `int64` 以 number 传输（V1 不涉及 2^53 溢出场景） |
| 字符编码 | UTF-8 |

---

## 1. 通用协议

### 1.1 请求头

| Header | 必填 | 说明 |
|---|---|---|
| `Content-Type: application/json` | 有 Body 时必填 | — |
| `Accept: text/event-stream` | SSE 接口必填 | — |
| `X-Request-Id` | 否 | 客户端可选传入；未传由后端生成。响应必回带 |
| `Last-Event-ID` | 否 | SSE 断线重连时由浏览器自动携带 |

V1 不做登录鉴权，无 `Authorization` 头；API Key 只存在后端环境变量中。

### 1.2 成功响应

- 返回资源本体，**不做** `{code, data}` 包装。
- 单资源：返回对象；列表：返回分页对象；创建：`201` + 对象；更新：`200` + 对象；删除：`204` 无 Body。
- 异步动作（Test / Discover / Run 创建）：`202` + 任务/资源描述对象。

### 1.3 分页

请求参数：

| 参数 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `page` | int | 1 | ≥ 1 |
| `page_size` | int | 20 | 1 ~ 100 |
| `sort` | string | `-created_at` | `-` 前缀表示倒序 |

响应结构（固定）：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

### 1.4 错误响应

所有非 2xx 响应统一为：

```json
{
  "code": "TOOL_TIMEOUT",
  "message": "MCP tool call timed out after 30000ms",
  "detail": { "qualified_name": "github.list_issues", "timeout_ms": 30000 },
  "request_id": "req_5c1a9f2d",
  "timestamp": "2026-09-10T08:30:00Z"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `code` | string | 是 | 机器可读错误码，见 §1.5 |
| `message` | string | 是 | 面向开发者的英文/中文短描述，可直接展示 |
| `detail` | object \| null | 否 | 结构化上下文，字段随错误码而定 |
| `request_id` | string | 是 | 用于日志追踪 |
| `timestamp` | datetime | 是 | 服务端时间 |

### 1.5 错误码表（冻结）

| code | HTTP | 触发场景 |
|---|---:|---|
| `VALIDATION_ERROR` | 400 | 请求体字段不合法（Pydantic 校验失败） |
| `INVALID_ARGUMENT` | 400 | 语义非法，如 `max_steps` 越界、endpoint 协议不允许 |
| `NOT_FOUND` | 404 | 资源不存在（Agent / Server / Tool / Run） |
| `TOOL_NOT_FOUND` | 404 | `qualified_name` 在 Registry 中不存在 |
| `RUN_NOT_FOUND` | 404 | `run_id` 不存在 |
| `CONFLICT` | 409 | 唯一约束冲突，如 Server 名重复 |
| `AGENT_DISABLED` | 409 | 对已禁用 Agent 发起 Run |
| `TOOL_NOT_BOUND` | 403 | 调用的 Tool 未被该 Agent 绑定 |
| `TOOL_RISK_DENIED` | 403 | 风险级别策略拒绝（`WRITE` / `HIGH_RISK` 在 V1 一律拒绝，无人工放行开关，见 §10 D2） |
| `RUN_NOT_RUNNING` | 409 | 对已结束 Run 执行取消等操作 |
| `NO_EXECUTABLE_TOOL` | 422 | Agent 无可用 Tool 且模型要求调用工具 |
| `TOOL_SCHEMA_INVALID` | 422 | Tool 入参不符合 `input_schema` |
| `MAX_STEPS_EXCEEDED` | 422 | 创建 Run 时 `max_steps` 与 Agent 配置冲突（预留） |
| `MCP_SERVER_UNREACHABLE` | 502 | MCP Server 连通性失败 |
| `MCP_DISCOVERY_FAILED` | 502 | `tools/list` 失败或返回不可解析 |
| `TOOL_EXECUTION_FAILED` | 502 | MCP `tools/call` 返回错误或协议异常 |
| `TOOL_TIMEOUT` | 504 | MCP Tool Call 超时 |
| `LLM_TIMEOUT` | 504 | LLM 请求超时（60s） |
| `LLM_AUTH_ERROR` | 502 | LLM 鉴权失败 |
| `LLM_QUOTA_EXCEEDED` | 429 | LLM 配额/限流 |
| `MODEL_OUTPUT_INVALID` | 502 | 模型输出无法解析为消息/工具调用 |
| `DB_UNAVAILABLE` | 503 | 数据库不可用 |
| `INTERNAL_ERROR` | 500 | 未归类异常 |

> 约定：**Run 内部**发生的 LLM / Tool 异常不通过 HTTP 错误码返回，而是写入 Run 的 `stop_reason` 与 Trace（见 §3.2、§5）。HTTP 错误码只在**同步请求路径**（CRUD、Test、Discover）使用。

### 1.6 幂等性

| 接口类型 | 幂等 |
|---|---|
| `GET` / `PUT` / `DELETE` | 是 |
| `POST /api/mcp/servers/{id}/discover` | 是（重复调用结果一致） |
| `POST /api/mcp/servers/{id}/test` | 是 |
| `POST /api/mcp/tools/{id}/test` | 否（可能产生副作用） |
| `POST /api/agents/{id}/runs` | 否 |

---

## 2. 枚举全集（冻结）

> 所有枚举在数据库中均以 `varchar` 存储，与下列字符串**完全一致**（UPPER_SNAKE）。

### 2.1 RunStatus

| 值 | 含义 |
|---|---|
| `PENDING` | 已创建，尚未开始执行 |
| `RUNNING` | LangGraph 执行中 |
| `SUCCESS` | 正常返回最终答案 |
| `PARTIAL` | 达到 max_steps 但已有中间输出 |
| `FAILED` | 模型/工具/系统错误导致中断 |
| `CANCELLED` | 客户端取消 |

### 2.2 StopReason

| 值 | 触发条件 | 对应 RunStatus |
|---|---|---|
| `FINISHED` | 模型返回无 `tool_calls` 的最终消息 | `SUCCESS` |
| `MAX_STEPS` | `step_count >= max_steps` | 有产出文本（含部分产出）→ `PARTIAL`；无 → `FAILED` |
| `MODEL_ERROR` | LLM 超时/鉴权/配额/解析失败 | `FAILED` |
| `TOOL_ERROR` | MCP Tool 失败且策略不重试 | `FAILED` |
| `INTERNAL_ERROR` | Runtime 内部异常（未归类的代码/依赖错误） | `FAILED` |
| `CANCELLED` | 用户取消 | `CANCELLED` |

### 2.3 StepStatus

| 值 | 含义 |
|---|---|
| `RUNNING` | 该步骤执行中（仅 SSE 中可能短暂出现） |
| `SUCCESS` | 成功 |
| `FAILED` | 失败（详见 `payload.error`） |
| `SKIPPED` | 未执行（如被降级跳过） |

### 2.4 RiskLevel

| 值 | 默认策略 |
|---|---|
| `READ_ONLY` | 允许 |
| `LOW_RISK` | 需显式启用 |
| `WRITE` | V1 禁用，不提供人工放行开关（见 §10 D2） |
| `HIGH_RISK` | V1 不接入，Discovery 时拒绝入库 |

### 2.5 McpServerStatus

| 值 | 含义 |
|---|---|
| `UNKNOWN` | 注册后未测试（初始值） |
| `CONNECTED` | 连通性测试通过 |
| `ERROR` | 连接或 Discovery 失败 |

### 2.6 TransportType

| 值 | V1 支持 |
|---|---|
| `streamable_http` | 是（MVP 唯一支持） |
| `stdio` | 否（P2） |

### 2.7 TraceEventType

| 值 | 说明 | 对应 SSE `event:` |
|---|---|---|
| `RUN_STARTED` | Run 开始 | `run_started` |
| `LLM_STARTED` | 开始调用模型 | `llm_started` |
| `LLM_FINISHED` | 模型调用结束 | `llm_finished` |
| `TOOL_CANDIDATES` | 动态工具选择结果 | `tool_candidates` |
| `TOOL_CALL_STARTED` | 开始执行 Tool | `tool_call_started` |
| `TOOL_CALL_FINISHED` | Tool 执行结束 | `tool_call_finished` |
| `STATE_UPDATED` | 步数/状态更新 | `state_updated` |
| `RUN_FINISHED` | Run 正常结束 | `run_finished` |
| `RUN_FAILED` | Run 异常结束 | `run_failed` |

> 持久化用 UPPER_SNAKE（`agent_step.event_type`）；SSE `event:` 字段用小写形式（**小写化即可，规则固定为 `str.lower()`**）。前端按小写匹配。

### 2.8 ModelVendor（约定值，非强枚举）

`MODEL` 字段为自由字符串，V1 约定使用 `provider/model` 形式，便于后端路由：

```text
deepseek/deepseek-chat
openai/gpt-4o-mini
qwen/qwen-plus
```

---

## 3. 公共 DTO（冻结）

命名以 Pydantic 类名为准；`Read` 结尾 = 响应对象，`Create` / `Update` = 请求对象。

### 3.1 Agent

```python
class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    model: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(default="", max_length=8000)
    max_steps: int = Field(default=8, ge=1, le=20)
    enabled: bool = True
    tool_ids: list[int] = []


class AgentUpdate(BaseModel):
    # 全部可选，未传字段保持不变
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=20)
    enabled: bool | None = None


class AgentRead(BaseModel):
    id: int
    name: str
    description: str | None
    model: str
    system_prompt: str
    max_steps: int
    enabled: bool
    tool_ids: list[int]          # 已绑定 Tool
    created_at: datetime
    updated_at: datetime


class AgentToolBind(BaseModel):
    tool_ids: list[int]          # 全量覆盖语义
```

**`PUT /api/agents/{id}/tools` 采用全量覆盖语义**（非增量），前端提交最终态即可。

### 3.2 MCP Server

```python
class McpServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)      # 唯一，即 server_slug
    endpoint: str = Field(min_length=1, max_length=512)
    transport: TransportType = TransportType.STREAMABLE_HTTP
    description: str | None = None
    enabled: bool = True
    headers: dict[str, str] | None = None               # 仅后端存储，永不回传


class McpServerUpdate(BaseModel):
    # name 不可修改：它派生出 server_slug，进而决定 mcp_tool.qualified_name（见 §10 D6）
    endpoint: str | None = None
    transport: TransportType | None = None
    description: str | None = None
    enabled: bool | None = None
    headers: dict[str, str] | None = None


class McpServerRead(BaseModel):
    id: int
    name: str
    endpoint: str
    transport: TransportType
    description: str | None
    enabled: bool
    status: McpServerStatus
    tool_count: int
    last_error: str | None
    last_discovered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class McpServerTestResult(BaseModel):
    ok: bool
    status: McpServerStatus
    latency_ms: int
    server_info: dict | None      # MCP initialize 返回的 serverInfo
    error_code: str | None
    error_message: str | None


class McpDiscoverResult(BaseModel):
    server_id: int
    status: McpServerStatus
    added: int
    updated: int
    removed: int
    total: int
    duration_ms: int
    error_code: str | None
    error_message: str | None
```

**`server_slug` 规则（冻结）**：`name` 小写化，非 `[a-z0-9]` 字符替换为 `_`，压缩连续 `_`，去除首尾 `_`。示例：`GitHub MCP` → `github_mcp`。

`name` **注册后不可修改**（见 §10 D6）：它派生出 `server_slug`，进而决定 `mcp_tool.qualified_name`，改名会让已绑定的 Tool 失效。

### 3.3 Tool

```python
class ToolDefinition(BaseModel):
    id: int
    server_id: int
    server_name: str
    remote_name: str
    qualified_name: str          # f"{server_slug}.{remote_name}"
    description: str
    input_schema: dict           # JSON Schema，直接来自 MCP tools/list
    risk_level: RiskLevel
    enabled: bool
    updated_at: datetime


class ToolTestRequest(BaseModel):
    arguments: dict = {}


class ToolTestResult(BaseModel):
    ok: bool
    duration_ms: int
    content: list[dict] | None   # MCP content 数组
    is_error: bool
    error_code: str | None
    error_message: str | None
```

`risk_level` 为**自动推断 + 可覆盖**：

| 判定顺序 | 规则 |
|---|---|
| 1 | 若 `annotations.readOnlyHint == true` → `READ_ONLY` |
| 2 | 若 tool 名匹配 `^(get|list|search|query|read|fetch|find|describe)_` → `READ_ONLY` |
| 3 | 若 tool 名匹配 `^(create|update|write|put|post|delete|remove|drop)_` → `WRITE` |
| 4 | 若匹配 `(^|_)(shell|exec|command|payment|transfer)($|_)` → `HIGH_RISK` |
| 5 | 其余 → `LOW_RISK` |

### 3.4 Run 与 Step

```python
class RunCreateRequest(BaseModel):
    input: str = Field(min_length=1, max_length=8000)
    max_steps: int | None = Field(default=None, ge=1, le=20)   # Run 级唯一可覆盖项
    stream: bool = False     # true 时响应返回后由前端另开 SSE（V1 固定 false）


class RunRead(BaseModel):
    id: str                       # run_id
    agent_id: int
    thread_id: str                # V1 每次 Run 新建，不复用、不承载历史上下文（见 §10 D4）
    status: RunStatus
    stop_reason: StopReason | None
    input: str
    output: str | None
    error_code: str | None
    error_message: str | None
    max_steps: int                # 本次 Run 实际生效的步数上限快照，用于复现（见 §10 D8）
    llm_calls: int
    tool_calls: int
    step_count: int
    duration_ms: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class StepRead(BaseModel):
    id: int
    run_id: str
    step_no: int
    event_type: TraceEventType
    status: StepStatus
    node: str | None            # "model_node" | "tools_node" | None
    tool: str | None            # qualified_name
    duration_ms: int | None
    payload: dict               # 见 §5.3
    created_at: datetime
```

**Run 级覆盖范围（见 §10 D1）**：仅 `max_steps` 可被 Run 请求覆盖；`system_prompt` / `model` / 工具绑定只能通过 Agent 配置（`PUT /api/agents/{id}`）修改，`RunCreateRequest` 中不得出现这些字段。

**`step_no` / `step_count` / `max_steps` 语义（冻结，见 §10 D7）**：这三个概念横跨 Runtime、Trace 与 UI，必须唯一定义。

| 概念 | 定义 |
|---|---|
| `step_no = 0` | Run 级事件（`RUN_STARTED`、`TOOL_CANDIDATES`），不对应任何图节点 |
| `step_no = N (N ≥ 1)` | 第 N 个 LangGraph 图执行步（super-step），一次节点执行 = 一步 |
| 同一 `step_no` 内 | 该步产生的全部事件共享同一 `step_no`（如 `LLM_STARTED` + `LLM_FINISHED`），按 `id ASC` 排序 |
| `RUN_FINISHED` / `RUN_FAILED` | `step_no = step_count`，靠更大的 `id` 排在最后 |
| `step_count` | 出现过的最大 `step_no`，即图节点执行总次数 |
| `max_steps` | 允许的最大图执行步数；`step_count >= max_steps` 触发 `MAX_STEPS` |

**重要**：`step_no` **不唯一**，同一 `step_no` 可对应多条 `StepRead`（见 §5.4 示例：3 次 model 节点 + 2 次 tools 节点 = 5 步，`step_count=5`、`llm_calls=3`、`tool_calls=2`）。前端时间线必须按 `step_no` 分组、组内按 `id` 排序，不得假设 `step_no` 唯一。

### 3.5 TraceEvent（内部 + SSE 共用）

```python
class TraceEvent(BaseModel):
    id: int | None = None            # = agent_step.id，作为 SSE 的 id
    run_id: str
    step_no: int
    event_type: TraceEventType
    status: StepStatus
    node: str | None = None
    tool: str | None = None
    duration_ms: int | None = None
    data: dict = {}
    timestamp: datetime
```

---

## 4. REST API 契约

### 4.1 Agent API

#### 4.1.1 创建 Agent

```text
POST /api/agents
```

Request Body：`AgentCreate`

```json
{
  "name": "Research Agent",
  "description": "演示用研究型 Agent",
  "model": "deepseek/deepseek-chat",
  "system_prompt": "你是一个研究员，优先使用工具获取事实。",
  "max_steps": 8,
  "enabled": true,
  "tool_ids": [12, 13]
}
```

Response `201`：`AgentRead`。若 `tool_ids` 中存在不存在的 Tool → `404 TOOL_NOT_FOUND`。

#### 4.1.2 Agent 列表

```text
GET /api/agents?page=1&page_size=20&enabled=true&keyword=research
```

| Query | 类型 | 必填 | 说明 |
|---|---|---|---|
| `page` / `page_size` | int | 否 | §1.3 |
| `enabled` | bool | 否 | 过滤启用状态 |
| `keyword` | string | 否 | 模糊匹配 `name` |

Response `200`：`Page[AgentRead]`。

#### 4.1.3 Agent 详情

```text
GET /api/agents/{agent_id}
```

Response `200`：`AgentRead`；`404 NOT_FOUND`。

#### 4.1.4 修改 Agent

```text
PUT /api/agents/{agent_id}
```

Request Body：`AgentUpdate`（部分更新，未传字段保持原值）。

Response `200`：`AgentRead`。

#### 4.1.5 删除 Agent

```text
DELETE /api/agents/{agent_id}
```

Response `204`。V1 为**软删除**（`deleted_at` 置位），历史 Run 保留可查。

#### 4.1.6 更新工具绑定

```text
PUT /api/agents/{agent_id}/tools
```

Request Body：`AgentToolBind`（全量覆盖）。

Response `200`：`AgentRead`。

---

### 4.2 MCP API

#### 4.2.1 注册 MCP Server

```text
POST /api/mcp/servers
```

Request Body：`McpServerCreate`

```json
{
  "name": "demo",
  "endpoint": "http://demo-mcp:8100/mcp",
  "transport": "streamable_http",
  "description": "课程自带 Demo MCP Server",
  "enabled": true,
  "headers": { "X-Api-Key": "***" }
}
```

约束（`INVALID_ARGUMENT`）：
- `transport=streamable_http` 时 endpoint 必须为 `http://` 或 `https://`；
- 禁止 `localhost` / `127.0.0.1` / `169.254.0.0/16` / 云元数据地址（除非 `ALLOW_PRIVATE_MCP=true`）；
- `name` 唯一（冲突 → `409 CONFLICT`）。

Response `201`：`McpServerRead`（`status=UNKNOWN`，`headers` 永不回传）。

#### 4.2.2 MCP Server 列表

```text
GET /api/mcp/servers?page=1&page_size=20&status=CONNECTED
```

Response `200`：`Page[McpServerRead]`。

#### 4.2.3 MCP Server 详情

```text
GET /api/mcp/servers/{server_id}
```

Response `200`：`McpServerRead`。

#### 4.2.4 修改 MCP Server

```text
PUT /api/mcp/servers/{server_id}
```

Request Body：`McpServerUpdate`（部分更新，未传字段保持原值）。**`name` 不可修改**（见 §10 D6）——请求体中若出现 `name` 则忽略该字段，不报错。

字段变更后的副作用：修改 `endpoint` / `transport` / `headers` 后，服务端将 `status` 置回 `UNKNOWN` 并清空 `last_error`，表示需要重新测试与 Discovery。

Response `200`：`McpServerRead`。

#### 4.2.5 连通性测试

```text
POST /api/mcp/servers/{server_id}/test
```

超时 10s。Response `200`：`McpServerTestResult`（业务失败也返回 200，靠 `ok` 判断）。副作用：更新 `mcp_server.status`。

#### 4.2.6 重新发现 Tool

```text
POST /api/mcp/servers/{server_id}/discover
```

流程：连通 → `tools/list` → 标准化 → 按 `(server_id, remote_name)` upsert → 标记本次未返回的 Tool 为 `enabled=false`（不物理删除）。

Discovery 边界规则（见 §10 D9）：

| 情况 | 处理 |
|---|---|
| upsert 冲突键 | `(server_id, remote_name)`；重复 Discovery 结果幂等 |
| `remote_name` 超过 128 字符 | **跳过该 Tool 并记 warning**，不阻断同 Server 其他 Tool 入库 |
| `input_schema` 非法（非 `type: object`） | 以 `{}` 入库并置 `enabled=false` |
| 识别为 `HIGH_RISK` 的 Tool | 直接丢弃，不入库 |

Response `200`：`McpDiscoverResult`。失败（不可达/解析失败）：更新 `status=ERROR` + `last_error`，返回 **`502 MCP_DISCOVERY_FAILED`**。

#### 4.2.7 查询 Tool

```text
GET /api/mcp/tools?server_id=1&enabled=true&risk_level=READ_ONLY&keyword=issues&page=1&page_size=50
```

Response `200`：`Page[ToolDefinition]`。

#### 4.2.8 手动测试 Tool

```text
POST /api/mcp/tools/{tool_id}/test
```

Request Body：`ToolTestRequest`。执行前做 `input_schema` 校验（失败 → `422 TOOL_SCHEMA_INVALID`），并拒绝 `HIGH_RISK` 与 `WRITE`（`403 TOOL_RISK_DENIED`）——V1 不提供任何人工放行开关（见 §10 D2）。

Response `200`：`ToolTestResult`；Tool Call 超时 → `504 TOOL_TIMEOUT`。

---

### 4.3 Run / Trace API

#### 4.3.1 创建并启动 Run

```text
POST /api/agents/{agent_id}/runs
```

Request Body：`RunCreateRequest`

```json
{ "input": "查一下 AgentHub 仓库最近 3 个 issue，并总结", "max_steps": 8 }
```

校验：Agent 存在且 `enabled=true`（否则 `409 AGENT_DISABLED`）；Agent 至少绑定 1 个 enabled Tool，否则 `422 NO_EXECUTABLE_TOOL`。

Response `202`：`RunRead`（`status=RUNNING`，`thread_id` 已生成）。**不等待执行完成**，前端拿到 `id` 后立即订阅 SSE。

#### 4.3.2 Run 摘要

```text
GET /api/runs/{run_id}
```

Response `200`：`RunRead`；`404 RUN_NOT_FOUND`。

#### 4.3.3 历史 Trace

```text
GET /api/runs/{run_id}/steps?after_step_no=0&page=1&page_size=200
```

| Query | 说明 |
|---|---|
| `after_step_no` | 仅返回 `step_no >` 该值的事件，用于增量补齐 |
| `page` / `page_size` | `page_size` 上限 500 |

排序固定：`step_no ASC, id ASC`。Response `200`：`Page[StepRead]`。

#### 4.3.4 SSE 实时事件

```text
GET /api/runs/{run_id}/events
Accept: text/event-stream
```

详见 §5。若 Run 已结束（`SUCCESS` / `FAILED` / `PARTIAL` / `CANCELLED`），服务端推送完历史事件后立即发送 `run_finished` / `run_failed` 并关闭连接。

#### 4.3.5 Agent 历史 Run

```text
GET /api/agents/{agent_id}/runs?status=SUCCESS&page=1&page_size=20
```

Response `200`：`Page[RunRead]`，默认 `-created_at`。

#### 4.3.6 取消 Run（P2）

```text
POST /api/runs/{run_id}/cancel
```

`202`：`RunRead`（`status=CANCELLED`, `stop_reason=CANCELLED`）。已结束 → `409 RUN_NOT_RUNNING`。V1 可先返回 `501`。

---

## 5. SSE 事件契约

### 5.1 连接与帧格式

```text
GET /api/runs/{run_id}/events
Accept: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

帧格式（严格）：

```text
event: tool_call_started
id: 16
data: {"run_id":"r_7f3a91c2b4e0","step_no":2,"event_type":"TOOL_CALL_STARTED","status":"RUNNING","node":"tools_node","tool":"github.list_issues","duration_ms":null,"data":{"arguments":{"state":"open"}},"timestamp":"2026-09-10T08:30:00Z"}

```

规则：
- `id` = `agent_step.id`（单调递增），用于断线续传；
- `data` 为 **单行 JSON**，不得含裸换行；
- 事件以空行结束；
- 每 15s 发送心跳：`: keep-alive`（注释帧，前端忽略）。

### 5.2 事件顺序保证

1. 同一 `run_id` 内事件严格按 `step_no` 递增推送，不重排、不去重。
2. 首个事件必为 `run_started`，末尾必为 `run_finished` 或 `run_failed`。
3. 若客户端连接时 Run 已产生历史事件，服务端先补推全部历史事件（按 `step_no`），再推实时事件。
4. 断线重连：浏览器携带 `Last-Event-ID`，服务端从 `id > Last-Event-ID` 开始补推。

### 5.3 各事件 `data` 字段契约

| event | data 字段 | 类型 | 说明 |
|---|---|---|---|
| `run_started` | `agent_id`, `input`, `max_steps`, `model` | int, string, int, string | Run 元信息 |
| `llm_started` | `model`, `message_count`, `candidate_tools` | string, int, string[] | `candidate_tools` 为本次注入的 `qualified_name` |
| `llm_finished` | `model`, `token_usage`, `finish_reason`, `tool_call_count`, `error` | object, object/string, int, object/null | `token_usage={"prompt":123,"completion":45,"total":168}` |
| `tool_candidates` | `names`, `scores`, `strategy`, `top_k` | string[], float[], string, int | `scores` 与 `names` 一一对应（降序）；`strategy="tfidf"`，未启用筛选时为 `"none"` |
| `tool_call_started` | `arguments` | object | 已通过 schema 校验的入参 |
| `tool_call_finished` | `result_summary`, `truncated`, `result_bytes`, `error` | string, bool, int, object/null | `result_summary` 截断至 2000 字符 |
| `state_updated` | `step_count`, `final_answer` | int, string/null | — |
| `run_finished` | `output`, `stop_reason`, `llm_calls`, `tool_calls`, `step_count` | string, string, int, int, int | — |
| `run_failed` | `stop_reason`, `error_code`, `error_message`, `partial_output` | string, string, string, string/null | — |

公共外层字段（每个事件都有）：`run_id`、`step_no`、`event_type`、`status`、`node`、`tool`、`duration_ms`、`data`、`timestamp`。

### 5.4 Run 结束事件与 RunStatus 的对应（冻结）

| `RunStatus` | 结束事件 | 说明 |
|---|---|---|
| `SUCCESS` | `run_finished` | `data.stop_reason == "FINISHED"` |
| `PARTIAL` | `run_finished` | `data.stop_reason == "MAX_STEPS"`，`data.output` 为部分产出 |
| `FAILED` | `run_failed` | `data.stop_reason` ∈ {`MAX_STEPS`, `MODEL_ERROR`, `TOOL_ERROR`, `INTERNAL_ERROR`} |
| `CANCELLED` | `run_failed` | `data.stop_reason == "CANCELLED"` |

> **注意**：`run_finished` **不等于成功**。前端必须以 `run.status`（或 `run_finished` 的 `data.stop_reason`）为准判断结果，不能只看事件名。

### 5.5 SSE 示例（完整一次 Run）

```text
event: run_started
id: 11
data: {"run_id":"r_7f3a91c2b4e0","step_no":0,"event_type":"RUN_STARTED","status":"SUCCESS","data":{"agent_id":3,"input":"查一下仓库最近3个issue","max_steps":8,"model":"deepseek/deepseek-chat"},"timestamp":"2026-09-10T08:30:00Z"}

event: tool_candidates
id: 12
data: {"run_id":"r_7f3a91c2b4e0","step_no":0,"event_type":"TOOL_CANDIDATES","status":"SUCCESS","data":{"names":["github.list_issues","search.search_web"],"scores":[0.81,0.42],"strategy":"tfidf","top_k":5},"timestamp":"2026-09-10T08:30:00Z"}

event: llm_started
id: 13
data: {"run_id":"r_7f3a91c2b4e0","step_no":1,"event_type":"LLM_STARTED","status":"RUNNING","node":"model_node","data":{"model":"deepseek/deepseek-chat","message_count":1,"candidate_tools":["github.list_issues","search.search_web"]},"timestamp":"2026-09-10T08:30:01Z"}

event: llm_finished
id: 14
data: {"run_id":"r_7f3a91c2b4e0","step_no":1,"event_type":"LLM_FINISHED","status":"SUCCESS","node":"model_node","duration_ms":1840,"data":{"model":"deepseek/deepseek-chat","token_usage":{"prompt":320,"completion":28,"total":348},"finish_reason":"tool_calls","tool_call_count":1},"timestamp":"2026-09-10T08:30:03Z"}

event: tool_call_started
id: 16
data: {"run_id":"r_7f3a91c2b4e0","step_no":2,"event_type":"TOOL_CALL_STARTED","status":"RUNNING","node":"tools_node","tool":"github.list_issues","data":{"arguments":{"state":"open","per_page":3}},"timestamp":"2026-09-10T08:30:03Z"}

event: tool_call_finished
id: 17
data: {"run_id":"r_7f3a91c2b4e0","step_no":2,"event_type":"TOOL_CALL_FINISHED","status":"SUCCESS","node":"tools_node","tool":"github.list_issues","duration_ms":418,"data":{"result_summary":"Found 3 issues: #12 ...","truncated":true,"result_bytes":8421},"timestamp":"2026-09-10T08:30:04Z"}

event: run_finished
id: 20
data: {"run_id":"r_7f3a91c2b4e0","step_no":5,"event_type":"RUN_FINISHED","status":"SUCCESS","duration_ms":9230,"data":{"output":"最近 3 个 issue 分别是……","stop_reason":"FINISHED","llm_calls":3,"tool_calls":2,"step_count":5},"timestamp":"2026-09-10T08:30:09Z"}
```

### 5.6 断连策略（与设计文档 §9.4 一致）

- 浏览器断开 SSE **不取消** Agent Run；Run 继续执行并持久化。
- 用户重新进入 Run Detail：先 `GET /api/runs/{run_id}` 拿状态 → `GET /api/runs/{run_id}/steps` 拿历史 → 若状态仍为 `RUNNING` / `PENDING` 再订阅 SSE（不带 `Last-Event-ID` 时服务端按 §5.2 规则 3 补推）。
- V1 `SSEBroker` 为进程内 `asyncio.Queue`，**只部署单 backend 实例**。

---

## 6. 内部 Python 接口契约

> 以下为跨成员（A/B/D）调用边界，签名冻结；实现细节各自自由。

### 6.1 A → B：Tool 能力边界

```python
class ToolCandidate(BaseModel):
    tool: ToolDefinition
    score: float                  # 相关性得分，降序返回；用于 TOOL_CANDIDATES 事件


class ToolSelector(Protocol):
    """A 调用：动态工具选择"""

    async def select(
        self,
        query: str,
        tools: list[ToolDefinition],
        top_k: int = 5,
    ) -> list[ToolCandidate]:
        """返回按 `score` 降序的 Top-K 候选（最多 `top_k` 个）。"""
```

```python
class McpToolGateway(Protocol):
    """A 调用：查询与执行 Tool"""

    async def list_tools(
        self,
        *,
        agent_id: int,
    ) -> list[ToolDefinition]:
        """返回该 Agent 已绑定且 enabled 的 Tool。"""

    async def execute_tool(
        self,
        call: ToolCall,
        ctx: ToolContext,
    ) -> ToolResult:
        """执行单个 Tool Call，内部完成 Permission + Schema 校验。
        约定：不抛业务异常，失败以 ToolResult.is_error=True 返回。"""
```

```python
class ToolCall(BaseModel):
    call_id: str                 # 模型返回的 tool_call.id
    qualified_name: str
    arguments: dict


class ToolContext(BaseModel):
    run_id: str
    agent_id: int
    step_no: int
    timeout_ms: int = 30_000


class ToolResult(BaseModel):
    call_id: str
    qualified_name: str
    ok: bool
    content: list[dict] = []     # MCP content（已裁剪）
    text: str = ""               # 拼平后的文本，直接回填 Observation
    duration_ms: int
    error_code: str | None = None
    error_message: str | None = None
```

### 6.2 D → A：Run 执行入口

```python
class AgentRunner(Protocol):
    async def run(
        self,
        *,
        run_id: str,
        thread_id: str,
        agent: AgentRead,
        user_input: str,
        max_steps: int,
        tracer: "TraceSink",
    ) -> RunResult: ...
```

```python
class RunResult(BaseModel):
    run_id: str
    status: RunStatus
    stop_reason: StopReason
    output: str | None
    llm_calls: int
    tool_calls: int
    step_count: int
    duration_ms: int
    error_code: str | None = None
    error_message: str | None = None
```

**约定**：`AgentRunner` 不感知 FastAPI / DB；Run 记录、Step 落库、SSE 推送均由 D 的实现通过 `tracer` 与返回值完成。

`thread_id` 由 D 生成（契约 §1 的 `t_` 格式）并在创建 Run 时传入，A 用它作为 LangGraph Checkpointer 的 thread key。V1 中 thread 与 run 一一对应，但两者保持独立标识——P2 支持多轮对话时一次 thread 会包含多个 run，届时 A 侧无需改动。

### 6.3 A / B → D：Trace 写入边界

```python
class TraceSink(Protocol):
    async def emit(self, event: TraceEvent) -> None: ...
```

- `emit()` 必须**非阻塞且不抛异常**（内部降级：DB 写失败只记日志，节流丢弃，不阻断 Runtime）；
- `emit()` 内部负责：分配 `id`（= `agent_step.id`，同时作为 SSE 的 `id`）、持久化 `agent_step`、投递 `asyncio.Queue`；
- `step_no` **由调用方（Runtime）提供**：它是 LangGraph 图执行步序号，语义只有 Runtime 掌握，Trace 层不得自行推导、递增或重排（见 §3.4）；
- `TraceEvent.data` 中禁止出现 `token` / `password` / `secret` / `api_key`，脱敏在 `TraceMapper` 完成（§7）。

### 6.4 D 内部：Repository 边界

```python
class AgentRepository(Protocol):
    async def get(self, agent_id: int) -> AgentRead | None: ...
    async def create(self, data: AgentCreate) -> AgentRead: ...


class RunRepository(Protocol):
    async def get(self, run_id: str) -> RunRead | None: ...
    async def finish(self, run_id: str, result: RunResult) -> None: ...
```

---

## 7. 数据脱敏与截断规则（冻结）

适用于写入 `agent_step.payload` 与 SSE `data`：

| 规则 | 内容 |
|---|---|
| 键名脱敏 | 键名（不区分大小写）匹配 `token`、`secret`、`password`、`passwd`、`api_key`、`apikey`、`authorization`、`cookie` → 值替换为 `"***"`，递归生效 |
| 文本截断 | `result_summary` / `text` 截断至 **2000 字符**，超出追加 `"...(truncated)"`，并置 `truncated=true` |
| 体积截断 | `agent_step.payload` 序列化后 > **64 KB** → 丢弃 `content` 数组，只保留 `text` 与 `error` |
| 不持久化 | Tool Result 原始 `content` 不落库；`headers` / API Key 永不落库明文 |
| 前端可见性 | SSE `data` 中不得出现任何后端环境变量内容 |

---

## 8. 前端 TypeScript 类型（自动映射基线）

```typescript
export type RunStatus =
  | 'PENDING' | 'RUNNING' | 'SUCCESS' | 'PARTIAL' | 'FAILED' | 'CANCELLED';

export type StopReason =
  | 'FINISHED' | 'MAX_STEPS' | 'MODEL_ERROR' | 'TOOL_ERROR' | 'CANCELLED';

export type RiskLevel = 'READ_ONLY' | 'LOW_RISK' | 'WRITE' | 'HIGH_RISK';

export enum TraceEventName {
  RunStarted = 'run_started',
  LlmStarted = 'llm_started',
  LlmFinished = 'llm_finished',
  ToolCandidates = 'tool_candidates',
  ToolCallStarted = 'tool_call_started',
  ToolCallFinished = 'tool_call_finished',
  StateUpdated = 'state_updated',
  RunFinished = 'run_finished',
  RunFailed = 'run_failed',
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ApiError {
  code: string;
  message: string;
  detail: Record<string, unknown> | null;
  request_id: string;
  timestamp: string;
}
```

前端约定：
- 枚举**只做展示映射，不做穷举校验**（容忍未知值，显示原始字符串）；
- Trace 事件按 `step_no` 排序渲染，不按到达顺序；
- `event_type` 用小写形式匹配 `TraceEventName`。

---

## 9. 联调与验收约定

### 9.1 Mock 基线

| 消费方 | 被 Mock 方 | 约定 |
|---|---|---|
| C（前端） | 后端 D | 用 §4 / §5 示例 JSON 造 mock server，字段名与枚举不得自创 |
| A（Runtime） | B（MCP Hub） | 用 §6.1 的 DTO 返回固定假数据 |
| B（MCP Hub） | 真实 MCP Server | 用 `demo_mcp_server/` 提供至少 3 个 Tool，覆盖成功/报错/超时 |

Demo MCP Server 由 `docker-compose` **默认启动**（见 §10 D5），但后端启动时**不自动注册**进平台：`mcp_server` 记录必须由用户在 MCP Center 手动创建后点击 Discovery 生成，以保证"注册 → 测试 → Discovery → 绑定 → 运行"的完整演示链路。

### 9.2 契约测试清单（Week 1 结束前完成）

1. `POST /api/agents` → `201` + `AgentRead`（字段齐全、类型正确）；
2. 错误路径返回 §1.4 结构 + 正确 `code`（至少覆盖 `NOT_FOUND`、`VALIDATION_ERROR`、`TOOL_NOT_FOUND`）；
3. SSE 一次完整 Run 的事件顺序满足 §5.2 规则 1/2，事件名与 §2.7 小写形式一致；
4. 断线重连携带 `Last-Event-ID` 能补齐后续事件，无重复、无丢失；
5. `agent_step.payload` 中不含 `***` 以外的敏感值，长文本按 §7 截断。

### 9.3 与设计文档的对应关系

| 本文档 | 设计文档位置 |
|---|---|
| §2 枚举 | §5 领域模型、§6.4 停止条件、§8.4 风险级别 |
| §3 DTO | §21 核心 DTO 示例（本文档为其完整化） |
| §4 REST | §11 API 设计（本文档为其字段级展开） |
| §5 SSE | §9 Execution Trace 与 SSE |
| §6 内部接口 | §7.3、§8.3、§16.1 协作约定 |
| §7 脱敏 | §10.2、§14.2 安全边界 |

---

## 10. 已确认决策（原待确认项）

> 2026-09-10 小组确认，全部纳入 Contract v1.1，不再作为开放问题。

| 编号 | 问题 | 决策 | 落点 |
|---|---|---|---|
| D1 | Agent 是否支持在 Run 时覆盖 `system_prompt` | **不支持**，Run 级仅 `max_steps` 可覆盖 | §3.4 |
| D2 | `WRITE` 级 Tool 是否允许人工放行 | **不允许**，V1 一律拒绝，放行开关推迟至 P2 | §1.5、§2.4、§4.2.8 |
| D3 | Run History 保留策略 | **不自动清理**，也不提供清理接口 | §10.1、数据库设计文档 |
| D4 | 多轮对话（同 `thread_id` 复用）是否进 V1 | **不做**；`thread_id` 每次新建，不复用、不承载历史 | §3.4 |
| D5 | Demo MCP Server 是否纳入 docker-compose 默认启动 | **纳入并默认启动**，但不自动注册进平台 | §9.1、部署文档 |

### 10.1 决策依据

- **D1 —— 保证 Run 可复现。** `system_prompt` / `model` / 工具绑定属配置态，任何一次 Run 都必须能由 `AgentDefinition` 完整还原；否则 `GET /api/runs/{id}` 无法解释当时的执行条件。调 Prompt 的正道是改 Agent 或另存 Agent。
- **D2 —— 成本高于收益。** 放行写操作需要二次确认 UI + 白名单开关 + 操作审计三件套；平台默认不产生写副作用，安全边界清晰、答辩易解释。
- **D3 —— 数据量不构成压力。** 课程演示量级为百级 Run，每个 Run 数十条 step；引入定时清理任务属基础设施膨胀，违反设计文档 §2.2 约束。落库侧保证 `(run_id, step_no)` 复合索引即可，需要清理时用 README 中的单条 SQL。
- **D4 —— 字段保留仅为占位。** 设计文档 §6.5 已定 Checkpointer 第一版用内存，§20 将多轮 Memory 列为"不做"。前后端均不得基于 `thread_id` 实现上下文延续。
- **D5 —— 答辩现场不赌外网可达性。** Demo Server 是唯一确定性可控的 MCP Server；不自动注册是为了保留完整演示链路，而非省略步骤。

### 10.2 由数据库设计衍生的跨模块约定

> 来源：AgentHub_数据库设计文档.md（DB Design v1.0），2026-09-10 起对契约生效。

| 编号 | 约定 | 落点 |
|---|---|---|
| D6 | **`mcp_server.name` 注册后不可修改**——它派生出 `server_slug`，进而决定 `mcp_tool.qualified_name`，改名会让已绑定 Tool 失效 | §3.2、§4.2.4 |
| D7 | **`step_no` 为 LangGraph 图执行步序号**，同一 `step_no` 可对应多条事件；事件唯一性由 `id` 承担，`(run_id, step_no)` 不唯一 | §3.4 |
| D8 | **Run 记录 `max_steps` 快照并在 `RunRead` 中暴露**——否则 Run 级覆盖后无法复现停止条件 | §3.4 |
| D9 | **Discovery 边界**：`remote_name` 超 128 字符跳过并记 warning；`input_schema` 非法则以 `{}` 入库并禁用；`HIGH_RISK` Tool 丢弃 | §4.2.6 |
| D10 | **新增 `PUT /api/mcp/servers/{server_id}`**——`McpServerCreate` 含 `enabled` 且存在 `McpServerUpdate`，但原接口清单（设计文档 §11.2）无更新入口，导致 Server 注册后无法启停或改 endpoint | §4.2.4 |

> D10 属**接口新增**（对既有消费方非破坏），但已超出设计文档 §11.2 的清单，需同步回设计文档。

### 10.3 由 Agent Runtime 实现（A）驱动的修正

> 来源：角色 A 的实现与测试（2026-09-10），纳入 Contract v1.3。

| 编号 | 约定 | 落点 |
|---|---|---|
| D11 | `TOOL_CANDIDATES` 属 Run 级事件，`step_no` 为 **0**（§5.5 示例已更正） | §3.4、§5.5 |
| D12 | `TraceSink.emit()` **只分配 `id`**；`step_no` 由 Runtime 提供，Trace 层不得推导 | §6.3 |
| D13 | `ToolSelector.select()` 返回 **`list[ToolCandidate]`**（`tool` + `score`），使 `scores` 字段有真实来源 | §6.1 |
| D14 | `StopReason` 新增 **`INTERNAL_ERROR`**，用于未归类的 Runtime 内部异常（避免误报为 `MODEL_ERROR`） | §2.2 |
| D15 | `AgentRunner.run()` 新增必填 **`thread_id`** 参数，A 用它作为 Checkpointer thread key | §6.2 |
| D16 | `PARTIAL` 通过"保留部分产出"变得可达；其结束事件仍是 `run_finished`，**`run_finished` ≠ 成功** | §2.2、§5.4 |

字段类型与长度（`varchar` 上界、`CHECK` 约束）、索引、级联删除规则、事务边界与语句超时，一律以数据库设计文档为准，本契约不再重复定义。

---

## 11. 版本记录

| 版本 | 日期 | 变更 | 确认人 |
|---|---|---|---|
| Contract v1.0 | 2026-09-10 | 首次冻结：枚举全集、DTO、REST、SSE、内部接口、脱敏规则 | A / B / C / D |
| Contract v1.1 | 2026-09-10 | 确认原 §10 五项决策（D1~D5）；收紧 `WRITE` 策略、明确 Run 覆盖范围与 `thread_id` 语义、Demo MCP Server 默认启动 | A / B / C / D |
| Contract v1.2 | 2026-09-10 | 吸收数据库设计（DB Design v1.0）：`McpServerUpdate` 移除 `name`（D6）、新增 `RunRead.max_steps`（D8）、冻结 `step_no` 语义（D7）、补充 Discovery 边界规则（D9）、新增 `PUT /api/mcp/servers/{id}`（D10）。除 D10 为接口新增外，其余属**实现前修正**，尚无消费方代码 | A / B / C / D |
| Contract v1.3 | 2026-09-10 | 吸收角色 A 实现：更正 `TOOL_CANDIDATES` 的 `step_no`（D11）、明确 `emit()` 不分配 `step_no`（D12）、`ToolSelector` 返回 `ToolCandidate`（D13）、`StopReason` 新增 `INTERNAL_ERROR`（D14）、`run()` 新增 `thread_id`（D15）、明确 `PARTIAL` 语义与结束事件对照表（D16） | A / B / C / D |
