"""Skill 参数契约纯函数单测：slug、JSON Schema 解析、params 校验。"""

from __future__ import annotations

import pytest

from app.agent.skills import SkillValidationError
from app.services.skill_service import parameters_from_schema, slugify, validate_params


def test_slugify_normalizes_ascii_names() -> None:
    assert slugify("Weekly Report") == "weekly-report"
    assert slugify("  Code-Review v2  ") == "code-review-v2"


def test_slugify_returns_empty_for_non_ascii_names() -> None:
    assert slugify("周报生成") == ""


def test_empty_schema_means_no_parameters() -> None:
    assert parameters_from_schema(None) == []
    assert parameters_from_schema({}) == []


def test_schema_is_parsed_with_required_and_defaults() -> None:
    parameters = parameters_from_schema(
        {
            "type": "object",
            "properties": {
                "tone": {
                    "type": "string",
                    "description": "输出语气",
                    "default": "正式",
                },
                "count": {"type": "integer"},
                "verbose": {"type": "boolean"},
            },
            "required": ["count"],
        }
    )

    by_name = {param.name: param for param in parameters}
    assert by_name["tone"].required is False
    assert by_name["tone"].default == "正式"
    assert by_name["tone"].description == "输出语气"
    assert by_name["count"].required is True
    assert by_name["count"].type == "number"
    assert by_name["verbose"].type == "boolean"


def test_unsupported_schema_type_is_rejected() -> None:
    with pytest.raises(SkillValidationError) as info:
        parameters_from_schema(
            {"type": "object", "properties": {"tags": {"type": "array"}}}
        )

    assert info.value.code == "SKILL_INVALID_PARAMS"
    assert "tags" in info.value.message


def test_schema_must_be_object() -> None:
    with pytest.raises(SkillValidationError):
        parameters_from_schema({"type": "array"})


def test_required_list_must_be_strings() -> None:
    with pytest.raises(SkillValidationError):
        parameters_from_schema(
            {"type": "object", "properties": {"tone": {"type": "string"}}, "required": [1]}
        )


def test_validate_params_accepts_defaults_and_coercions() -> None:
    parameters = parameters_from_schema(
        {
            "type": "object",
            "properties": {
                "tone": {"type": "string", "default": "正式"},
                "count": {"type": "number"},
                "verbose": {"type": "boolean"},
            },
            "required": ["count"],
        }
    )

    validate_params(parameters, {"count": "3", "verbose": "true"})
    validate_params(parameters, {"count": 2, "verbose": True, "tone": "轻松"})


def test_validate_params_reports_missing_required() -> None:
    parameters = parameters_from_schema(
        {"type": "object", "properties": {"tone": {"type": "string"}}, "required": ["tone"]}
    )

    with pytest.raises(SkillValidationError) as info:
        validate_params(parameters, {})

    assert info.value.code == "SKILL_INVALID_PARAMS"
    assert info.value.param == "tone"


def test_validate_params_rejects_wrong_types() -> None:
    parameters = parameters_from_schema(
        {
            "type": "object",
            "properties": {"count": {"type": "number"}, "flag": {"type": "boolean"}},
        }
    )

    with pytest.raises(SkillValidationError):
        validate_params(parameters, {"count": "not-a-number"})
    with pytest.raises(SkillValidationError):
        validate_params(parameters, {"flag": "yes"})
    with pytest.raises(SkillValidationError):
        validate_params(parameters, {"count": True})


def test_validate_params_ignores_unknown_keys() -> None:
    parameters = parameters_from_schema(
        {"type": "object", "properties": {"tone": {"type": "string"}}}
    )

    validate_params(parameters, {"tone": "正式", "future_option": 1})
