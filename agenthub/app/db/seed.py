"""示例数据初始化：MCP Server / Model API / Skill / Agent。

Agent 与 Skill 是数据库记录，不随代码仓库分发；新环境启动后需要写入一份
示例数据，队友才能看到「天气助手」「文档生成 Agent」等内置对象。

本脚本幂等：
- MCP Server 按 `name`、Model API 按 `(owner, name)`、Skill 按 `(owner, slug)`、
  Agent 按 `(owner, name)` 匹配，存在则更新，不存在则创建；
- 绑定关系（Agent-Tool / Agent-Skill / Skill-Tool）按配置重建。

运行前提：后端已完成建表，且本地 MCP Server（8100/8102/8103）已启动，
否则 Tool 发现会失败（此时仍会创建 Server/Skill/Agent，只是缺少工具绑定）。

用法::

    cd agenthub
    .venv\\Scripts\\python -m app.db.seed

`dev.ps1` 在启动全部服务后会自动调用一次。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import LOCAL_USER_EMAIL
from app.core.crypto import SecretDecryptError, encrypt_secret
from app.db.session import SessionFactory, create_schema, engine
from app.mcp.client_adapter import HttpMcpClientFactory
from app.mcp.discovery import DiscoveryService, McpDiscoveryError
from app.models.agent import Agent, AgentTool
from app.models.mcp import McpServer
from app.models.model_api import ModelApi, ModelApiModel
from app.models.skill import AgentSkill, Skill, SkillTool
from app.models.user import AppUser
from app.repositories.mcp_repository import McpServerRepository, McpToolRepository
from app.services.workspace_service import ensure_agent_dir, ensure_skill_dir

logger = logging.getLogger("agenthub.seed")

SERVERS: list[dict[str, str]] = [
    {
        "name": "demo-mcp",
        "endpoint": "http://127.0.0.1:8100/mcp",
        "description": "本地演示 MCP Server",
    },
    {
        "name": "weather-mcp",
        "endpoint": "http://127.0.0.1:8102/mcp",
        "description": "open-meteo 天气查询（query_weather）",
    },
    {
        "name": "document-mcp",
        "endpoint": "http://127.0.0.1:8103/mcp",
        "description": "Word/PDF 文档生成（generate_document）",
    },
]

SKILLS: list[dict[str, Any]] = [
    {
        "slug": "skill-2",
        "name": "文档排版",
        "summary": "统一文档标题层级、段落节奏与列表规范，并调用文档生成工具",
        "category": "general",
        "icon": None,
        "tags": ["文档", "排版"],
        "instructions": (
            "你是一个专业的文档排版与生成专家。请根据提供的内容，统一文档层级，并调用工具生成文件。\n\n"
            "【排版规范（极其重要）】\n"
            "在组织最终文本时，你必须使用 Markdown 语法严格标记层级，以便后端工具识别并应用对应字体：\n"
            "1. 文档总标题：使用 `# `（一级标题）。\n"
            "2. 章节小标题：使用 `## `（二级标题）。\n"
            "3. 正文段落：直接输出普通段落，不要加任何标题标记，段与段之间留一个空行。\n"
            "4. 列表：使用 `- ` 或 `1. `。\n\n"
            "【核心要求】\n"
            "1. 严格按照大纲和上述规范，整理出最终要写入文档的纯文本内容。\n"
            "2. 必须调用绑定的“文档生成工具”，生成真实的 Word/PDF 文件。\n"
            "3. 工具返回成功结果后，你只需提取工具返回的那个纯 URL 链接。\n"
            "4. **绝对禁止**对链接进行任何包装（不要加 []、()、<> 或 Markdown 语法）。直接输出纯文本 URL。\n\n"
            "【格式转换】如果用户要求把上一轮已生成的文档改为另一种格式（例如把 Word 改为 PDF，"
            "或把 PDF 改为 Word），调用 generate_document 时传 source_name=上一轮返回的文件名、"
            "format=目标格式，不要重新编写正文。"
        ),
        "input_schema": {},
        "tools": [{"qualified_name": "document_mcp.generate_document", "required": True}],
    },
    {
        "slug": "skill-3",
        "name": "大纲生成",
        "summary": "先把文档任务拆成结构化大纲，再展开正文",
        "category": "general",
        "icon": None,
        "tags": ["文档", "大纲"],
        "instructions": (
            "你是一个专业的文档大纲规划助手。请根据用户的需求，输出结构化的文档大纲。\n\n"
            "【输出规范】\n"
            "1. 文档目标与读者（1-2 句话）\n"
            "2. 核心章节（3-6 个一级标题）\n"
            "3. 每个章节下的内容要点（每个章节 3-5 条要点）\n"
            "4. 结论与下一步\n\n"
            "【重要约束】\n"
            "- 你的任务是**只输出大纲结构**。绝对不要展开写正文！\n"
            "- 绝对不要调用任何文件生成工具（那是其他步骤的事）。\n"
            "- 只要大纲梳理清晰，你的任务就完成了，等待下一步指令。"
        ),
        "input_schema": {},
        "tools": [],
    },
    {
        "slug": "python-coding-guide",
        "name": "Python编码规范",
        "summary": "按统一规范编写可运行、可维护的Python代码",
        "category": "coding",
        "icon": "PythonCode",
        "tags": ["代码，规范"],
        "instructions": (
            "你是一个精通各种编程语言的高级代码助手。请严格按照以下规则处理用户的编码、修改或重构请求：\n\n"
            "【语言识别】\n"
            "自动识别用户输入中指定的语言（如 Java, C++, Go, JavaScript 等）。如果用户未指定，则默认使用 Python。\n\n"
            "【模式判断与输出规范】\n"
            "1. 【纯代码模式】（当用户仅要求代码，如“只给我代码”、“直接给代码”或未作特殊说明时）：\n"
            "   - 你的整个回答只能包含一个 Markdown 代码块（如 ```python ... ```）。\n"
            "   - 绝对禁止在代码块外输出任何解释、问候、前言或后记（如“好的”、“以下是代码”、“希望这能帮到你”等）。\n"
            "   - 确保缩进、空格、标点符号完全符合该语言的语法规范，保证用户复制后无需任何修改即可直接运行。\n\n"
            "2. 【注释讲解模式】（当用户要求“加解释”、“加注释”或“讲讲思路”时）：\n"
            "   - 输出完整可运行的代码。\n"
            "   - 在关键的逻辑、复杂的算法或修复了 bug 的地方，使用该语言的单行或多行注释（如 //, #, /* */）进行说明。\n"
            "   - 注释必须放在代码内部，不破坏代码结构的完整性。\n"
            "   - 依然要保证代码可以被直接复制运行。\n\n"
            "【代码修改与纠错】\n"
            "当用户提供错误代码时，直接修复错误。如果未要求解释，直接输出修复后的【纯代码】。\n\n"
            "【绝对底线】\n"
            "禁止编造不存在的 API 或库。如遇不确定，必须在代码注释中写明假设。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "default": "Python",
                    "description": "目标语言",
                }
            },
        },
        "tools": [],
    },
]

AGENTS: list[dict[str, Any]] = [
    {
        "name": "chat",
        "description": "用于普通聊天",
        "max_steps": 8,
        "tools": ["demo_mcp.list_issues"],
        "skills": [],
        "system_prompt": (
            "你是一个通用 AI 助理。只有在确实需要查询外部数据或执行操作时才调用工具；"
            "对于问候、闲聊、常识问题，直接回答，不要调用工具。回答使用简体中文。"
        ),
    },
    {
        "name": "天气助手",
        "description": "查询城市指定日期的天气（open-meteo）",
        "max_steps": 6,
        "tools": ["weather_mcp.query_weather"],
        "skills": [],
        "system_prompt": (
            "你是天气查询助手。用户输入类似「上海9月1日」「北京和上海明天」「上海9月1日到9月3日」时，"
            "提取城市和日期，调用 query_weather 工具：city 可为多个城市（用顿号分隔），"
            "date 为起始日期，end_date 为结束日期。回答用简洁中文播报每个城市的日期、天气现象、"
            "气温范围、降水、风速；不要编造数据，只使用工具返回结果。"
        ),
    },
    {
        "name": "文档生成 Agent",
        "description": "通用文档生成：按大纲组织内容，输出 Word/PDF 到专属工作区",
        "max_steps": 10,
        "tools": ["document_mcp.generate_document"],
        "skills": [
            {"slug": "skill-2", "order_no": 0},
            {"slug": "skill-3", "order_no": 1},
        ],
        "system_prompt": (
            "你是文档生成助手。你的核心任务是根据用户的需求生成 Word 或 PDF 文档。\n\n"
            "【执行流程】\n"
            "1. 收到需求后，先调用【大纲生成】Skill 理清结构。\n"
            "2. 再调用【文档排版】Skill，让该 Skill 调用工具生成文件。\n"
            "3. 文件生成成功后，你必须严格按照下方【输出格式】回复用户，绝对禁止输出任何多余的开场白或解释。\n\n"
            "【输出格式】（必须一字不差地遵循，禁止使用加粗符号 **）\n"
            "文档已生成完毕 ✅\n\n"
            "- 文件名：这里填入真实文件名\n"
            "- 格式：这里填入 DOCX 或 PDF\n"
            "- 文件链接：这里直接输出后端返回的纯 URL 链接（不要加任何括号、引号、Markdown语法或 HTML 标签，"
            "必须是一段连续的英文字母和斜杠）\n\n"
            "正文约 [字数] 字，如需调整请随时告诉我。\n\n"
            "【底线要求】\n"
            "链接必须是纯文本的 URL。如果你加上了多余的文字或符号（比如把链接放进 [] 里），"
            "会导致前端卡片渲染失败。"
        ),
    },
    {
        "name": "代码助手",
        "description": "按规范编写、解释和审查代码",
        "max_steps": 8,
        "tools": ["demo_mcp.search_web"],
        "skills": [
            {
                "slug": "python-coding-guide",
                "order_no": 0,
                "params": {"language": "通用编程语言"},
            }
        ],
        "system_prompt": (
            "你是代码助手 Agent。你的核心任务是根据用户的需求编写、修改或审查代码。\n"
            "收到任务后：\n"
            "1. 严格遵守挂载的「通用代码规范」Skill 中的规则。\n"
            "2. 仔细分析用户是否要求“只给代码”或“需要解释”。如果用户要求纯代码，"
            "你的回复必须以代码块开头，以代码块结尾，不要在代码块外有任何废话。\n"
            "3. 如果用户给了报错信息或错误代码，先分析原因，然后直接给出修复后的代码。"
        ),
    },
]

DEMO_MODEL = {
    "name": "本地演示模型",
    "provider": "custom",
    "base_url": "http://127.0.0.1:8101/v1",
    "api_key": "demo-key",
    "model_key": "demo-chat",
    "display_name": "Demo Chat",
    "capabilities": {"tool_call": True, "context_window": 32000},
}


def _touch(obj: Any) -> Any:
    """兼容历史建表脚本：部分表的 created_at/updated_at 没有数据库默认值。"""
    now = datetime.now(UTC)
    if hasattr(obj, "created_at"):
        obj.created_at = now
    if hasattr(obj, "updated_at"):
        obj.updated_at = now
    return obj


async def seed_demo_data(session: AsyncSession) -> dict[str, int]:
    """写入示例数据；返回各类对象的创建/更新数量，便于 CLI 输出。"""
    user = await _ensure_local_user(session)
    servers = await _ensure_servers(session)
    await session.commit()

    factory = HttpMcpClientFactory()
    try:
        await _discover_tools(session, servers, factory)
        tools = await _tool_ids_by_qualified_name(session)
        skills = await _ensure_skills(session, user, tools)
        await session.commit()
        await _ensure_agents(session, user, tools, skills)
        await session.commit()
        model_count = await _ensure_demo_model(session, user)
        await session.commit()
    finally:
        await factory.aclose()

    return {
        "servers": len(servers),
        "tools": len(tools),
        "skills": len(skills),
        "agents": len(AGENTS),
        "model_apis": model_count,
    }


async def _ensure_local_user(session: AsyncSession) -> AppUser:
    user = (
        await session.execute(select(AppUser).where(AppUser.email == LOCAL_USER_EMAIL))
    ).scalar_one_or_none()
    if user is None:
        user = AppUser(
            email=LOCAL_USER_EMAIL, display_name="Local", password_hash="!locked"
        )
        session.add(user)
        await session.flush()
        logger.info("创建 local 用户：%s", LOCAL_USER_EMAIL)
    return user


async def _ensure_servers(session: AsyncSession) -> list[McpServer]:
    servers: list[McpServer] = []
    for item in SERVERS:
        server = (
            await session.execute(
                select(McpServer).where(McpServer.name == item["name"])
            )
        ).scalar_one_or_none()
        if server is None:
            server = _touch(
                McpServer(
                    name=item["name"],
                    endpoint=item["endpoint"],
                    transport="streamable_http",
                    description=item["description"],
                    enabled=True,
                )
            )
            session.add(server)
            await session.flush()
            logger.info("创建 MCP Server：%s", item["name"])
        else:
            server.endpoint = item["endpoint"]
            server.description = item["description"]
            server.enabled = True
        servers.append(server)
    return servers


async def _discover_tools(
    session: AsyncSession,
    servers: list[McpServer],
    factory: HttpMcpClientFactory,
) -> None:
    discovery = DiscoveryService(
        registry_store=McpToolRepository(session),
        server_store=McpServerRepository(session),
        client_factory=factory,
    )
    repository = McpServerRepository(session)
    for server in servers:
        config = await repository.get_config(server.id)
        if config is None:  # pragma: no cover - 刚创建不会缺失
            continue
        try:
            await discovery.discover(config)
            await session.commit()
            logger.info("发现工具完成：%s", server.name)
        except McpDiscoveryError as exc:
            # Discovery 已把 status=ERROR 写入内存，提交后继续下一个
            await session.commit()
            logger.warning("MCP Server %s 工具发现失败：%s", server.name, exc.message)


async def _tool_ids_by_qualified_name(session: AsyncSession) -> dict[str, int]:
    from app.models.mcp import McpTool

    rows = (await session.execute(select(McpTool.qualified_name, McpTool.id))).all()
    return {name: tool_id for name, tool_id in rows}


async def _ensure_skills(
    session: AsyncSession, user: AppUser, tools: dict[str, int]
) -> dict[str, Skill]:
    skills: dict[str, Skill] = {}
    for item in SKILLS:
        skill = (
            await session.execute(
                select(Skill).where(
                    Skill.owner_id == user.id, Skill.slug == item["slug"]
                )
            )
        ).scalar_one_or_none()
        if skill is None:
            # 兼容历史数据：slug 不同但同名时复用，避免重复创建
            skill = (
                await session.execute(
                    select(Skill).where(
                        Skill.owner_id == user.id, Skill.name == item["name"]
                    )
                )
            ).scalar_one_or_none()

        if skill is None:
            skill = _touch(Skill(owner_id=user.id, slug=item["slug"]))
            session.add(skill)
            logger.info("创建 Skill：%s", item["name"])
        else:
            skill.slug = item["slug"]

        skill.name = item["name"]
        skill.summary = item["summary"]
        skill.category = item["category"]
        skill.icon = item["icon"]
        skill.version = "1.0.0"
        skill.visibility = "public"
        skill.status = "published"
        skill.instructions = item["instructions"]
        skill.input_schema = item["input_schema"]
        skill.tags = item["tags"]
        await session.flush()

        wanted = {
            binding["qualified_name"]: bool(binding.get("required", True))
            for binding in item["tools"]
        }
        existing = {
            row.tool_id: row
            for row in (
                await session.execute(
                    select(SkillTool).where(SkillTool.skill_id == skill.id)
                )
            ).scalars()
        }
        for qualified_name, required in wanted.items():
            tool_id = tools.get(qualified_name)
            if tool_id is None:
                logger.warning(
                    "Skill %s 依赖的工具不存在：%s（请先启动 MCP Server 后重跑）",
                    skill.name,
                    qualified_name,
                )
                continue
            row = existing.pop(tool_id, None)
            if row is None:
                session.add(
                    SkillTool(skill_id=skill.id, tool_id=tool_id, required=required)
                )
            else:
                row.required = required
        for row in existing.values():
            await session.delete(row)

        ensure_skill_dir(skill.id)
        skills[item["slug"]] = skill
    return skills


async def _ensure_agents(
    session: AsyncSession,
    user: AppUser,
    tools: dict[str, int],
    skills: dict[str, Skill],
) -> None:
    for item in AGENTS:
        agent = (
            await session.execute(
                select(Agent)
                .where(
                    Agent.name == item["name"],
                    Agent.deleted_at.is_(None),
                    # 历史数据 owner_id 可能为 NULL，复用而不是重复创建
                    or_(Agent.owner_id == user.id, Agent.owner_id.is_(None)),
                )
                .order_by(Agent.id)
            )
        ).scalars().first()
        if agent is None:
            agent = _touch(Agent(owner_id=user.id, name=item["name"], model=""))
            session.add(agent)
            logger.info("创建 Agent：%s", item["name"])
        else:
            agent.owner_id = user.id
        agent.description = item["description"]
        agent.model = ""
        agent.system_prompt = item["system_prompt"]
        agent.max_steps = item["max_steps"]
        agent.enabled = True
        await session.flush()

        await session.execute(delete(AgentTool).where(AgentTool.agent_id == agent.id))
        for qualified_name in item["tools"]:
            tool_id = tools.get(qualified_name)
            if tool_id is None:
                logger.warning(
                    "Agent %s 依赖的工具不存在：%s（请先启动 MCP Server 后重跑）",
                    item["name"],
                    qualified_name,
                )
                continue
            session.add(AgentTool(agent_id=agent.id, tool_id=tool_id))

        await session.execute(
            delete(AgentSkill).where(AgentSkill.agent_id == agent.id)
        )
        for binding in item["skills"]:
            skill = skills.get(binding["slug"])
            if skill is None:  # pragma: no cover - 上面已保证存在
                continue
            session.add(
                AgentSkill(
                    agent_id=agent.id,
                    skill_id=skill.id,
                    order_no=int(binding.get("order_no", 0)),
                    enabled=True,
                    params=dict(binding.get("params", {})),
                )
            )

        ensure_agent_dir(agent.id)


async def _ensure_demo_model(session: AsyncSession, user: AppUser) -> int:
    api = (
        await session.execute(
            select(ModelApi).where(
                ModelApi.owner_id == user.id, ModelApi.name == DEMO_MODEL["name"]
            )
        )
    ).scalar_one_or_none()

    if api is None:
        try:
            cipher = encrypt_secret(DEMO_MODEL["api_key"])
        except SecretDecryptError as exc:
            logger.warning("跳过 Model API 初始化：%s", exc)
            return 0
        has_default = (
            await session.execute(
                select(ModelApi.id).where(
                    ModelApi.owner_id == user.id, ModelApi.is_default.is_(True)
                )
            )
        ).first() is not None
        api = ModelApi(
            owner_id=user.id,
            name=DEMO_MODEL["name"],
            provider=DEMO_MODEL["provider"],
            base_url=DEMO_MODEL["base_url"],
            api_key_cipher=cipher,
            api_key_hint=f"-{DEMO_MODEL['api_key'][-3:]}",
            is_default=not has_default,
            enabled=True,
        )
        _touch(api)
        session.add(api)
        await session.flush()
        logger.info("创建 Model API：%s", DEMO_MODEL["name"])
    else:
        api.provider = DEMO_MODEL["provider"]
        api.base_url = DEMO_MODEL["base_url"]
        api.enabled = True

    model = (
        await session.execute(
            select(ModelApiModel).where(
                ModelApiModel.model_api_id == api.id,
                ModelApiModel.model_key == DEMO_MODEL["model_key"],
            )
        )
    ).scalar_one_or_none()
    if model is None:
        has_default_model = (
            await session.execute(
                select(ModelApiModel.id).where(
                    ModelApiModel.model_api_id == api.id,
                    ModelApiModel.is_default.is_(True),
                )
            )
        ).first() is not None
        session.add(
            _touch(
                ModelApiModel(
                    model_api_id=api.id,
                    model_key=DEMO_MODEL["model_key"],
                    display_name=DEMO_MODEL["display_name"],
                    capabilities=DEMO_MODEL["capabilities"],
                    enabled=True,
                    is_default=not has_default_model,
                )
            )
        )
    else:
        model.display_name = DEMO_MODEL["display_name"]
        model.capabilities = DEMO_MODEL["capabilities"]
        model.enabled = True
    return 1


async def _run() -> None:
    await create_schema()
    async with SessionFactory() as session:
        summary = await seed_demo_data(session)
    await engine.dispose()
    logger.info("示例数据初始化完成：%s", summary)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    asyncio.run(_run())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
