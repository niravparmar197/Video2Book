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
