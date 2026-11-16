"""Skill 领域纯函数：slug 生成、JSON Schema 子集解析、参数校验。

归属：D（Platform Backend）+ B（工具侧契约）。不访问数据库，便于单测与复用：

- 创建 / 更新 Skill 时把 `input_schema` 解析为 `SkillParameter` 列表并校验；
- 挂载到 Agent 时用 `validate_params` 提前发现必填缺失（运行前校验，对应 US-M2-6）；
- Runtime 侧由 `SkillResolver` 再做一次渲染与校验，两层语义一致。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.agent.skills import SkillParameter, SkillValidationError

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_SLUG_MAX = 80

_TYPE_MAP = {
    "string": "string",
    "number": "number",
    "integer": "number",
    "boolean": "boolean",
}


def slugify(value: str) -> str:
    """把名称转换为 `skill.slug` 允许的形态；无法转换时返回空串，由调用方兜底。"""
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _NON_SLUG.sub("-", ascii_only).strip("-")
    return slug[:_SLUG_MAX].strip("-")


def parameters_from_schema(schema: dict[str, Any] | None) -> list[SkillParameter]:
    """把 JSON Schema 子集解析为运行期参数契约。

    支持的字段：`type`（object）、`properties`（string/number/integer/boolean）、
    `required`、每个属性的 `description` 与 `default`。其余关键字忽略，不符合约定时
    抛 `SKILL_INVALID_PARAMS`。
    """
    if not schema:
        return []
    if not isinstance(schema, dict):
        raise _invalid("input_schema 必须是 JSON 对象")

    schema_type = schema.get("type", "object")
    if schema_type != "object":
        raise _invalid("input_schema.type 只支持 object")

    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        raise _invalid("input_schema.properties 必须是对象")

    required = schema.get("required") or []
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise _invalid("input_schema.required 必须是字符串数组")
    required_names = set(required)

    parameters: list[SkillParameter] = []
    for name, spec in properties.items():
        if not isinstance(name, str) or not name:
            raise _invalid("input_schema.properties 的键必须是非空字符串")
        if not isinstance(spec, dict):
            raise _invalid(f"参数 {name} 的 schema 必须是对象")

        raw_type = spec.get("type", "string")
        if raw_type not in _TYPE_MAP:
            raise _invalid(f"参数 {name} 的类型 {raw_type!r} 不受支持（仅 string/number/boolean）")

        parameters.append(
            SkillParameter(
                name=name,
                description=str(spec.get("description") or ""),
                type=_TYPE_MAP[raw_type],  # type: ignore[arg-type]
                required=name in required_names,
                default=spec.get("default"),
            )
        )
    return parameters


def validate_params(
    parameters: list[SkillParameter],
    values: dict[str, Any] | None,
) -> None:
    """校验一组 `params` 是否满足 Skill 参数契约（只校验，不渲染）。"""
    provided = values or {}
    if not isinstance(provided, dict):
        raise _invalid("params 必须是 JSON 对象")

    # 未知参数只忽略：允许用户保留未来版本的参数，不阻断运行
    for param in parameters:
        if param.name in provided:
            _coerce(param, provided[param.name])
        elif param.default is not None:
            _coerce(param, param.default)
        elif param.required:
            raise _invalid(f"缺少必填参数：{param.name}", param=param.name)


def _coerce(param: SkillParameter, value: Any) -> Any:
    if param.type == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            raise _invalid(f"参数 {param.name} 不是合法的 string", param=param.name)
        return str(value)
    if param.type == "number":
        if isinstance(value, bool):
            raise _invalid(f"参数 {param.name} 不是合法的 number", param=param.name)
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            raise _invalid(f"参数 {param.name} 不是合法的 number", param=param.name) from None
    if param.type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise _invalid(f"参数 {param.name} 不是合法的 boolean", param=param.name)
    raise _invalid(f"参数 {param.name} 的类型不受支持", param=param.name)


def _invalid(message: str, *, param: str | None = None) -> SkillValidationError:
    return SkillValidationError("SKILL_INVALID_PARAMS", message, param=param)
