import sys
import threading
import time

import pytest

from mechkeys.audiodevice import DeviceWatcher, EndpointReader


class FakeReader:
    """Reports whatever ids the test sets."""

    def __init__(self, ids=("A", "A")):
        self.ids = ids
        self.name = "Speakers"
        self.fail = False

    def default_ids(self):
        if self.fail:
            raise OSError("COM hiccup")
        return self.ids

    def default_name(self):
        return self.name


def wait_for(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def watch():
    started = []

    def build(reader, dead=lambda: False, **kwargs):
        calls = []
        options = dict(poll_s=0.01, settle_s=0.02, retry_s=0.05, retry_max_s=0.2)
        options.update(kwargs)
        watcher = DeviceWatcher(on_change=calls.append, is_audio_dead=dead,
                                reader_factory=lambda: reader, **options)
        watcher.start()
        started.append(watcher)
        return watcher, calls

    yield build
    for watcher in started:
        watcher.stop()


def test_no_change_means_no_callback(watch):
    _, calls = watch(FakeReader())
    time.sleep(0.15)
    assert calls == []


def test_switching_output_device_triggers_one_restart(watch):
    reader = FakeReader()
    _, calls = watch(reader)
    reader.ids = ("B", "B")
    assert wait_for(lambda: calls)
    time.sleep(0.1)
    assert calls == ["default output changed"]


def test_change_in_either_role_counts(watch):
    reader = FakeReader()
    _, calls = watch(reader)
    reader.ids = ("A", "C")
    assert wait_for(lambda: calls)


def test_a_flicker_that_settles_back_is_ignored(watch):
    reader = FakeReader()
    _, calls = watch(reader, settle_s=0.1)

    def flicker():
        reader.ids = ("B", "B")
        time.sleep(0.04)
        reader.ids = ("A", "A")

    threading.Thread(target=flicker).start()
    time.sleep(0.4)
    assert calls == []


def test_device_removed_then_returning_restarts_each_time(watch):
    reader = FakeReader()
    _, calls = watch(reader)
    reader.ids = (None, None)          # headset unplugged, nothing else available
    assert wait_for(lambda: len(calls) == 1)
    reader.ids = ("A", "A")            # plugged back in
    assert wait_for(lambda: len(calls) == 2)


def test_dead_audio_is_retried_with_backoff_until_it_recovers(watch):
    state = {"dead": True}
    _, calls = watch(FakeReader(), dead=lambda: state["dead"])
    assert wait_for(lambda: len(calls) >= 3, timeout=3)
    assert set(calls) == {"audio stream stopped"}
    state["dead"] = False
    settled = len(calls)
    time.sleep(0.5)
    assert len(calls) <= settled + 1


def test_healthy_audio_is_never_restarted(watch):
    _, calls = watch(FakeReader(), dead=lambda: False)
    time.sleep(0.3)
    assert calls == []


def test_reader_errors_do_not_kill_the_watcher(watch):
    reader = FakeReader()
    _, calls = watch(reader)
    reader.fail = True
    time.sleep(0.1)
    reader.fail = False
    reader.ids = ("B", "B")
    assert wait_for(lambda: calls)


def test_missing_com_still_retries_dead_audio():
    def broken():
        raise OSError("no enumerator")

    calls = []
    watcher = DeviceWatcher(on_change=calls.append, is_audio_dead=lambda: True, reader_factory=broken,
                            poll_s=0.01, retry_s=0.03)
    watcher.start()
    try:
        assert wait_for(lambda: calls)
    finally:
        watcher.stop()


def test_stop_ends_the_thread():
    watcher = DeviceWatcher(on_change=lambda r: None, is_audio_dead=lambda: False,
                            reader_factory=FakeReader, poll_s=0.01)
    watcher.start()
    thread = watcher._thread
    watcher.stop()
    assert not thread.is_alive()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows audio endpoints")
def test_windows_reports_the_default_output():
    try:
        reader = EndpointReader()
    except OSError:
        pytest.skip("no audio device enumerator on this machine")
    ids = reader.default_ids()
    assert len(ids) == 2
    if ids[0] is None:
        pytest.skip("no output device")
    assert ids[0].startswith("{0.0.0.00000000}.")
    assert ids == reader.default_ids()               # stable between reads
    assert reader.default_name() not in ("", "unknown device")
