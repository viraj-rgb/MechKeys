from mechkeys import launcher


class FakeInstance:
    is_primary = False
    notified = False

    def notify_primary(self):
        FakeInstance.notified = True


def test_second_launch_hands_off_without_starting_app(monkeypatch):
    monkeypatch.setattr(launcher.winutil, "SingleInstance", FakeInstance)
    monkeypatch.setattr("mechkeys.app.run", lambda **_: (_ for _ in ()).throw(AssertionError("started")))
    launcher.main([])
    assert FakeInstance.notified


def test_first_launch_runs_app_minimized(monkeypatch):
    calls = []
    primary = type("Primary", (), {"is_primary": True})
    monkeypatch.setattr(launcher.winutil, "SingleInstance", primary)
    monkeypatch.setattr("mechkeys.app.run", lambda **kwargs: calls.append(kwargs))
    launcher.main(["--minimized"])
    assert calls and calls[0]["start_hidden"] is True
