"""State machine tests. This is the thing three threads fight over."""

import threading

from momito import state as state_mod
from momito.state import AppState


def ready_state() -> AppState:
    s = AppState()
    s.model_loaded()
    return s


def test_starts_loading() -> None:
    assert AppState().label == state_mod.LOADING


def test_ready_is_idle() -> None:
    assert ready_state().label == state_mod.IDLE


def test_recording_claim_is_exclusive() -> None:
    s = ready_state()
    assert s.start_recording() is True
    assert s.start_recording() is False  # already held
    assert s.label == state_mod.REC


def test_stop_recording_reports_whether_it_did_anything() -> None:
    s = ready_state()
    assert s.stop_recording() is False  # nothing to stop
    s.start_recording()
    assert s.stop_recording() is True
    assert s.stop_recording() is False


def test_recording_wins_over_a_job_still_finishing() -> None:
    """The old bug: the worker finishing a job stamped idle over a recording
    that had already started."""
    s = ready_state()
    s.job_queued()
    assert s.label == state_mod.BUSY
    s.start_recording()
    assert s.label == state_mod.REC
    s.job_done()
    assert s.label == state_mod.REC


def test_jobs_never_go_negative() -> None:
    s = ready_state()
    s.job_done()
    s.job_done()
    assert s.jobs == 0
    s.job_queued()
    assert s.jobs == 1


def test_failed_model_is_an_error_state_not_a_ready_one() -> None:
    s = AppState()
    s.model_failed("no disk space")
    assert s.ready is False
    assert s.error == "no disk space"
    assert s.label == state_mod.ERROR


def test_failed_model_blocks_recording() -> None:
    s = AppState()
    s.model_failed("boom")
    assert s.start_recording() is False


def test_error_message_is_never_empty() -> None:
    s = AppState()
    s.model_failed("")
    assert s.error == "unknown error"


def test_retry_clears_the_error() -> None:
    s = AppState()
    s.model_failed("boom")
    s.model_loading()
    assert s.error == ""
    assert s.label == state_mod.LOADING
    s.model_loaded()
    assert s.label == state_mod.IDLE


def test_only_one_thread_can_claim_the_mic() -> None:
    s = ready_state()
    wins = []
    start = threading.Barrier(8)

    def claim() -> None:
        start.wait()
        if s.start_recording():
            wins.append(1)

    threads = [threading.Thread(target=claim) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1


def test_job_counter_survives_concurrent_updates() -> None:
    s = ready_state()

    def churn() -> None:
        for _ in range(500):
            s.job_queued()
        for _ in range(500):
            s.job_done()

    threads = [threading.Thread(target=churn) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert s.jobs == 0
    assert s.label == state_mod.IDLE
