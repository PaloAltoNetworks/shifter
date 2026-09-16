"""Unit tests for the challenge-list filter-link URL builder.

Covers ``_build_challenge_filter_links`` / ``_filter_query`` in
``ctf.views.participant_challenges`` across every filter combination so the
relative tag/topic URLs, the two "All" URLs, and the active flags are correct.
"""

from __future__ import annotations

from types import SimpleNamespace

from ctf.views.participant_challenges import _build_challenge_filter_links, _filter_query


def _named(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def test_filter_query_drops_empty_and_prefixes() -> None:
    assert _filter_query() == ""
    assert _filter_query(("a", None), ("b", "")) == ""
    assert _filter_query(("tag", "web"), ("category", None)) == "?tag=web"
    assert _filter_query(("category", "misc"), ("tag", "web")) == "?category=misc&tag=web"


def test_no_filters() -> None:
    result = _build_challenge_filter_links(
        [_named("web")], [_named("crypto")], category_filter=None, tag_filter=None, topic_filter=None
    )
    assert result["tags_all_url"] == ""
    assert result["tag_filters"] == [{"name": "web", "url": "?tag=web", "active": False}]
    assert result["topics_all_url"] == ""
    assert result["topic_filters"] == [{"name": "crypto", "url": "?topic=crypto", "active": False}]


def test_category_filter_threads_into_every_url() -> None:
    result = _build_challenge_filter_links(
        [_named("web")], [_named("crypto")], category_filter="misc", tag_filter=None, topic_filter=None
    )
    assert result["tags_all_url"] == "?category=misc"
    assert result["tag_filters"][0]["url"] == "?tag=web&category=misc"
    assert result["topics_all_url"] == "?category=misc"
    assert result["topic_filters"][0]["url"] == "?topic=crypto&category=misc"


def test_tag_and_topic_active_flags_and_combined_query() -> None:
    result = _build_challenge_filter_links(
        [_named("web")], [_named("crypto")], category_filter="misc", tag_filter="web", topic_filter="crypto"
    )
    assert result["tag_filters"][0]["active"] is True
    assert result["topics_all_url"] == "?category=misc&tag=web"
    assert result["topic_filters"][0]["url"] == "?topic=crypto&category=misc&tag=web"
    assert result["topic_filters"][0]["active"] is True


def test_tag_filter_only_threads_into_topic_urls() -> None:
    result = _build_challenge_filter_links(
        [], [_named("crypto")], category_filter=None, tag_filter="web", topic_filter=None
    )
    assert result["tag_filters"] == []
    assert result["topics_all_url"] == "?tag=web"
    assert result["topic_filters"][0]["url"] == "?topic=crypto&tag=web"


def test_urlencodes_special_characters() -> None:
    result = _build_challenge_filter_links(
        [_named("a b&c")], [], category_filter=None, tag_filter=None, topic_filter=None
    )
    assert result["tag_filters"][0]["url"] == "?tag=a+b%26c"
