"""Tests for the minimum Django i18n contract."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PLATFORM_ROOT.parents[1]
ENTRYPOINT = PLATFORM_ROOT / "entrypoint.sh"
DOCKERFILE = PLATFORM_ROOT / "Dockerfile"
TEMPLATE_ROOTS = (
    PLATFORM_ROOT / "templates",
    PLATFORM_ROOT / "cms" / "experiments" / "templates",
)


def test_locale_middleware_keeps_django_required_ordering():
    middleware = list(settings.MIDDLEWARE)

    locale_index = middleware.index("django.middleware.locale.LocaleMiddleware")

    assert middleware.index("django.contrib.sessions.middleware.SessionMiddleware") < locale_index
    assert locale_index < middleware.index("django.middleware.common.CommonMiddleware")


def test_locale_paths_uses_platform_locale_directory():
    assert settings.LOCALE_PATHS == [PLATFORM_ROOT / "locale"]


def test_image_build_compiles_messages_before_collectstatic():
    dockerfile = DOCKERFILE.read_text()

    compile_index = dockerfile.index("python manage.py compilemessages")
    collectstatic_index = dockerfile.index("python manage.py collectstatic --noinput")

    assert compile_index < collectstatic_index


def test_entrypoint_does_not_build_static_artifacts_at_runtime():
    entrypoint = ENTRYPOINT.read_text()

    assert "python manage.py compilemessages" not in entrypoint
    assert "python manage.py collectstatic --noinput" not in entrypoint


def test_user_facing_templates_use_translation_tags():
    untranslated_templates: list[str] = []

    for template_root in TEMPLATE_ROOTS:
        for template_path in sorted(template_root.rglob("*.html")):
            relative_path = template_path.relative_to(REPO_ROOT).as_posix()
            content = template_path.read_text()
            if _has_user_facing_literal(content) or (_uses_translation_tags(content) and not _loads_i18n(content)):
                untranslated_templates.append(relative_path)

    assert untranslated_templates == []


def _loads_i18n(content: str) -> bool:
    return bool(re.search(r"{%\s*load\s+[^%]*\bi18n\b", content))


def _uses_translation_tags(content: str) -> bool:
    return bool(re.search(r"{%\s*(trans|blocktrans)\b", content))


def _has_user_facing_literal(content: str) -> bool:
    stripped = _strip_ignored_blocks(content)
    return _has_visible_text_node(stripped) or _has_translatable_attribute(stripped)


def _strip_ignored_blocks(content: str) -> str:
    stripped = re.sub(r"{#.*?#}", "", content, flags=re.DOTALL)
    stripped = re.sub(r"<!--.*?-->", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"<(script|style)\b.*?</\1>", "", stripped, flags=re.DOTALL | re.IGNORECASE)
    stripped = re.sub(r"{%\s*(trans|blocktrans)\b.*?%}.*?{%\s*endblocktrans\s*%}", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"{%\s*trans\b.*?%}", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"{%.*?%}", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"{{.*?}}", "", stripped, flags=re.DOTALL)
    return stripped


def _has_visible_text_node(content: str) -> bool:
    for text in re.findall(r">([^<>{%][^<]*)<", content):
        normalized = re.sub(r"\s+", " ", text).strip()
        if normalized and re.search(r"[A-Za-z]", normalized):
            return True
    return False


def _has_translatable_attribute(content: str) -> bool:
    pattern = re.compile(r"\b(?:aria-label|placeholder|title|alt|value)=([\"'])(.*?)\1", re.DOTALL)
    for _, value in pattern.findall(content):
        normalized = re.sub(r"\s+", " ", value).strip()
        if (
            normalized
            and normalized.lower() not in {"true", "false"}
            and "<" not in normalized
            and ">" not in normalized
            and re.search(r"[A-Za-z]", normalized)
            and "{{" not in normalized
            and "{%" not in normalized
        ):
            return True
    return False
