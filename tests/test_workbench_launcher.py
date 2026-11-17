"""The double-click launcher must preserve other apps and prebuilt distributions."""
from unittest.mock import Mock

from scripts import start_workbench as launcher


def test_occupied_port_never_starts_or_stops_other_process(monkeypatch, capsys):
    monkeypatch.setenv("PORT", "8766")
    monkeypatch.setattr(launcher, "port_in_use", lambda port: True)
    spawn = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    assert launcher.main() == 1
    spawn.assert_not_called()
    assert "没有停止任何已有进程" in capsys.readouterr().out


def test_invalid_port_has_actionable_message(monkeypatch, capsys):
    monkeypatch.setenv("PORT", "not-a-port")
    probe = Mock()
    monkeypatch.setattr(launcher, "port_in_use", probe)
    assert launcher.main() == 1
    probe.assert_not_called()
    assert "PORT" in capsys.readouterr().out


def test_prebuilt_package_does_not_require_node(monkeypatch, tmp_path):
    monkeypatch.setenv("PORT", "8766")
    dist = tmp_path / "web_react" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>ready</html>")
    (dist / ".source-fingerprint").write_text("unchanged")
    monkeypatch.setattr(launcher, "frontend_fingerprint", lambda: "unchanged")
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher.os, "chdir", lambda path: None)
    monkeypatch.setattr(launcher, "port_in_use", lambda port: False)
    monkeypatch.setattr(launcher.shutil, "which", lambda cmd: "/bin/uv" if cmd == "uv" else None)
    steps = Mock()
    monkeypatch.setattr(launcher, "run_step", steps)
    process = Mock()
    process.wait.return_value = 0
    monkeypatch.setattr(launcher.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(launcher.threading, "Thread", Mock())
    assert launcher.main() == 0
    steps.assert_not_called()
    args = launcher.subprocess.Popen.call_args.args[0]
    assert args[args.index("--host") + 1] == "127.0.0.1"


def test_browser_only_opens_after_health_check(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(launcher, "health_ready", Mock(side_effect=[False, True]))
    monkeypatch.setattr(launcher.time, "sleep", Mock())
    opened = Mock()
    monkeypatch.setattr(launcher.webbrowser, "open", opened)
    launcher.open_when_ready(process, "http://127.0.0.1:8766")
    opened.assert_called_once_with("http://127.0.0.1:8766")


def test_code_updates_change_build_fingerprint(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    source = tmp_path / "web_react" / "src"
    source.mkdir(parents=True)
    page = source / "App.tsx"
    page.write_text("old page")
    old = launcher.frontend_fingerprint()
    page.write_text("new page")
    assert launcher.frontend_fingerprint() != old
    old = launcher.frontend_fingerprint()
    (source / "NewPage.tsx").write_text("added page")
    assert launcher.frontend_fingerprint() != old
