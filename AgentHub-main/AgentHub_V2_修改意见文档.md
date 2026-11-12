# AgentHub V2 修改意见文档

> **项目名称：AgentHub**
> **文档类型：版本迭代修改意见 / 需求增补与分工**
> **版本：V2.0-Review（修改意见稿）**
> **上游文档：AgentHub_需求分析文档.md（V1.0）、AgentHub_系统设计文档.md（V1.0）、AgentHub_接口契约文档.md（Contract v1.3）、AgentHub_数据库设计文档.md（DB Design v1.2）**
> **日期：2026 年 11 月**
> **文档性质：本文档只提出修改意见、范围界定与分工，不修改任何代码。代码实施在评审通过后按 §10 的里程碑推进。**

---

## 0. 文档说明

### 0.1 为什么需要 V2

V1 已完成并跑通最小闭环：**创建 Agent → 接入 MCP 工具 → 运行 → 观察 Trace → 调试**。

V1 的模型接入是**进程级环境变量**方案（[model_provider.py](file:///d:/Code/AgentHub/agenthub/app/agent/model_provider.py) 读取 `LLM_API_KEY` / `LLM_BASE_URL`），Agent 的 `model` 只是一个 `provider/model` 字符串；平台没有用户概念，也没有任何复用与分享能力。这带来三个明确问题：

| 问题 | 现状 | V2 要解决的事 |
|---|---|---|
| 模型不可自助管理 | 换模型要改环境变量、重启服务；所有人共用一把 Key | 用户在界面里维护自己的模型 API，Agent 可各自选择不同模型 |
| 能力不可复用 | 每个 Agent 都要从头配 Prompt + 工具 | 引入 Skill，可封装、复用、分享 |
| Agent 不可流通 | Agent 只存在自己库里，无法沉淀 | 引入 Agent Center，可发布、发现、一键安装 |

### 0.2 V2 三个新模块 + 一次前端改版

| 编号 | 模块 | 一句话定义 | 主要归属 |
|---|---|---|---|
| M1 | **模型 API 管理（Model API）** | 用户级模型接入配置，Agent 可引用不同模型 | D（后端）+ A（运行时）+ C（前端） |
| M2 | **Skills Center** | 可复用的能力包（Prompt 片段 + 工具绑定 + 参数） | B（工具侧）+ D（平台）+ C（前端） |
| M3 | **Agent Center** | Agent 的发布、发现、安装与版本管理 | D（平台）+ B（依赖解析）+ C（前端） |
| M4 | **前端 Harness 化改版** | 参照 DeepSeek 类工作台的信息架构与交互 | C（主责） |

### 0.3 与现有文档的关系

本文档是**增量需求**，不推翻 V1 的架构与冻结契约。评审通过后按下表更新四份基线文档，版本号同步升级：

| 文档 | 需要新增/修改的章节 | 责任人 |
|---|---|---|
| 需求分析文档 | 新增 §1.6 V2 范围、新增 FR 编号、更新 §9 优先级 | A（统稿）+ 全员评审 |
| 接口契约文档 | 升 **Contract v2.0**：新增 §4.8~§4.12、DTO 扩展、错误码、鉴权头 | D |
| 数据库设计文档 | 升 **DB Design v2.0**：7 张新表 + `agent` 表变更 + 迁移与回填 | D |
| 系统设计文档 | 升 **V2.0**：模块图、模型网关、Skill 注入、发布安装时序 | A |

**冲突裁决顺序不变**：需求范围（本文档 + 需求分析文档）→ 接口契约 → 数据库设计 → 系统设计。

### 0.4 术语增补

| 术语 | 含义 |
|---|---|
| Model API | 用户维护的一类模型接入配置（provider + base_url + 密钥 + 可用模型清单） |
| Model Key | 某条 Model API 下具体可调用的模型名，如 `deepseek-chat` |
| Skill | 可复用的能力包：指令片段 + 工具集合 + 参数契约 + 示例 |
| Skill 绑定 | Agent 引用某个 Skill，并在运行时注入其内容 |
| Publication | Agent 的不可变发布快照，是 Agent Center 的陈列单位 |
| Install | 其他用户把 Publication 复制成本地 Agent 的动作 |
| Harness | 本文指“对话 + 工具 + 过程可视”的开发者工作台形态 |

---

## 1. V2 目标、范围与不做项

### 1.1 目标（按可演示验收描述）

1. 用户 A 登录后，可在 UI 中添加多条自己的模型 API，测试连通性，并让 Agent1 用 DeepSeek、Agent2 用自建网关模型，两者互不影响。
2. 用户可以把“System Prompt + 工具集合 + 参数”沉淀为 Skill，在任意 Agent 上挂载；Skill 可设为公开供他人复用。
3. 用户可以把 Agent 发布到 Agent Center；其他用户能搜索、查看、安装并直接运行，安装过程对缺失依赖给出明确提示。
4. 前端从“四个独立页面”升级为**一个工作台**：左侧资源导航、中间对话工作区、右侧执行过程，模型/Agent 选择器贴近输入框。

### 1.2 本期范围（P0）

| 模块 | 范围 |
|---|---|
| 身份 | 最小账号体系：注册 / 登录 / 退出 / 当前用户；不做角色与权限矩阵 |
| 模型 API | 用户级 CRUD、密钥加密存储、连通性测试、模型清单管理、默认模型、Agent 引用 |
| Skills | Skill CRUD、分类/标签、工具绑定、公开/私有、版本、安装计数、Agent 挂载 |
| Agent Center | 发布快照、下架、搜索/分类/排序、详情、点赞、安装（复制）、依赖预检、安装计数 |
| 前端 | 全局布局改版、工作台首页、模型设置页、Skills 页、Agent Center 页、Agent 编辑器改造、Playground 改造 |
| 兼容 | V1 数据迁移回填；V1 字段保留一个版本；SSE 事件契约向后兼容新增字段 |

### 1.3 明确不做（V2）

- 不做复杂 RBAC、组织/团队空间、多租户隔离。
- 不做在线支付、配额计费、Token 账单。
- 不做 Skill 的代码执行沙箱（Skill 只做声明式组合，不跑用户代码）。
- 不做 Agent Center 的人工审核后台（V2 用“发布即公开 + 举报下架”替代）。
- 不做前端 SSR、不做可视化 DAG 编排（延续 V1 边界）。
- 不做模型参数的高级调优面板（temperature/top_p 仅保留 temperature 一个字段）。

---

## 2. 总体架构增量

### 2.1 模块关系

```
                      ┌─────────────────────────────┐
                      │   Frontend (Harness UI)     │
                      │  Workbench / Model / Skills │
                      │  / Agent Center / MCP       │
                      └──────────────┬──────────────┘
                                     │ REST + SSE (Contract v2.0)
   ┌─────────────────────────────────▼──────────────────────────────────┐
   │                          FastAPI (D)                               │
   │  Auth · ModelApi API · Skill API · AgentCenter API · 既有 API       │
   └───────┬──────────────────┬──────────────────┬──────────────────────┘
           │                  │                  │
   ┌───────▼───────┐  ┌───────▼────────┐  ┌──────▼─────────────────────┐
   │ Model Gateway │  │ Skill Resolver │  │ Publication / Install 服务 │
   │      (A)      │  │   (A + B)      │  │        (D + B)             │
   └───────┬───────┘  └───────┬────────┘  └──────┬─────────────────────┘
           │                  │                  │
           └──────────────────┴──────────────────┘
                              │
                      ┌───────▼────────┐
                      │  PostgreSQL    │
                      │ 7 张新表 + 变更 │
                      └────────────────┘
```

### 2.2 三个关键改造点

1. **凭据来源从“进程环境变量”改为“数据库按用户存取”**：新增 `Model Gateway` 收敛模型构建逻辑，运行期按 `agent.model_api_id` 解密取 Key，不再读全局 `LLM_API_KEY`。
2. **Agent 定义从“单一 Prompt”变为“Prompt 基座 + Skill 叠加”**：运行前由 `Skill Resolver` 组装最终 system prompt 与候选工具集合，Trace 中记录本次生效的 Skill 列表。
3. **Agent 从“可编辑实体”派生出“不可变发布快照”**：发布时把 Agent + Skill + 工具依赖序列化为 `snapshot` JSONB，安装时做依赖解析与重建，避免引用失效。

---

## 3. M1 模型 API 管理

### 3.1 用户故事与验收

| 编号 | 用户故事 | 验收口径 |
|---|---|---|
| US-M1-1 | 我可以在设置页添加一条模型 API（名称、provider、base_url、API Key） | 保存后列表出现该条；Key 只显示 `****abcd` |
| US-M1-2 | 我可以点击“测试连接”，确认 Key 与地址可用 | 成功显示延迟与可用模型数；失败显示上游错误摘要，不泄露 Key |
| US-M1-3 | 我可以维护这条 API 下“我要用的模型清单” | 支持手动添加模型名，也支持测试后从上游拉取候选 |
| US-M1-4 | 我可以在 Agent 编辑器里选择“用哪条 API 的哪个模型” | 只能看到自己的 API；模型下拉随 API 联动 |
| US-M1-5 | 我可以设置某条 API/某个模型为默认 | 新建 Agent 时默认选中 |
| US-M1-6 | 同一平台可以有两个 Agent 分别使用不同模型同时运行 | 并发跑两个 Run，Trace 各自标注 `model_api_name` / `model_key` |

### 3.2 数据模型（草案，供 DB 文档吸收）

```sql
CREATE TABLE app_user (
  id            bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  email         varchar(128) NOT NULL,
  display_name  varchar(64)  NOT NULL,
  password_hash varchar(255) NOT NULL,
  status        varchar(16)  NOT NULL DEFAULT 'active', -- active | disabled
  created_at    timestamptz  NOT NULL DEFAULT now(),
  updated_at    timestamptz  NOT NULL DEFAULT now(),
  CONSTRAINT uq_app_user_email UNIQUE (email),
  CONSTRAINT ck_app_user_status CHECK (status IN ('active','disabled'))
);

CREATE TABLE model_api (
  id             bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  owner_id       bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  name           varchar(64)  NOT NULL,        -- 用户自定义，如“我的 DeepSeek”
  provider       varchar(32)  NOT NULL,        -- deepseek | openai | qwen | custom
  base_url       varchar(512) NOT NULL,
  api_key_cipher text         NOT NULL,        -- Fernet 密文，禁止明文
  api_key_hint   varchar(16),                  -- 仅末 4 位，用于界面展示
  is_default     boolean      NOT NULL DEFAULT false,
  enabled        boolean      NOT NULL DEFAULT true,
  last_test_at   timestamptz,
  last_test_ok   boolean,
  last_error     varchar(512),
  created_at     timestamptz  NOT NULL DEFAULT now(),
  updated_at     timestamptz  NOT NULL DEFAULT now(),
  CONSTRAINT uq_model_api_owner_name UNIQUE (owner_id, name)
);

CREATE TABLE model_api_model (
  id            bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  model_api_id  bigint NOT NULL REFERENCES model_api(id) ON DELETE CASCADE,
  model_key     varchar(128) NOT NULL,          -- 传给上游的 model 名
  display_name  varchar(128) NOT NULL,
  capabilities  jsonb        NOT NULL DEFAULT '{}', -- {"tool_call":true,"vision":false,"context_window":64000}
  enabled       boolean      NOT NULL DEFAULT true,
  is_default    boolean      NOT NULL DEFAULT false,
  created_at    timestamptz  NOT NULL DEFAULT now(),
  CONSTRAINT uq_model_api_model UNIQUE (model_api_id, model_key)
);
```

`agent` 表变更（过渡期兼容）：

```sql
ALTER TABLE agent ADD COLUMN owner_id     bigint REFERENCES app_user(id);
ALTER TABLE agent ADD COLUMN model_api_id bigint REFERENCES model_api(id) ON DELETE RESTRICT;
ALTER TABLE agent ADD COLUMN model_key    varchar(128);

-- 回填规则
-- 1) owner_id：统一回填为内置用户（首个注册用户或 seed 的 local 用户）
-- 2) model_api_id / model_key：按 V1 model 字符串拆分为 provider + name，
--    为每个 provider 建一条“系统迁移” Model API（密钥取原环境变量，仅迁移时写入密文）
-- 3) 保留 agent.model 一个版本，读路径优先 model_api_id + model_key，写路径双写
-- 4) 删除策略：Model API 被 Agent 引用时禁止物理删除，只允许置 enabled=false
```

### 3.3 接口清单（草案）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/auth/me` | 当前用户；未登录 401 |
| POST | `/api/auth/register` / `login` / `logout` | 最小账号体系，HttpOnly Cookie 会话 |
| GET | `/api/model-apis` | 我的模型 API 列表（Key 已掩码） |
| POST | `/api/model-apis` | 新建，`api_key` 仅入参，永不回显 |
| GET/PUT/DELETE | `/api/model-apis/{id}` | 详情 / 部分更新 / 删除（被引用返回 409） |
| POST | `/api/model-apis/{id}/test` | 连通性测试，返回 `ok / latency_ms / models / error` |
| GET | `/api/model-apis/{id}/models` | 该 API 下的模型清单 |
| POST/PUT/DELETE | `/api/model-apis/{id}/models[/{model_id}]` | 模型清单维护 |
| GET | `/api/model-apis/available` | Agent 编辑器用：树形“API → 模型”聚合 |

**新增错误码**：`MODEL_API_NOT_FOUND`、`MODEL_API_IN_USE`、`MODEL_API_TEST_FAILED`、`SECRET_DECRYPT_FAILED`、`MODEL_NOT_AVAILABLE`、`UNAUTHORIZED`、`EMAIL_TAKEN`。

### 3.4 运行时改造（A 负责）

1. `build_chat_model()` 签名改为 `build_chat_model(agent, model_api, model_key)`：不再读 `LLM_API_KEY`，由调用方传入已解密的 Key 与 base_url。
2. 新增 `ModelGateway`：负责解密、缓存（进程内 LRU，Key 明文不落日志）、超时、错误归类（鉴权失败 / 模型不存在 / 限流 / 网络）。
3. `Run` 开始时做模型可用性校验，失败即 `status=FAILED`，`error_message` 写可读原因，不产生半截 Trace。
4. Trace 的 run 级事件新增 `model_api_id`、`model_api_name`、`model_key`（契约新增可选字段，旧前端可忽略）。
5. 兼容：无 `model_api_id` 的历史 Agent 继续走环境变量路径，标记 `legacy`。

### 3.5 安全要求（硬性）

- 密钥使用 `cryptography.fernet` 对称加密，主密钥来自 `SECRET_KEY` 环境变量，**不落库、不写日志、不进 Trace**。
- 所有响应、SSE 事件、异常栈、请求日志统一脱敏；导出与分享（见 §5）不得包含密钥。
- `api_key` 仅允许“写入”，更新时留空表示不变；前端不得缓存明文。
- `GET /api/model-apis` 不返回 `base_url` 之外的任何凭据字段（含密文）。

---

## 4. M2 Skills Center

### 4.1 概念边界（必须先统一）

| 概念 | 是什么 | 不是什么 |
|---|---|---|
| Tool（MCP Tool） | 一次可调用的原子能力，有 input schema | 不含策略、不含指令 |
| Skill | 面向某类任务的能力包：指令片段 + 必需工具 + 参数契约 + 示例 | 不是可执行代码，不是独立进程 |
| Agent | 完整执行体：模型 + 基座 Prompt + Skills + Tools + 步数 | 不是 Skill 的集合别名 |

一句话：**Tool 是手，Skill 是招式，Agent 是会用招式的人。**

### 4.2 用户故事与验收

| 编号 | 用户故事 | 验收口径 |
|---|---|---|
| US-M2-1 | 我可以创建一个 Skill，写指令、绑工具、定义参数 | 保存后出现在“我的 Skills”，状态为草稿 |
| US-M2-2 | 我可以把 Skill 设为公开，别人能在 Skills Center 看到 | 公开后其他账号可搜索到、可安装 |
| US-M2-3 | 我可以在 Agent 编辑器里挂载多个 Skill，并调顺序 | 挂载后 Agent 详情展示 Skill 列表与顺序 |
| US-M2-4 | Skill 绑定的工具自动进入该 Agent 的候选工具池 | 运行时不需再手工绑定这些工具 |
| US-M2-5 | 运行时 Trace 能看到“本次注入了哪些 Skill、贡献了哪些工具” | Trace 中有 `skill_injected` 事件 |
| US-M2-6 | Skill 可带参数（如语气、输出格式），挂载时可覆盖默认值 | 参数通过 `params` 覆盖，运行前校验必填 |

### 4.3 数据模型（草案）

```sql
CREATE TABLE skill (
  id            bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  owner_id      bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  name          varchar(64)  NOT NULL,
  slug          varchar(80)  NOT NULL,
  summary       varchar(512) NOT NULL DEFAULT '',
  category      varchar(32)  NOT NULL DEFAULT 'general',  -- general | writing | coding | data | research | ops
  icon          varchar(64),                              -- 图标名，前端映射，不做图片上传
  version       varchar(16)  NOT NULL DEFAULT '1.0.0',
  visibility    varchar(16)  NOT NULL DEFAULT 'private',  -- private | public
  status        varchar(16)  NOT NULL DEFAULT 'draft',    -- draft | published | archived
  instructions  text         NOT NULL DEFAULT '',         -- 注入 system prompt 的片段，支持 {{param}} 占位
  input_schema  jsonb        NOT NULL DEFAULT '{}',       -- 参数契约（JSON Schema 子集）
  tags          jsonb        NOT NULL DEFAULT '[]',
  install_count integer      NOT NULL DEFAULT 0,
  like_count    integer      NOT NULL DEFAULT 0,
  created_at    timestamptz  NOT NULL DEFAULT now(),
  updated_at    timestamptz  NOT NULL DEFAULT now(),
  CONSTRAINT uq_skill_owner_slug UNIQUE (owner_id, slug),
  CONSTRAINT ck_skill_visibility CHECK (visibility IN ('private','public')),
  CONSTRAINT ck_skill_status CHECK (status IN ('draft','published','archived'))
);
CREATE INDEX idx_skill_public ON skill (status, visibility, category);

CREATE TABLE skill_tool (
  skill_id bigint NOT NULL REFERENCES skill(id) ON DELETE CASCADE,
  tool_id  bigint NOT NULL REFERENCES mcp_tool(id) ON DELETE CASCADE,
  required boolean NOT NULL DEFAULT true,
  PRIMARY KEY (skill_id, tool_id)
);

CREATE TABLE agent_skill (
  agent_id  bigint NOT NULL REFERENCES agent(id) ON DELETE CASCADE,
  skill_id  bigint NOT NULL REFERENCES skill(id) ON DELETE RESTRICT,
  order_no  smallint NOT NULL DEFAULT 0,
  enabled   boolean NOT NULL DEFAULT true,
  params    jsonb NOT NULL DEFAULT '{}',   -- 覆盖 Skill 默认参数
  PRIMARY KEY (agent_id, skill_id)
);
```

### 4.4 运行期组装规则（A + B）

```
final_system_prompt =
    agent.system_prompt
  + Σ (skill.instructions 渲染参数后)            # 按 order_no 升序
  + 固定约束段（工具使用边界、失败重试、输出格式）

candidate_tools =
    agent_tool（显式绑定）
  ∪ Σ skill_tool（仅 enabled 的 Skill）
  去重后进入既有的 Tool Selection（Top-K 不变）
```

约束：

1. Prompt 总长超过模型上下文 60% 时，按 Skill 顺序截断并在 Trace 中告警 `skill_prompt_truncated`。
2. Skill 的参数渲染只做字符串替换，**不做表达式求值**，避免注入。
3. Skill 引用的工具被禁用/删除时，运行时跳过该工具并在 Trace 中记录 `skill_tool_missing`；`required=true` 时直接拒绝运行并给出可读原因。
4. Skill 变更不影响已发布 Publication 的 `snapshot`（见 §5）。

### 4.5 接口清单（草案）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/skills` | 我的 Skills；`visibility/status/category/keyword` 过滤 |
| POST | `/api/skills` | 创建 |
| GET/PUT/DELETE | `/api/skills/{id}` | 详情 / 更新 / 删除（被 Agent 引用返回 409） |
| POST | `/api/skills/{id}/publish` | 公开（校验 instructions 非空、至少 1 个工具或允许零工具） |
| POST | `/api/skills/{id}/archive` | 下架 |
| GET | `/api/skills/center` | 公开 Skill 广场：搜索/分类/排序（最新、最热） |
| POST | `/api/skills/{id}/install` | 安装为“我的 Skill”（复制副本，不跟随原作者更新） |
| GET | `/api/skills/{id}/export` | 导出 JSON（脱敏，不含密钥） |
| PUT | `/api/agents/{id}/skills` | 全量覆盖 Agent 的 Skill 挂载与参数 |

新增错误码：`SKILL_NOT_FOUND`、`SKILL_IN_USE`、`SKILL_INVALID_PARAMS`、`SKILL_TOOL_MISSING`、`SKILL_ALREADY_INSTALLED`。

---

## 5. M3 Agent Center

### 5.1 核心设计：快照发布 + 复制安装

V2 不让用户“引用别人的 Agent”，而是**发布不可变快照 → 安装时复制成本地 Agent**。理由：

- 避免原作者改动/删除导致安装者运行失败；
- 避免跨用户的模型凭据、MCP headers 泄露；
- 安装后可自由改，符合“模板”心智。

### 5.2 用户故事与验收

| 编号 | 用户故事 | 验收口径 |
|---|---|---|
| US-M3-1 | 我可以把 Agent 发布到 Agent Center，填写标题、简介、分类、版本 | 发布后生成 Publication，原 Agent 继续可编辑 |
| US-M3-2 | 路人可以浏览/搜索/筛选 Agent Center | 支持关键词、分类、排序（最新/最热）；卡片显示名称、简介、作者、安装数、点赞数 |
| US-M3-3 | 我可以查看详情：完整 Prompt、Skill 列表、所需工具、示例输入 | 详情不出现任何密钥、headers、内部 id 以外的敏感信息 |
| US-M3-4 | 我可以一键安装，安装后得到一个可编辑、可运行的 Agent | 安装成功跳转 Agent 编辑器；计数 +1；重复安装提示已有副本 |
| US-M3-5 | 安装时若缺少依赖，我能看到明确清单并知道怎么补 | 预检给出缺失的 MCP Server 与 Skill，支持“安装缺失 Skill” |
| US-M3-6 | 我可以给 Publication 点赞 | 同一用户只能点一次，可取消 |
| US-M3-7 | 作者可以下架自己的 Publication | 下架后从广场消失，已安装副本不受影响 |

### 5.3 数据模型（草案）

```sql
CREATE TABLE agent_publication (
  id              bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  owner_id        bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  source_agent_id bigint REFERENCES agent(id) ON DELETE SET NULL,
  title           varchar(64)  NOT NULL,
  summary         varchar(512) NOT NULL DEFAULT '',
  category        varchar(32)  NOT NULL DEFAULT 'general',
  version         varchar(16)  NOT NULL DEFAULT '1.0.0',
  status          varchar(16)  NOT NULL DEFAULT 'published', -- draft | published | offline
  snapshot        jsonb        NOT NULL,   -- 脱敏后的不可变快照，结构见 §5.4
  install_count   integer      NOT NULL DEFAULT 0,
  like_count      integer      NOT NULL DEFAULT 0,
  published_at    timestamptz,
  created_at      timestamptz  NOT NULL DEFAULT now(),
  updated_at      timestamptz  NOT NULL DEFAULT now(),
  CONSTRAINT uq_agent_publication UNIQUE (owner_id, source_agent_id, version),
  CONSTRAINT ck_agent_publication_status CHECK (status IN ('draft','published','offline'))
);
CREATE INDEX idx_publication_feed ON agent_publication (status, category, published_at DESC);

CREATE TABLE publication_like (
  publication_id bigint NOT NULL REFERENCES agent_publication(id) ON DELETE CASCADE,
  user_id        bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (publication_id, user_id)
);

CREATE TABLE publication_install (
  id                  bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  publication_id      bigint NOT NULL REFERENCES agent_publication(id) ON DELETE CASCADE,
  installer_id        bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  installed_agent_id  bigint REFERENCES agent(id) ON DELETE SET NULL,
  created_at          timestamptz NOT NULL DEFAULT now()
);
```

### 5.4 快照结构（关键）

```json
{
  "schema_version": 1,
  "agent": {
    "name": "周报助手",
    "description": "把本周 Git 与日程整理成周报",
    "system_prompt": "...",
    "max_steps": 8,
    "required_capabilities": ["tool_call"]
  },
  "suggested_model": { "provider": "deepseek", "model_key": "deepseek-chat" },
  "skills": [
    { "slug": "weekly-report", "version": "1.0.0", "params": { "tone": "正式" } }
  ],
  "tools": [
    {
      "server_name": "git-tools",
      "remote_name": "list_commits",
      "transport": "streamable_http",
      "endpoint": "https://example.com/mcp",
      "required": true
    }
  ]
}
```

**脱敏与禁止项（硬性）**：

- 不写入：`api_key_cipher` / `api_key_hint` / `model_api_id` / `owner_id` / `agent.id` / MCP `headers` / Trace 内容。
- `endpoint` 允许写入（用于依赖提示），但安装时**不自动注册** MCP Server，只提示“需先注册同名 Server”。
- Skill 以 `slug + version` 引用；安装时优先匹配本地同名 Skill，其次匹配公开 Skill，都没有则提示安装。

### 5.5 接口清单（草案）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/agent-center` | 广场列表：`keyword/category/sort(latest\|popular)/page` |
| GET | `/api/agent-center/{publication_id}` | 详情（含快照、作者、计数） |
| POST | `/api/agents/{id}/publish` | 发布（body：title/summary/category/version） |
| POST | `/api/agent-center/{publication_id}/offline` | 下架（仅作者） |
| POST | `/api/agent-center/{publication_id}/like` / `unlike` | 点赞/取消 |
| POST | `/api/agent-center/{publication_id}/precheck` | 依赖预检：返回缺失的 Skill / MCP Server |
| POST | `/api/agent-center/{publication_id}/install` | 安装：先预检，可选 `confirm_missing=true` 跳过缺失项 |
| GET | `/api/agent-center/mine` | 我的发布列表（含草稿、计数） |

新增错误码：`PUBLICATION_NOT_FOUND`、`PUBLICATION_OFFLINE`、`PUBLICATION_FORBIDDEN`、`ALREADY_INSTALLED`、`INSTALL_DEPENDENCY_MISSING`、`SNAPSHOT_INVALID`。

### 5.6 安装算法（D 负责，B 提供工具解析）

```
1. 读取 publication.snapshot，校验 schema_version
2. 依赖解析：
   - skills：本地同名(owner=me) → 公开同名(version 匹配) → 标记缺失
   - tools：按 (server_name, remote_name) 在本地 Tool Registry 查找 → 缺失则标记
   - 模型：不强制匹配；安装后默认选中安装者的默认 Model API，若无则提示先配置
3. 若存在 required 缺失且 confirm_missing != true → 返回 409 + 缺失清单
4. 事务内创建 agent（owner=me）+ agent_skill + agent_tool，名称冲突自动追加 “(副本)”
5. 写 publication_install，install_count +1
6. 返回新 agent_id 与“安装后仍需处理的事项”列表
```

---

## 6. M4 前端 Harness 化改版

### 6.1 改版目标

V1 前端是 4 个平行页面（Agents / AgentEditor / MCP / Playground），没有全局框架，用户不知道“从哪开始”。V2 参照 DeepSeek 这类工作台产品的形态：

1. **一个壳 + 一个主工作区**：左侧固定导航，右侧内容区切换，不再整页跳转式切换。
2. **对话优先**：进入即工作台，输入框居中，选 Agent / 选模型在输入框上方，发送后进入“对话 + 过程”双栏。
3. **过程可见**：工具调用、Skill 注入、Observation 以可折叠块嵌在对话流里，右侧可展开完整 Trace 时间线。
4. **资源即条目**：Agent / Skill / MCP / Model API 都是“可检索的条目列表”，统一卡片、统一搜索、统一空状态。
5. **克制的视觉**：深色底、细边框、低饱和强调色、圆角 8~12px、无重阴影、无渐变堆叠。

### 6.2 信息架构

```
/                        工作台 Home（对话优先）
/chat/:runId?            对话 + Trace（同一页面，runId 可为空）
/agents                  Agents 列表
/agents/new | /agents/:id Agent 编辑器（Tabs：基础 / Skills / 工具 / 调试）
/skills                  Skills Center（我的 / 广场）
/skills/:id              Skill 编辑器
/mcp                     MCP Hub（沿用 V1，视觉改版）
/agent-center            Agent Center（广场）
/agent-center/:id        Publication 详情
/settings/models         模型 API 设置
/settings/profile        账号
```

导航分组建议：

| 分组 | 条目 |
|---|---|
| 工作 | 工作台、Agents |
| 资源 | Skills、Agent Center、MCP Hub |
| 设置 | 模型 API、账号 |

### 6.3 关键页面交互

**工作台 Home**

- 顶部：全局搜索（`Ctrl/Cmd + K` 命令面板，可搜 Agent / Skill / MCP）。
- 中央：大输入框 + 两个选择器（Agent、模型）；下方是“最近使用”和“推荐 Agent”卡片。
- 发送后：输入框收起到顶部，主体变为对话流；右侧 320~400px 为过程面板（可收起）。
- 流式输出：SSE 增量渲染，工具调用块默认折叠，展示工具名 + 状态 + 耗时。
- 失败态：明确区分“模型鉴权失败 / 模型不存在 / 工具失败 / 步数超限”，并提供“去配置模型”跳转。

**模型设置页**

- 列表：名称、provider、掩码 Key、模型数、上次测试状态、默认标记。
- 右侧抽屉编辑：名称 / provider / base_url / api_key（占位 `不修改则留空`）/ 模型清单（可编辑标签）。
- 测试按钮：加载中、成功（延迟 + 模型数）、失败（错误摘要 + 展开详情）。
- 删除：被 Agent 引用时禁用并提示引用数量。

**Skills Center**

- 顶部 Tab：我的 Skills / 广场。
- 左筛选：分类、可见性、状态；顶部搜索。
- 卡片：图标、名称、摘要、标签、工具数、安装数；hover 出现“挂载到 Agent / 安装”。
- 编辑器：左侧编辑（名称、指令、参数 schema、工具选择），右侧“预览”（渲染后的 Prompt 片段 + 参数表单）。

**Agent Center**

- 卡片网格 + 搜索 + 分类 + 排序（最新 / 最热）。
- 详情页：左侧简介 + Prompt 预览 + Skill / 工具依赖清单；右侧作者卡、安装按钮、点赞、版本。
- 安装流程：点击 → 预检弹窗 → 缺失项清单（可一键安装缺失 Skill）→ 成功后跳转 Agent 编辑器并提示“请选择模型”。

**Agent 编辑器改造**

- 新增 Tab：`基础`（名称/描述/Prompt/步数）、`模型`（Model API + 模型 + 参数）、`Skills`（挂载 + 排序 + 参数覆盖）、`工具`（沿用 V1，标注来源是 Skill 还是显式绑定）、`调试`（内嵌 Playground）。
- 提示：Skill 带来的工具以只读标签展示，避免与显式绑定混淆。

### 6.4 视觉与组件约定

| 项 | 约定 |
|---|---|
| 主题 | 深色为默认，预留 `prefers-color-scheme` 浅色变量 |
| 背景/层级 | `--bg-base #0F1115`、`--bg-panel #161A20`、`--bg-elevated #1D222B` |
| 文字 | 主 `#E6E8EB`、次 `#A3AAB5`、弱 `#6B7280` |
| 强调 | `#4D6BFE`（主按钮/焦点/链接），危险 `#F05D5D` |
| 描边 | 1px `rgba(255,255,255,0.08)`，不使用阴影表达层级 |
| 圆角 | 控件 8px、卡片 12px、气泡 16px |
| 字体 | 系统 UI 字体栈；代码/工具名用等宽字体 |
| 间距 | 4 的倍数；主区最大宽度 1200px，对话列 760px |
| 动效 | 仅用于出现/折叠，150~200ms；`prefers-reduced-motion` 时关闭 |
| 无障碍 | 全部交互可键盘到达；焦点环 2px；对比度 ≥ 4.5:1 |
| 响应式 | ≥1280 三栏；1024~1280 右侧过程面板改为抽屉；<768 单栏 + 底部标签栏 |

组件拆分建议（C 负责）：

- 布局：`AppShell`、`SidebarNav`、`TopBar`、`CommandPalette`
- 通用：`DataList`、`CardGrid`、`EmptyState`、`ErrorState`、`ConfirmDialog`、`Drawer`、`TagInput`
- 业务：`ModelApiForm`、`ModelSelector`、`SkillCard`、`SkillEditor`、`PublicationCard`、`InstallPrecheckDialog`、`TracePanel`、`TraceBlock`

### 6.5 前端验收

1. 1440 / 1280 / 768 三档无横向滚动、无遮挡。
2. 工作台可完成“选 Agent → 选模型 → 发消息 → 看流式输出 → 看工具块 → 看 Trace”，全程不刷新页面。
3. 模型 Key 在请求、响应、页面状态、localStorage 中均不出现明文。
4. 首屏可交互时间与 V1 相比不退化（本地网络下主观无卡顿）。
5. 空状态、加载态、错误态、无权限态四态齐备。

---

## 7. 对现有系统的改造清单

| 编号 | 位置 | 改造 | 归属 | 影响面 |
|---|---|---|---|---|
| CHG-1 | [model_provider.py](file:///d:/Code/AgentHub/agenthub/app/agent/model_provider.py) | 改为按 Model API 构建，新增 ModelGateway 与解密 | A | Runtime |
| CHG-2 | [agent.py](file:///d:/Code/AgentHub/agenthub/app/models/agent.py) | 增加 `owner_id / model_api_id / model_key` | D | 数据 |
| CHG-3 | [agent.py](file:///d:/Code/AgentHub/agenthub/app/schemas/agent.py) | DTO 新增字段并保留 `model` 兼容 | D | 契约 |
| CHG-4 | [agent.py](file:///d:/Code/AgentHub/agenthub/app/api/routers/agent.py) | 列表按 owner 过滤；创建/更新校验模型归属；新增 skill 挂载接口 | D | API |
| CHG-5 | [graph.py](file:///d:/Code/AgentHub/agenthub/app/agent/graph.py) | Prompt 组装接入 Skill Resolver；候选工具合并 | A | Runtime |
| CHG-6 | [selector.py](file:///d:/Code/AgentHub/agenthub/app/tools/selector.py) | 输入改为“Agent 绑定 ∪ Skill 绑定”后的工具池 | B | 工具选择 |
| CHG-7 | [events.py](file:///d:/Code/AgentHub/agenthub/app/trace/events.py) | 新增 `skill_injected`、`skill_tool_missing` 事件与模型字段 | A | Trace |
| CHG-8 | [index.ts](file:///d:/Code/AgentHub/frontend/src/router/index.ts) | 新路由与全局布局 | C | 前端 |
| CHG-9 | 全部视图 | 视觉与交互改版，复用 V1 已有的接口调用逻辑 | C | 前端 |
| CHG-10 | Alembic | 新增迁移：7 张新表 + `agent` 变更 + 回填脚本；必须可 downgrade | D | 数据 |
| CHG-11 | 契约文档 | 升 v2.0：鉴权、模型、Skill、Agent Center、SSE 新增事件 | D | 文档 |
| CHG-12 | 系统设计文档 | 新增模型网关、Skill 注入、发布安装时序图 | A | 文档 |

**兼容原则**：

- 新增字段一律可选；旧客户端不传不影响。
- SSE 只新增事件类型与字段，不删改 V1 事件；前端必须容忍未知事件。
- V1 的 MCP、Trace、Run 语义保持不变。
- 引入登录后，V2 提供“本地模式”开关：未登录时使用内置 local 用户，保证 V1 演示脚本仍可跑通。

---

## 8. 非功能要求

| 类别 | 要求 |
|---|---|
| 安全 | 密钥加密存储；接口不回显；日志/Trace/异常全链路脱敏；分享快照强制脱敏；Cookie 会话 `HttpOnly + SameSite=Lax` |
| 权限 | 所有资源按 `owner_id` 过滤；跨用户访问返回 404 而非 403，避免探测 |
| 性能 | 广场列表 P95 < 300ms（本地数据量级）；模型测试接口超时 10s；安装事务 < 1s |
| 一致性 | 安装/发布使用事务；计数使用原子 `UPDATE ... SET x = x + 1` |
| 可观测 | 模型调用失败按 provider 分类计数；安装失败记录原因；不打印任何密钥 |
| 数据迁移 | 迁移前自动备份说明写入文档；回填幂等；downgrade 可回退一步 |
| 错误体验 | 所有失败给“人能看懂的原因 + 下一步动作”，禁止只抛英文堆栈 |

---

## 9. 分工

沿用 V1 的四个角色，V2 新增工作包按“谁离得最近”分配。每人有一个**主责模块**和一个**协同模块**，避免都碰同一批文件。

### 9.1 角色总览

| 角色 | V1 职责 | V2 主责 | V2 协同 |
|---|---|---|---|
| **A** | Agent Runtime | 模型网关 + Skill 注入 + Trace 扩展 | 发布快照结构、文档统稿 |
| **B** | MCP Hub & Tool Selection | Skill 工具侧 + 安装依赖解析 + 顶会 | 模型能力校验（tool_call） |
| **C** | 前端 & Trace UI | 前端 Harness 改版（全部新页面） | 交互评审、可用性验收 |
| **D** | 平台 & 数据 | 账号、模型 API、Skills/Agent Center 后端、迁移 | 安全与脱敏落地 |

### 9.2 工作包明细

| 工作包 | 内容 | 负责人 | 交付物 | 依赖 | 完成标准 |
|---|---|---|---|---|---|
| WP-1.1 | 账号与会话（注册/登录/退出/me、local 模式） | D | 接口 + 中间件 + 迁移 | 无 | 未登录可跑 V1 演示；登录后资源隔离 |
| WP-1.2 | `model_api` / `model_api_model` 表与 CRUD、加密、掩码 | D | 表 + API + 单测 | WP-1.1 | Key 不出现于任何响应与日志 |
| WP-1.3 | 连通性测试与模型拉取 | D | `/test` 接口 | WP-1.2 | 成功/失败/超时三态可演示 |
| WP-1.4 | ModelGateway 重构与运行期解密 | A | Gateway + 单测 | WP-1.2、WP-2.1 | 两个 Agent 不同模型可并发运行 |
| WP-1.5 | Agent 模型字段迁移与双写兼容 | D + A | 迁移 + 回填脚本 | WP-1.2 | 历史 Agent 仍可运行 |
| WP-2.1 | 模型选择器与设置页 | C | 页面 + 组件 | WP-1.2、WP-1.3 | 完成 US-M1-1~5 |
| WP-2.2 | `skill` / `skill_tool` / `agent_skill` 表与 CRUD | D | 表 + API | WP-1.1 | 草稿/公开/归档状态流转正确 |
| WP-2.3 | Skill 广场、安装、导出 | D | API + 计数 | WP-2.2 | 跨账号可见可安装 |
| WP-2.4 | Skill Resolver（Prompt 组装 + 工具合并 + 参数渲染） | A | Resolver + 单测 | WP-2.2 | 注入顺序、截断、参数覆盖符合 §4.4 |
| WP-2.5 | 工具侧适配（Skill 工具池、缺失检测、去重） | B | selector 改造 + 单测 | WP-2.4 | Top-K 行为与 V1 一致 |
| WP-2.6 | Skills Center 页面与编辑器 | C | 页面 + 组件 | WP-2.2、WP-2.3 | 完成 US-M2-1~6 |
| WP-3.1 | `agent_publication` 等表、发布/下架/详情/列表 | D | 表 + API | WP-1.1 | 快照脱敏校验通过 |
| WP-3.2 | 快照序列化与脱敏规则 | A + D | serializer + 校验 | WP-3.1、WP-2.2 | 快照中无密钥/headers/id |
| WP-3.3 | 依赖预检与安装算法 | B + D | 预检/安装接口 | WP-3.1、WP-2.5 | 缺失项清单准确；安装后可直接运行 |
| WP-3.4 | Agent Center 页面与安装流程 | C | 页面 + 弹窗 | WP-3.1、WP-3.3 | 完成 US-M3-1~7 |
| WP-3.5 | 点赞、计数、我的发布 | D | API | WP-3.1 | 幂等、计数准确 |
| WP-4.1 | 全局壳（AppShell / 导航 / 命令面板 / 主题变量） | C | 布局组件 | 无 | 三档响应式通过 |
| WP-4.2 | 工作台 Home 与对话页（含 Trace 面板） | C | 页面 | WP-4.1、WP-1.4 | 流式 + 工具块 + Trace 全链路 |
| WP-4.3 | Agent 编辑器改造（Tabs / Skills / 模型） | C | 页面 | WP-2.6、WP-1.5 | 五个 Tab 可用且保存正确 |
| WP-4.4 | 视觉走查与可用性验收 | C 主 + 全员 | 走查清单 + 修复 | WP-4.x | §6.5 五条全过 |
| WP-5.1 | 契约 v2.0 更新 | D | 文档 | 各接口定稿 | 字段与代码一致 |
| WP-5.2 | DB 设计 v2.0 + 迁移说明 | D | 文档 | 表定稿 | DDL 与迁移一致 |
| WP-5.3 | 系统设计 V2.0（网关、注入、发布安装时序） | A | 文档 | WP-1.4、WP-2.4、WP-3.3 | 评审通过 |
| WP-5.4 | 需求文档 V2 章节与验收脚本 | A 统稿 | 文档 | 全部 | 评审通过 |

### 9.3 依赖与并行策略

```
M0 冻结（全员）：§3.2 / §4.3 / §5.3 表结构、§3.3 / §4.5 / §5.5 接口、§5.4 快照结构
        │
        ├── 轨道一（D）：账号 → 模型 API → Skill → Publication → 迁移
        │        └── 轨道一产出接口后，A / B / C 立即接
        ├── 轨道二（A）：ModelGateway → SkillResolver → 快照序列化 → Trace
        ├── 轨道三（B）：工具池合并 → 缺失检测 → 安装依赖解析
        └── 轨道四（C）：壳与设计变量 → 模型设置 → Skills → Agent Center → 工作台
```

并行铁律：

1. **先冻结接口再写实现**，任何人不得私自改字段；确需变更走 §0.3 的变更流程并升契约小版本。
2. C 的前端先基于 mock 数据开发（M0 后即可开始），不阻塞 D。
3. A / B 的运行期改造必须保留 V1 回退路径（`legacy` 模型 + 无 Skill），避免回归。
4. 每个工作包自带单测/验收脚本，联调前先自测。

### 9.4 里程碑与验收方式（不设时间，只设出口条件）

| 里程碑 | 出口条件 | 验收人 |
|---|---|---|
| M0 契约冻结 | 表结构、DTO、错误码、快照结构评审通过并写入契约/DB 文档 | 全员 |
| M1 模型链路 | 用户可建两条 API，两个 Agent 分别使用并跑通，Trace 标注模型 | A + D |
| M2 Skills | Skill 可创建/公开/挂载，Trace 出现 `skill_injected`，工具池合并正确 | A + B |
| M3 Agent Center | 跨账号发布→发现→预检→安装→运行全链路通过 | B + D |
| M4 前端收口 | §6.5 五条验收全过，三档响应式无问题 | C + 全员 |
| M5 文档与演示 | 四份文档升级完成，§10 演示脚本一次通过 | 全员 |

---

## 10. 验收演示脚本（评审现场按此走）

**场景一：模型隔离**

1. 注册用户 A，进入“模型 API”，添加 DeepSeek 与自建网关两条，均测试成功。
2. 创建 Agent-A（DeepSeek）、Agent-B（自建模型），各绑定一个工具。
3. 同时发起两个 Run，均成功；Trace 分别显示对应的 `model_api_name` / `model_key`。
4. 把 Agent-A 的 Key 改错，再运行：失败原因显示“鉴权失败”，页面提供“去配置模型”，不出现明文 Key。

**场景二：Skill 复用**

1. 创建 Skill“周报生成”，指令含 `{{tone}}` 参数，绑定 2 个工具，设为公开。
2. 在 Agent-C 上挂载该 Skill，参数填“正式”。
3. 运行：Trace 显示 `skill_injected`，2 个 Skill 工具进入候选池；最终 Prompt 中含渲染后的指令。
4. 禁用其中一个工具后再运行：Trace 显示 `skill_tool_missing`；若标记 required 则拒绝运行并说明原因。

**场景三：Agent Center 流通**

1. 用户 A 发布 Agent-C（版本 1.0.0），广场出现卡片。
2. 用户 B 登录，搜索到该卡片，进入详情，看到 Prompt 预览与依赖清单。
3. 点击安装：预检提示缺少 MCP Server；B 注册同名 Server 后重试成功，得到可编辑副本。
4. 运行成功；`install_count` +1；B 点赞后 `like_count` +1，重复点赞无效。
5. 用接口直接查 Publication 详情，确认无 `api_key` / `headers` / `owner_id` 等敏感字段。

**场景四：前端**

1. 1440 / 768 两档演示主流程与响应式。
2. 命令面板可跨资源搜索并跳转。
3. 工作台完成对话 → 工具块展开 → Trace 面板对照，全程无整页刷新。

**场景五：兼容**

1. 未登录（local 模式）执行 V1 的原演示脚本，结果不变。
2. 历史 Agent（仅 `model` 字符串）可直接运行。
3. 旧版前端（若保留构建产物）连新后端，未识别的新事件不导致崩溃。

---

## 11. 风险与待决策项

### 11.1 风险

| 编号 | 风险 | 影响 | 应对 |
|---|---|---|---|
| R1 | 引入账号体系会波及全部既有接口（按 owner 过滤） | 高 | 先落“local 模式 + owner 默认回填”，再逐接口加过滤；用集成测试兜底 |
| R2 | 密钥加密的主密钥管理不当 | 高 | `SECRET_KEY` 仅走环境变量；启动时校验长度；文档写明轮换步骤；禁止写入 Trace/日志 |
| R3 | Skill 与 MCP Tool 概念混淆，导致验收争议 | 中 | 以 §4.1 定义为准；UI 上明确“Skill 是能力包，Tool 是原子能力” |
| R4 | 发布快照泄露敏感信息 | 高 | 白名单序列化（只写允许字段）；发布前跑脱敏单测；接口层二次过滤 |
| R5 | 安装后依赖缺失导致“装了不能跑” | 中 | 强制预检 + 缺失清单 + 一键补装；详情页展示依赖徽标 |
| R6 | 前端改版范围过大拖慢联调 | 中 | 分两步：先壳与路由，再逐页替换；旧逻辑保留在组件内复用 |
| R7 | 多模型并发下的连接与超时问题 | 中 | 按 Model API 维度复用客户端；超时与重试策略集中在 Gateway |
| R8 | 迁移不可逆导致演示环境损坏 | 中 | 迁移必须实现 downgrade；迁移前备份脚本写入文档 |

### 11.2 待决策项（M0 前必须给出结论）

| 编号 | 待决策 | 建议 | 决策人 |
|---|---|---|---|
| Q1 | V2 是否必须登录才能使用 | 建议“默认要求登录，保留 `AUTH_MODE=local` 供演示与回归” | 全员 |
| Q2 | Agent Center 是否需要审核 | 建议 V2 不做审核，改为“发布即公开 + 举报下架 + 作者可下架” | D |
| Q3 | Skill 是否允许零工具 | 建议允许（纯提示词型 Skill），但发布时提示“无工具依赖” | A + B |
| Q4 | 发布的 Agent 是否自动跟随 Skill 更新 | 建议不跟随，快照固定版本；原 Agent 重新发布会生成新版本 | D |
| Q5 | 模型参数是否只保留 temperature | 建议 V2 只保留 temperature（0~2），其余进 V3 | A |
| Q6 | 是否允许匿名浏览 Agent Center | 建议允许浏览，安装需登录 | C + D |
| Q7 | 是否引入头像/图片上传 | 建议不引入，用首字母与图标名替代 | C |

---

## 12. 交付物清单

| 交付物 | 负责人 | 形式 |
|---|---|---|
| Contract v2.0（新增接口、DTO、错误码、SSE 事件） | D | 更新 `AgentHub_接口契约文档.md` |
| DB Design v2.0（7 张新表、`agent` 变更、迁移与回填） | D | 更新 `AgentHub_数据库设计文档.md` |
| 系统设计 V2.0（网关、注入、发布安装时序） | A | 更新 `AgentHub_系统设计文档.md` |
| 需求文档 V2 章节（FR 增补、优先级、验收） | A | 更新 `AgentHub_需求分析文档.md` |
| 后端：账号 / 模型 API / Skills / Agent Center + 迁移 | D | 代码 + 单测 |
| 运行时：ModelGateway / SkillResolver / Trace 扩展 | A | 代码 + 单测 |
| 工具侧：工具池合并 / 缺失检测 / 安装依赖解析 | B | 代码 + 单测 |
| 前端：全局壳 + 5 个页面改造 + 组件库 | C | 代码 + 走查清单 |
| 演示脚本与回归清单 | 全员 | §10 扩充为可执行清单 |

---

## 13. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| V2.0-Review | 2026-11-09 | 初稿：新增模型 API 管理、Skills Center、Agent Center、前端 Harness 化改版，并给出分工、里程碑与验收脚本 |
