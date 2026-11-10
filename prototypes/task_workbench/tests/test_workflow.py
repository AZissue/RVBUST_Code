import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model import Workflow


def ready():
    flow = Workflow()
    flow.set_inputs(['机位 001', '机位 002'])
    return flow


def test_view_selection_does_not_replace_processing_inputs():
    flow = ready()
    flow.select('机位 003')
    assert flow.inputs == ['机位 001', '机位 002']


def test_input_change_rejects_inflight_result():
    flow = ready()
    token = flow.start()
    flow.set_inputs(['机位 002', '机位 003'])
    assert not flow.complete(token)
    assert not flow.can_publish


def test_parameter_change_invalidates_candidate_but_keeps_draft():
    flow = ready()
    assert flow.complete(flow.start())
    flow.set_parameter(2.5)
    assert flow.parameter == 2.5
    assert not flow.can_publish
    with pytest.raises(ValueError):
        flow.publish()


def test_stop_waits_for_inflight_completion():
    flow = ready()
    token = flow.start()
    flow.stop()
    assert flow.busy
    with pytest.raises(ValueError):
        flow.start()
    assert not flow.complete(token)
    assert not flow.busy
    assert not flow.can_publish


def test_publish_once_preserves_sources():
    flow = ready()
    assert flow.complete(flow.start())
    result = flow.publish()
    assert result in flow.results
    assert flow.inputs == ['机位 001', '机位 002']
    assert flow.selected == result
    with pytest.raises(ValueError):
        flow.publish()


def test_fail_retry_and_double_dispatch_guard():
    flow = ready()
    token = flow.start()
    with pytest.raises(ValueError):
        flow.start()
    assert not flow.complete(token, failed=True)
    assert flow.inputs
    assert flow.complete(flow.start())


def test_late_callback_cannot_finish_new_job():
    flow = ready()
    old = flow.start()
    flow.complete(old, failed=True)
    current = flow.start()
    assert not flow.complete(old)
    assert flow.busy
    assert flow.complete(current)


def test_insufficient_input_is_explicit():
    flow = Workflow()
    flow.set_inputs(['机位 001'])
    with pytest.raises(ValueError):
        flow.start()
