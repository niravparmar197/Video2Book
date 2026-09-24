from langgraph.checkpoint.base import empty_checkpoint

from api import checkpointer


def test_ensure_checkpoint_tables_is_idempotent():
    checkpointer.ensure_checkpoint_tables()
    checkpointer.ensure_checkpoint_tables()


def test_get_checkpointer_put_get_tuple_round_trips():
    checkpointer.ensure_checkpoint_tables()
    saver = checkpointer.get_checkpointer()

    config = {"configurable": {"thread_id": "test-thread-round-trip", "checkpoint_ns": ""}}
    checkpoint = empty_checkpoint()
    saver.put(config, checkpoint, {"source": "input", "step": -1, "writes": {}}, {})

    tuple_ = saver.get_tuple(config)

    assert tuple_ is not None
    assert tuple_.checkpoint["id"] == checkpoint["id"]
