from cursor_model_router.common.config import RepositoryFilterConfig
from cursor_model_router.common.pathing import normalize_path
from cursor_model_router.common.repo_filter import is_path_ignored, is_repository_observable


def test_normalize_path_lowercases_drive_letter_and_uses_forward_slashes():
    assert normalize_path(r"C:\Users\dev\repo") == "c:/Users/dev/repo"


def test_normalize_path_removes_cursor_windows_uri_slash():
    assert normalize_path("/C:/Users/dev/repo") == "c:/Users/dev/repo"


def test_normalize_path_handles_none():
    assert normalize_path(None) is None


def test_repository_observable_by_default():
    config = RepositoryFilterConfig()
    assert is_repository_observable("c:/work/anything", config) is True


def test_repository_denied_when_matching_deny_glob():
    config = RepositoryFilterConfig(deny=["c:/secret/*"])
    assert is_repository_observable("c:/secret/project", config) is False


def test_repository_requires_allow_membership_when_allow_list_present():
    config = RepositoryFilterConfig(allow=["c:/work/*"])
    assert is_repository_observable("c:/work/project", config) is True
    assert is_repository_observable("c:/other/project", config) is False


def test_deny_takes_precedence_over_allow():
    config = RepositoryFilterConfig(allow=["c:/work/*"], deny=["c:/work/blocked"])
    assert is_repository_observable("c:/work/blocked", config) is False


def test_path_ignored_matches_configured_globs():
    config = RepositoryFilterConfig()
    assert is_path_ignored("c:/work/repo/.git/HEAD", config) is True
    assert is_path_ignored("c:/work/repo/src/main.py", config) is False
