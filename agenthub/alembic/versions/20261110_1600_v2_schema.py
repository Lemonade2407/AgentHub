"""v2 schema: auth / model api / skill / agent center

Revision ID: 0002_v2_schema
Revises: 0001_initial_schema
Create Date: 2026-11-10 16:00:00

修改意见文档 §3.2 / §4.3 / §5.3（DB 设计文档 v2.0）：

- 新增 9 张表：app_user、model_api、model_api_model、skill、skill_tool、
  agent_skill、agent_publication、publication_like、publication_install；
- `agent` 表新增 owner_id / model_api_id / model_key 与按 owner 过滤的列表索引；
- `agent_step.event_type` CHECK 扩充 V2 事件 SKILL_INJECTED / SKILL_TOOL_MISSING；
- 回填（幂等）：内置 local 用户 → agent.owner_id；按 V1 `provider/model` 拆分为
  每个 provider 建「系统迁移」Model API（密钥取原环境变量，Fernet 加密后写入）→
  agent.model_api_id / model_key。缺少 SECRET_KEY 或 API Key 时跳过 Model API 回填，
  历史 Agent 保持 legacy（model_api_id=NULL）路径，迁移本身不失败。

加密说明：Fernet 派生算法（SHA-256 → urlsafe-b64）内嵌于本迁移，与
`app/core/crypto.py` 保持一致；迁移不 import 应用代码，保证长期可重放。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "0002_v2_schema"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# 内置 local 用户：local 模式（未登录演示）下所有资源的归属
LOCAL_USER_EMAIL = "local@agenthub.local"

# provider -> (默认 base_url, 专用 API Key 环境变量)；与 V1 model_provider 一致
_PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
}


def upgrade() -> None:
    # ---------- app_user ----------
    op.create_table(
        "app_user",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("email", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        sa.UniqueConstraint("email", name="uq_app_user_email"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="status"),
        comment="平台账号（V2 最小账号体系）",
    )

    # ---------- model_api ----------
    op.create_table(
        "model_api",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("api_key_cipher", sa.Text(), nullable=False, comment="Fernet 密文，禁止明文入库、禁止回显"),
        sa.Column("api_key_hint", sa.String(length=16), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_model_api"),
        sa.ForeignKeyConstraint(["owner_id"], ["app_user.id"], name="fk_model_api_owner_id", ondelete="CASCADE"),
        sa.UniqueConstraint("owner_id", "name", name="uq_model_api_owner_id_name"),
        sa.CheckConstraint("provider IN ('deepseek', 'openai', 'qwen', 'custom')", name="provider"),
        comment="用户级模型接入配置（V2）",
    )
    op.create_index("idx_model_api_owner_id", "model_api", ["owner_id"], unique=False)
    op.create_index(
        "uq_model_api_owner_default",
        "model_api",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    # ---------- model_api_model ----------
    op.create_table(
        "model_api_model",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("model_api_id", sa.BigInteger(), nullable=False),
        sa.Column("model_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("capabilities", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_model_api_model"),
        sa.ForeignKeyConstraint(["model_api_id"], ["model_api.id"], name="fk_model_api_model_model_api_id", ondelete="CASCADE"),
        sa.UniqueConstraint("model_api_id", "model_key", name="uq_model_api_model_model_api_id_model_key"),
        comment="Model API 下的可用模型清单（V2）",
    )
    op.create_index(
        "uq_model_api_model_default",
        "model_api_model",
        ["model_api_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    # ---------- skill ----------
    op.create_table(
        "skill",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("summary", sa.String(length=512), server_default="", nullable=False),
        sa.Column("category", sa.String(length=32), server_default="general", nullable=False),
        sa.Column("icon", sa.String(length=64), nullable=True),
        sa.Column("version", sa.String(length=16), server_default="1.0.0", nullable=False),
        sa.Column("visibility", sa.String(length=16), server_default="private", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("instructions", sa.Text(), server_default="", nullable=False),
        sa.Column("input_schema", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("tags", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("install_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("like_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_skill"),
        sa.ForeignKeyConstraint(["owner_id"], ["app_user.id"], name="fk_skill_owner_id", ondelete="CASCADE"),
        sa.UniqueConstraint("owner_id", "slug", name="uq_skill_owner_id_slug"),
        sa.CheckConstraint("visibility IN ('private', 'public')", name="visibility"),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="status"),
        sa.CheckConstraint("category IN ('general', 'writing', 'coding', 'data', 'research', 'ops')", name="category"),
        sa.CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]*$'", name="slug_format"),
        comment="可复用能力包：指令片段 + 工具集合 + 参数契约（V2）",
    )
    op.create_index("idx_skill_public", "skill", ["status", "visibility", "category"], unique=False)
    op.create_index("idx_skill_owner_id", "skill", ["owner_id"], unique=False)

    # ---------- skill_tool ----------
    op.create_table(
        "skill_tool",
        sa.Column("skill_id", sa.BigInteger(), nullable=False),
        sa.Column("tool_id", sa.BigInteger(), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("skill_id", "tool_id", name="pk_skill_tool"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], name="fk_skill_tool_skill_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_id"], ["mcp_tool.id"], name="fk_skill_tool_tool_id", ondelete="CASCADE"),
        comment="Skill 与 MCP Tool 的绑定关系（V2）",
    )
    op.create_index("idx_skill_tool_tool_id", "skill_tool", ["tool_id"], unique=False)

    # ---------- agent_skill ----------
    op.create_table(
        "agent_skill",
        sa.Column("agent_id", sa.BigInteger(), nullable=False),
        sa.Column("skill_id", sa.BigInteger(), nullable=False),
        sa.Column("order_no", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("params", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.PrimaryKeyConstraint("agent_id", "skill_id", name="pk_agent_skill"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_agent_skill_agent_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], name="fk_agent_skill_skill_id", ondelete="RESTRICT"),
        comment="Agent 与 Skill 的挂载关系（V2）",
    )
    op.create_index("idx_agent_skill_skill_id", "agent_skill", ["skill_id"], unique=False)

    # ---------- agent_publication ----------
    op.create_table(
        "agent_publication",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("source_agent_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=512), server_default="", nullable=False),
        sa.Column("category", sa.String(length=32), server_default="general", nullable=False),
        sa.Column("version", sa.String(length=16), server_default="1.0.0", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="published", nullable=False),
        sa.Column("snapshot", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment="脱敏后的不可变发布快照，禁止包含密钥 / headers / owner_id"),
        sa.Column("install_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("like_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agent_publication"),
        sa.ForeignKeyConstraint(["owner_id"], ["app_user.id"], name="fk_agent_publication_owner_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_agent_id"], ["agent.id"], name="fk_agent_publication_source_agent_id", ondelete="SET NULL"),
        sa.UniqueConstraint("owner_id", "source_agent_id", "version", name="uq_agent_publication_owner_id_source_agent_id_version"),
        sa.CheckConstraint("status IN ('draft', 'published', 'offline')", name="status"),
        sa.CheckConstraint("category IN ('general', 'writing', 'coding', 'data', 'research', 'ops')", name="category"),
        comment="Agent 发布快照（V2 Agent Center）",
    )
    op.create_index(
        "idx_publication_feed",
        "agent_publication",
        ["status", "category", sa.text("published_at DESC")],
        unique=False,
    )
    op.create_index("idx_agent_publication_owner_id", "agent_publication", ["owner_id"], unique=False)

    # ---------- publication_like ----------
    op.create_table(
        "publication_like",
        sa.Column("publication_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("publication_id", "user_id", name="pk_publication_like"),
        sa.ForeignKeyConstraint(["publication_id"], ["agent_publication.id"], name="fk_publication_like_publication_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], name="fk_publication_like_user_id", ondelete="CASCADE"),
        comment="Publication 点赞关系（V2）",
    )
    op.create_index("idx_publication_like_user_id", "publication_like", ["user_id"], unique=False)

    # ---------- publication_install ----------
    op.create_table(
        "publication_install",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("publication_id", sa.BigInteger(), nullable=False),
        sa.Column("installer_id", sa.BigInteger(), nullable=False),
        sa.Column("installed_agent_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publication_install"),
        sa.ForeignKeyConstraint(["publication_id"], ["agent_publication.id"], name="fk_publication_install_publication_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["installer_id"], ["app_user.id"], name="fk_publication_install_installer_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["installed_agent_id"], ["agent.id"], name="fk_publication_install_installed_agent_id", ondelete="SET NULL"),
        sa.UniqueConstraint("publication_id", "installer_id", name="uq_publication_install_publication_id_installer_id"),
        comment="Publication 安装记录（V2）",
    )
    op.create_index("idx_publication_install_installer_id", "publication_install", ["installer_id"], unique=False)

    # ---------- agent 表变更（修改意见 §3.2）----------
    op.add_column("agent", sa.Column("owner_id", sa.BigInteger(), nullable=True))
    op.add_column("agent", sa.Column("model_api_id", sa.BigInteger(), nullable=True))
    op.add_column("agent", sa.Column("model_key", sa.String(length=128), nullable=True))
    op.create_foreign_key(
        "fk_agent_owner_id", "agent", "app_user", ["owner_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_agent_model_api_id",
        "agent",
        "model_api",
        ["model_api_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "idx_agent_owner_created_active",
        "agent",
        ["owner_id", sa.text("created_at DESC")],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ---------- agent_step.event_type CHECK 扩充 V2 事件 ----------
    # 短名 event_type 会经 naming_convention 展开为 ck_agent_step_event_type
    op.drop_constraint("event_type", "agent_step", type_="check")
    op.create_check_constraint(
        "event_type",
        "agent_step",
        "event_type IN ('RUN_STARTED', 'LLM_STARTED', 'LLM_FINISHED', "
        "'TOOL_CANDIDATES', 'SKILL_INJECTED', 'SKILL_TOOL_MISSING', "
        "'TOOL_CALL_STARTED', 'TOOL_CALL_FINISHED', 'STATE_UPDATED', "
        "'RUN_FINISHED', 'RUN_FAILED')",
    )

    # ---------- V1 数据回填（幂等）----------
    _backfill()


def downgrade() -> None:
    # 恢复 agent_step CHECK 为 V1 的 9 种事件
    op.drop_constraint("event_type", "agent_step", type_="check")
    op.create_check_constraint(
        "event_type",
        "agent_step",
        "event_type IN ('RUN_STARTED', 'LLM_STARTED', 'LLM_FINISHED', "
        "'TOOL_CANDIDATES', 'TOOL_CALL_STARTED', 'TOOL_CALL_FINISHED', "
        "'STATE_UPDATED', 'RUN_FINISHED', 'RUN_FAILED')",
    )

    # agent 表变更回滚（列上的数据随列一并消失）
    op.drop_index("idx_agent_owner_created_active", table_name="agent")
    op.drop_constraint("fk_agent_model_api_id", "agent", type_="foreignkey")
    op.drop_constraint("fk_agent_owner_id", "agent", type_="foreignkey")
    op.drop_column("agent", "model_key")
    op.drop_column("agent", "model_api_id")
    op.drop_column("agent", "owner_id")

    # 反向依赖顺序 drop 新表
    op.drop_table("publication_install")
    op.drop_table("publication_like")
    op.drop_table("agent_publication")
    op.drop_table("agent_skill")
    op.drop_table("skill_tool")
    op.drop_table("skill")
    op.drop_table("model_api_model")
    op.drop_table("model_api")
    op.drop_table("app_user")


# ---------------------------------------------------------------------------
# 回填（修改意见 §3.2「回填规则」）
# ---------------------------------------------------------------------------


def _fernet_encrypt(plaintext: str, secret_key: str) -> str:
    """与 app/core/crypto.py 相同的派生：SHA-256 → urlsafe-b64 → Fernet。

    内嵌实现而不 import 应用代码：迁移必须在未来代码演进后仍可重放。
    """
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
    fernet = Fernet(base64.urlsafe_b64encode(digest))
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def _backfill() -> None:
    # 离线模式（alembic upgrade --sql）只生成 DDL，无真实连接，跳过数据回填
    if context.is_offline_mode():
        return
    conn = op.get_bind()

    # 1) 内置 local 用户（幂等）
    conn.execute(
        sa.text(
            "INSERT INTO app_user (email, display_name, password_hash, status) "
            "VALUES (:email, :name, '!locked', 'active') "
            "ON CONFLICT (email) DO NOTHING"
        ),
        {"email": LOCAL_USER_EMAIL, "name": "Local"},
    )
    local_user_id: int = conn.execute(
        sa.text("SELECT id FROM app_user WHERE email = :email"),
        {"email": LOCAL_USER_EMAIL},
    ).scalar_one()

    # 2) owner_id 统一回填为 local 用户
    conn.execute(
        sa.text("UPDATE agent SET owner_id = :uid WHERE owner_id IS NULL"),
        {"uid": local_user_id},
    )

    # 3) 按 V1 model 字符串拆分回填 model_api / model_key
    secret_key = os.getenv("SECRET_KEY", "")
    rows = (
        conn.execute(sa.text("SELECT DISTINCT model FROM agent")).mappings().all()
    )
    if not rows:
        return

    if not secret_key:
        logger.warning(
            "0002_v2_schema: 缺少 SECRET_KEY，跳过 Model API 回填；"
            "历史 Agent 保持 legacy 环境变量路径（model_api_id 为 NULL）"
        )
        return

    # provider -> model_api id（本次迁移创建）
    model_api_ids: dict[str, int] = {}
    for row in rows:
        provider, sep, model_key = (row["model"] or "").partition("/")
        if not sep or not provider or not model_key:
            continue
        if provider not in _PROVIDER_DEFAULTS:
            provider = "custom"
        if provider in model_api_ids:
            continue

        default_base_url, api_key_env = _PROVIDER_DEFAULTS.get(provider, ("", ""))
        base_url = os.getenv("LLM_BASE_URL") or default_base_url
        api_key = os.getenv("LLM_API_KEY") or (os.getenv(api_key_env) if api_key_env else None)
        if not base_url or not api_key:
            logger.warning(
                "0002_v2_schema: provider %r 缺少 base_url 或 API Key，跳过；"
                "相关 Agent 保持 legacy 路径",
                provider,
            )
            continue

        # 幂等：同一迁移不会因 ON CONFLICT 重复执行，这里防御已人工建过同名记录的场景
        existing = conn.execute(
            sa.text(
                "SELECT id FROM model_api WHERE owner_id = :uid AND name = :name"
            ),
            {"uid": local_user_id, "name": f"迁移导入-{provider}"},
        ).scalar_one_or_none()
        if existing is not None:
            model_api_ids[provider] = existing
            continue

        cipher = _fernet_encrypt(api_key, secret_key)
        hint = api_key[-4:] if len(api_key) >= 4 else api_key
        model_api_id = conn.execute(
            sa.text(
                "INSERT INTO model_api (owner_id, name, provider, base_url, "
                "api_key_cipher, api_key_hint, is_default, enabled) "
                "VALUES (:uid, :name, :provider, :base_url, :cipher, :hint, "
                "false, true) RETURNING id"
            ),
            {
                "uid": local_user_id,
                "name": f"迁移导入-{provider}",
                "provider": provider,
                "base_url": base_url,
                "cipher": cipher,
                "hint": hint,
            },
        ).scalar_one()
        model_api_ids[provider] = model_api_id

    # 4) 逐条回填 agent.model_api_id / model_key，并维护 model_api_model 清单
    for row in rows:
        raw_provider, sep, model_key = (row["model"] or "").partition("/")
        if not sep or not raw_provider or not model_key:
            continue
        provider = raw_provider if raw_provider in _PROVIDER_DEFAULTS else "custom"
        model_api_id = model_api_ids.get(provider)
        if model_api_id is None:
            continue

        conn.execute(
            sa.text(
                "INSERT INTO model_api_model (model_api_id, model_key, display_name, "
                "capabilities, enabled, is_default) "
                "VALUES (:mid, :key, :key, "
                "'{\"tool_call\": true}'::jsonb, true, false) "
                "ON CONFLICT ON CONSTRAINT "
                "uq_model_api_model_model_api_id_model_key DO NOTHING"
            ),
            {"mid": model_api_id, "key": model_key},
        )
        conn.execute(
            sa.text(
                "UPDATE agent SET model_api_id = :mid, model_key = :key "
                "WHERE model = :model AND model_api_id IS NULL"
            ),
            {"mid": model_api_id, "key": model_key, "model": row["model"]},
        )

    # 5) 每个迁移 Model API 的第一个模型置为默认（该 API 下原本无任何默认）
    for model_api_id in model_api_ids.values():
        conn.execute(
            sa.text(
                "UPDATE model_api_model SET is_default = true "
                "WHERE id = ("
                "  SELECT id FROM model_api_model "
                "  WHERE model_api_id = :mid ORDER BY id LIMIT 1"
                ")"
            ),
            {"mid": model_api_id},
        )
