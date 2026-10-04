"""Black-box sync progress and reporter tests against contracts.py only."""

from io import StringIO
import time

import pytest

from skillctl.cli import main
from skillctl.config import save_config
from skillctl.contracts import ProgressEvent, SkillError, SkillSpec
from skillctl.manager import sync
from skillctl.progress import ProgressReporter

from conftest import commit, markdown, skill_dir


def assert_events(events, total, terminal):
    assert events and all(isinstance(event, ProgressEvent) for event in events)
    assert all(event.operation == "sync" for event in events)
    assert events[0].phase == "waiting"
    assert events[-1].phase == "finished"
    assert (events[-1].completed, events[-1].total) == (total, total)
    assert [(e.skill, e.phase, e.completed, e.total) for e in events if e.phase in ("done", "failed")] == terminal
    completed = 0
    for event in events[1:-1]:
        assert event.total == total
        assert 0 <= event.completed <= total
        if event.phase in ("done", "failed"):
            completed += 1
        assert event.completed == completed


def in_order(actual, expected):
    iterator = iter(actual)
    assert all(any(phase == wanted for phase in iterator) for wanted in expected), actual


def test_sync_install_progress_and_done_observes_committed_state(repository, tmp_path):
    home = tmp_path / "home"
    save_config(home / "config.toml", {"demo": SkillSpec(str(repository), "catalog/demo")})
    events = []
    at_done = []

    def observe(event):
        events.append(event)
        if event.phase == "done":
            at_done.append(((home / "skills" / "demo" / "SKILL.md").is_file(),
                            '"demo"' in (home / ".state" / "installed.json").read_text(encoding="utf-8")))

    assert sync(home, progress=observe).updated == ("demo",)
    assert_events(events, 1, [("demo", "done", 1, 1)])
    in_order([e.phase for e in events], ["waiting", "checking", "fetching", "rendering", "installing", "done", "finished"])
    assert at_done == [(True, True)]


def test_sync_sorted_items_failure_then_success_then_removal_with_counters(repository, tmp_path):
    home = tmp_path / "home"
    other = skill_dir(repository).parent / "other"
    other.mkdir()
    (other / "SKILL.md").write_text(markdown(name="other"), encoding="utf-8")
    commit(repository, "add other")
    save_config(home / "config.toml", {"demo": SkillSpec(str(repository), "catalog/demo")})
    sync(home)
    save_config(home / "config.toml", {
        "beta": SkillSpec(str(repository), "catalog/other"),  # Name mismatch fails.
        "other": SkillSpec(str(repository), "catalog/other"),
    })
    events = []
    done_observations = []

    def observe(event):
        events.append(event)
        if event.phase == "done":
            done_observations.append((event.skill, (home / "skills" / "other" / "SKILL.md").is_file(),
                                      (home / "skills" / "demo").exists()))

    result = sync(home, progress=observe)
    assert result.updated == ("other",) and result.removed == ("demo",)
    assert result.errors.get("beta")
    assert_events(events, 3, [
        ("beta", "failed", 1, 3), ("other", "done", 2, 3), ("demo", "done", 3, 3),
    ])
    assert [e.skill for e in events if e.phase == "checking"] == ["beta", "other", "demo"]
    in_order([e.phase for e in events if e.skill == "other"], ["checking", "fetching", "rendering", "installing", "done"])
    in_order([e.phase for e in events if e.skill == "demo"], ["checking", "removing", "done"])
    assert not any(e.phase == "done" for e in events if e.skill == "beta")
    assert done_observations == [("other", True, True), ("demo", True, False)]


def test_sync_removal_refusal_counts_failure_and_continues(repository, tmp_path):
    home = tmp_path / "home"
    other = skill_dir(repository).parent / "other"
    other.mkdir()
    (other / "SKILL.md").write_text(markdown(name="other"), encoding="utf-8")
    commit(repository, "add other")
    save_config(home / "config.toml", {
        "demo": SkillSpec(str(repository), "catalog/demo"),
        "other": SkillSpec(str(repository), "catalog/other"),
    })
    sync(home)
    (home / "skills" / "demo" / "local").write_text("edited", encoding="utf-8")
    save_config(home / "config.toml", {})
    events = []
    result = sync(home, progress=events.append)
    assert result.removed == ("other",) and result.errors.get("demo")
    assert_events(events, 2, [("demo", "failed", 1, 2), ("other", "done", 2, 2)])
    assert [e.skill for e in events if e.phase == "removing"] == ["demo", "other"]


def test_local_sync_progress_skips_fetch_and_counts_done(tmp_path):
    home = tmp_path / "home"
    target = home / "skills" / "personal"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(markdown(name="personal"), encoding="utf-8")
    save_config(home / "config.toml", {"personal": SkillSpec("local")})
    events = []
    assert sync(home, progress=events.append).updated == ("personal",)
    assert_events(events, 1, [("personal", "done", 1, 1)])
    phases = [e.phase for e in events]
    in_order(phases, ["waiting", "checking", "rendering", "installing", "done", "finished"])
    assert "fetching" not in phases


def test_sync_empty_config_finishes_zero_of_zero(tmp_path):
    home = tmp_path / "home"
    save_config(home / "config.toml", {})
    events = []
    result = sync(home, progress=events.append)
    assert result.updated == result.removed == () and result.errors == {}
    assert_events(events, 0, [])


def test_global_error_does_not_publish_done(tmp_path):
    events = []
    with pytest.raises(SkillError):
        sync(tmp_path / "missing-home", progress=events.append)
    assert events and events[0].operation == "sync" and events[0].phase == "waiting"
    assert not any(event.phase == "done" for event in events)


def test_callback_exceptions_do_not_change_sync_result(repository, tmp_path):
    home = tmp_path / "home"
    save_config(home / "config.toml", {"demo": SkillSpec(str(repository), "catalog/demo")})
    seen = []

    def broken(event):
        seen.append(event)
        raise RuntimeError("display failed")

    assert sync(home, progress=broken).updated == ("demo",)
    assert any(event.phase == "done" for event in seen)
    save_config(home / "config.toml", {})
    seen.clear()
    assert sync(home, progress=broken).removed == ("demo",)
    assert any(event.phase == "finished" for event in seen)


def test_manager_without_callback_writes_nothing(repository, tmp_path, capsys):
    home = tmp_path / "home"
    save_config(home / "config.toml", {"demo": SkillSpec(str(repository), "catalog/demo")})
    sync(home)
    save_config(home / "config.toml", {})
    sync(home)
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_reporter_stringio_plain_text_literal_markup_and_no_stdout(capsys):
    class FlushedStringIO(StringIO):
        flushes = 0

        def flush(self):
            self.flushes += 1
            super().flush()

    stream = FlushedStringIO()
    skill = "demo [red]literal[/red]"
    with ProgressReporter(stream=stream) as report:
        report(ProgressEvent("sync", "checking", skill=skill, completed=1, total=3))
        report(ProgressEvent("sync", "finished", completed=3, total=3))
    text = stream.getvalue()
    assert "sync" in text and "checking" in text and "finished" in text
    assert skill in text
    assert "1/3" in text and "3/3" in text
    assert "\x1b" not in text and "\r" not in text and "\b" not in text
    assert text.endswith("\n")
    assert stream.flushes >= 2
    assert capsys.readouterr().out == ""


def test_reporter_does_not_execute_untrusted_terminal_controls():
    stream = StringIO()
    with ProgressReporter(stream=stream) as report:
        report(ProgressEvent("sync", "fetching", skill="demo\x1b[31mALERT\x1b[0m", completed=0, total=1))
    text = stream.getvalue()
    assert "demo" in text and "ALERT" in text
    assert "\x1b" not in text and "\r" not in text


def test_reporter_propagates_exception_from_context_body():
    stream = StringIO()
    with pytest.raises(ValueError, match="body failed"):
        with ProgressReporter(stream=stream) as report:
            report(ProgressEvent("sync", "waiting"))
            raise ValueError("body failed")
    assert "waiting" in stream.getvalue()


def test_reporter_tty_restores_cursor_stops_animation_and_propagates_error():
    class TTYStringIO(StringIO):
        def isatty(self):
            return True

    stream = TTYStringIO()
    with pytest.raises(ValueError, match="body failed"):
        with ProgressReporter(stream=stream) as report:
            report(ProgressEvent("sync", "fetching", skill="demo", completed=0, total=2))
            raise ValueError("body failed")
    output_at_exit = stream.getvalue()
    assert "\x1b[?25h" in output_at_exit
    time.sleep(0.15)
    assert stream.getvalue() == output_at_exit


def test_cli_progress_and_partial_failure(repository, tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("SKILLCTL_HOME", str(home))
    save_config(home / "config.toml", {"demo": SkillSpec(str(repository), "catalog/demo")})
    assert main(["sync"]) == 0
    output = capsys.readouterr()
    assert "Updated demo" in output.out and "/reload" in output.out
    assert "sync" in output.err and "done" in output.err and "\x1b" not in output.err

    (home / "skills" / "demo" / "local").write_text("changed", encoding="utf-8")
    save_config(home / "config.toml", {})
    assert main(["sync"]) == 1
    output = capsys.readouterr()
    assert "failed" in output.err and "finished" in output.err
    assert "Traceback" not in output.out + output.err
