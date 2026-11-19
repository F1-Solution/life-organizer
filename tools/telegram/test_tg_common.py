# Run with: uv run --with pytest pytest tools/telegram -q
import pytest

from tg_common import extract_urls, load_config, parse_env, pick_by_name, slugify


def test_parse_env_skips_comments_and_strips_quotes():
    text = '# comment\nTG_API_ID=123\nTG_API_HASH="abc"\n\nnoequals\n'
    assert parse_env(text) == {"TG_API_ID": "123", "TG_API_HASH": "abc"}


def test_load_config_reads_env_and_builds_session_path(tmp_path):
    (tmp_path / ".env").write_text("TG_API_ID=42\nTG_API_HASH=h\n", encoding="utf-8")
    cfg = load_config(tmp_path)
    assert (cfg.api_id, cfg.api_hash, cfg.session) == (42, "h", tmp_path / "reader.session")


def test_load_config_explains_missing_or_bad_env(tmp_path):
    with pytest.raises(SystemExit, match="Missing"):
        load_config(tmp_path)
    (tmp_path / ".env").write_text("TG_API_ID=notanumber\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="numeric"):
        load_config(tmp_path)


def test_slugify_keeps_it_filesystem_safe():
    assert slugify("Ricette & Link!", 77) == "ricette-link-77"
    assert slugify("   ", 5) == "chat-5"


def test_extract_urls_dedupes_and_trims_punctuation():
    text = "vedi https://a.it/x. e (https://b.com/y) poi https://a.it/x"
    assert extract_urls(text) == ["https://a.it/x", "https://b.com/y"]
    assert extract_urls(None) == []


def test_pick_by_name_prefers_exact_then_unique_substring():
    names = {1: "Famiglia", 2: "Famiglia allargata", 3: "Lavoro"}
    assert pick_by_name(names, "famiglia") == 1
    assert pick_by_name(names, "lav") == 3


def test_pick_by_name_reports_ambiguity_and_absence():
    names = {1: "Gruppo A", 2: "Gruppo B"}
    with pytest.raises(SystemExit, match="several"):
        pick_by_name(names, "gruppo")
    with pytest.raises(SystemExit, match="No chat"):
        pick_by_name(names, "zzz")
