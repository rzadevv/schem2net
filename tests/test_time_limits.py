"""Extraction budgets compose with callers' one-shot and periodic alarms."""

import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from schem2net import pdf


class Alarm:
    def __init__(self):
        self.now = 0.0
        self.handler = 0
        self.deadline = None
        self.interval = 0.0

    def signal(self, signum, handler):
        previous, self.handler = self.handler, handler
        return previous

    def getitimer(self, which):
        return (max(self.deadline - self.now, 0.0) if self.deadline else 0.0, self.interval)

    def setitimer(self, which, seconds, interval=0.0):
        previous = self.getitimer(which)
        self.deadline = self.now + seconds if seconds else None
        self.interval = interval
        return previous

    def advance(self, seconds):
        target = self.now + seconds
        while self.deadline is not None and self.deadline <= target:
            self.now = self.deadline
            self.deadline = self.deadline + self.interval if self.interval else None
            if callable(self.handler):
                self.handler(14, None)
        self.now = target


@pytest.fixture
def alarm(monkeypatch):
    alarm = Alarm()
    monkeypatch.setattr(pdf, "monotonic", lambda: alarm.now, raising=False)
    monkeypatch.setattr(
        pdf,
        "signal",
        SimpleNamespace(
            SIGALRM=14,
            ITIMER_REAL=0,
            SIG_DFL=0,
            SIG_IGN=1,
            signal=alarm.signal,
            getsignal=lambda signum: alarm.handler,
            setitimer=alarm.setitimer,
            getitimer=alarm.getitimer,
        ),
    )
    return alarm


def test_nested_budget_keeps_the_outer_deadline(alarm):
    with pytest.raises(TimeoutError, match="5 s"), pdf.time_limit(5), pdf.time_limit(10):
        alarm.advance(6)
    assert alarm.now == 5
    assert alarm.getitimer(0) == (0, 0)
    assert alarm.handler == 0


def test_shorter_inner_timeout_restores_the_remaining_outer_budget(alarm):
    with pytest.raises(TimeoutError, match="5 s"), pdf.time_limit(5):
        with pytest.raises(TimeoutError, match="1 s"), pdf.time_limit(1):
            alarm.advance(2)
        assert alarm.getitimer(0)[0] == pytest.approx(4)
        alarm.advance(5)


def test_normal_exit_preserves_the_callers_timer_and_interval(alarm):
    calls = []

    def handler(*args):
        calls.append(alarm.now)

    alarm.signal(14, handler)
    alarm.setitimer(0, 10, 3)
    with pdf.time_limit(5):
        alarm.advance(2)
    assert alarm.handler is handler
    assert alarm.getitimer(0) == pytest.approx((8, 3))
    alarm.advance(8)
    assert calls == [10]


def test_earlier_caller_alarm_can_return_without_disabling_the_budget(alarm):
    calls = []
    alarm.signal(14, lambda *args: calls.append(alarm.now))
    alarm.setitimer(0, 1)
    with pytest.raises(TimeoutError, match="3 s"), pdf.time_limit(3):
        alarm.advance(4)
    assert calls == [1]
    assert alarm.now == 3


def test_periodic_caller_alarm_does_not_disable_the_budget(alarm):
    calls = []

    def handler(*args):
        calls.append(alarm.now)

    alarm.signal(14, handler)
    alarm.setitimer(0, 1, 1)
    with pytest.raises(TimeoutError, match="3.5 s"), pdf.time_limit(3.5):
        alarm.advance(4)
    assert calls == [1, 2, 3]
    assert alarm.handler is handler
    assert alarm.getitimer(0) == pytest.approx((0.5, 1))


def test_exception_restores_the_callers_remaining_alarm(alarm):
    def handler(*args):
        pass

    alarm.signal(14, handler)
    alarm.setitimer(0, 10)
    with pytest.raises(ValueError, match="failed"), pdf.time_limit(5):
        alarm.advance(2)
        raise ValueError("failed")
    assert alarm.handler is handler
    assert alarm.getitimer(0) == pytest.approx((8, 0))


def test_alarm_expiring_during_handler_installation_is_preserved(alarm, monkeypatch):
    calls, installed = [], []
    alarm.signal(14, lambda *args: calls.append(alarm.now))
    alarm.setitimer(0, 1)
    original = alarm.signal

    def delayed_install(signum, handler):
        previous = original(signum, handler)
        if not installed:
            installed.append(True)
            alarm.advance(1)
        return previous

    monkeypatch.setattr(pdf.signal, "signal", delayed_install)
    with pdf.time_limit(3):
        alarm.advance(0.5)
    assert calls == [pytest.approx(1, abs=1e-5)]
    assert alarm.getitimer(0) == (0, 0)


def test_zero_budget_leaves_the_callers_alarm_active(alarm):
    calls = []
    alarm.signal(14, lambda *args: calls.append(alarm.now))
    alarm.setitimer(0, 1)
    with pdf.time_limit(0):
        alarm.advance(3)
    assert calls == [1]


def test_ignored_caller_alarm_does_not_disable_the_budget(alarm):
    alarm.signal(14, 1)
    alarm.setitimer(0, 1)
    with pytest.raises(TimeoutError, match="3 s"), pdf.time_limit(3):
        alarm.advance(4)
    assert alarm.handler == 1


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf")])
def test_invalid_budget_preserves_the_callers_alarm(alarm, seconds):
    alarm.setitimer(0, 10, 3)
    with pytest.raises(ValueError, match="finite and nonnegative"), pdf.time_limit(seconds):
        pytest.fail("invalid budget was entered")
    assert alarm.getitimer(0) == (10, 3)
    assert alarm.handler == 0


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="requires POSIX interval timers")
@pytest.mark.parametrize("default_handler", [False, True])
def test_real_posix_alarm_survives_a_nested_budget(default_handler):
    code = """
import signal,time
from schem2net import pdf
if DEFAULT:
    signal.setitimer(signal.ITIMER_REAL, 0.03)
    with pdf.time_limit(0.3):
        time.sleep(0.15)
else:
    try:
        with pdf.time_limit(0.03), pdf.time_limit(0.3):
            time.sleep(0.15)
    except TimeoutError as exc:
        assert '0.03 s' in str(exc)
    else:
        raise AssertionError('outer budget was lost')
"""
    result = subprocess.run(
        [sys.executable, "-c", code.replace("DEFAULT", repr(default_handler))],
        capture_output=True, text=True, timeout=10,
    )  # fmt: skip
    assert result.returncode == (-signal.SIGALRM if default_handler else 0), result.stderr
