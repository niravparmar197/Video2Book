import inspect

from api import ai_llm_bridge


def test_get_progress_is_importable_and_callable():
    assert callable(ai_llm_bridge.get_progress)
    assert list(inspect.signature(ai_llm_bridge.get_progress).parameters) == [
        "output_dir",
        "checkpointer",
        "book_order",
        "phase",
    ]


def test_get_chapter_progress_is_importable_and_callable():
    assert callable(ai_llm_bridge.get_chapter_progress)
    assert list(inspect.signature(ai_llm_bridge.get_chapter_progress).parameters) == [
        "output_dir",
    ]


def test_get_warnings_is_importable_and_callable():
    assert callable(ai_llm_bridge.get_warnings)
    assert list(inspect.signature(ai_llm_bridge.get_warnings).parameters) == [
        "output_dir",
    ]


def test_estimate_playlist_is_importable_and_callable():
    assert callable(ai_llm_bridge.estimate_playlist)
    assert list(inspect.signature(ai_llm_bridge.estimate_playlist).parameters) == [
        "url",
        "chunk_minutes",
    ]


def test_load_settings_is_a_pass_through_to_ai_llms_own_settings():
    assert callable(ai_llm_bridge.load_settings)

    import app.config as ai_llm_config

    bridged = ai_llm_bridge.load_settings()
    direct = ai_llm_config.load_settings()

    assert bridged.max_book_hours == direct.max_book_hours
    assert bridged.max_book_cost_usd == direct.max_book_cost_usd
