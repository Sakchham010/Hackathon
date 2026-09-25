from cursor_model_router.common.ids import new_id, stable_event_key


def test_stable_event_key_is_deterministic():
    assert stable_event_key("a", "b", "c") == stable_event_key("a", "b", "c")


def test_stable_event_key_distinguishes_boundary_shifts():
    assert stable_event_key("ab", "c") != stable_event_key("a", "bc")


def test_stable_event_key_distinguishes_order():
    assert stable_event_key("a", "b") != stable_event_key("b", "a")


def test_new_id_is_unique_and_string():
    first, second = new_id(), new_id()
    assert isinstance(first, str)
    assert first != second
