"""API 契约与关键安全边界。"""
from api.main import app


def test_api_exposes_comment_workflow():
    paths = app.openapi()['paths']
    assert '/api/automation/approve' in paths or any('approve' in path for path in paths)
    assert '/api/analysis/runs' in paths
    assert '/api/strategy/profiles' in paths
    assert '/api/settings/model' in paths
    assert '/api/strategy/scenario/plan' in paths


def test_model_settings_corruption_does_not_silently_clear_credentials(tmp_path, monkeypatch):
    import pytest

    from api.services import model_settings
    from api.services.json_store import JsonStoreCorruption

    path = tmp_path / 'model_settings.json'
    path.write_text('{broken', encoding='utf-8')
    monkeypatch.setattr(model_settings, 'SETTINGS_PATH', path)
    with pytest.raises(JsonStoreCorruption):
        model_settings.load_model_settings()
    assert any('{broken' in p.read_text() for p in tmp_path.iterdir())


def test_zaobo_reply_lint_still_flags_high_risk_claims():
    from scripts.zaobo_talk_check import check
    assert any("风险" in issue for issue in check("这个方法保证见效"))
