from app.agents.workload import (
    interactive_model_call_pending,
    prioritize_interactive_model_call,
)


def test_interactive_priority_supports_nested_requests() -> None:
    assert not interactive_model_call_pending()

    with prioritize_interactive_model_call():
        assert interactive_model_call_pending()
        with prioritize_interactive_model_call():
            assert interactive_model_call_pending()
        assert interactive_model_call_pending()

    assert not interactive_model_call_pending()


def test_interactive_priority_is_released_after_error() -> None:
    try:
        with prioritize_interactive_model_call():
            raise RuntimeError("model hatası")
    except RuntimeError:
        pass

    assert not interactive_model_call_pending()
