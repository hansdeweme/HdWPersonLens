"""Completed portrait failures must release Qt job tracking, including stale generations."""
from types import SimpleNamespace
import ast
from pathlib import Path


# Exercise the actual unbound handlers without importing Qt/dlib into pytest.
# Full workbench lifecycle tests run separately in fresh, bootstrapped interpreters.
source_path = Path(__file__).resolve().parents[1] / "hdw_person_lens" / "persons_workbench.py"
tree = ast.parse(source_path.read_bytes())
workbench_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PersonsWorkbench")
handlers = [node for node in workbench_class.body if isinstance(node, ast.FunctionDef)
            and node.name in ("_portrait_failed", "_portrait_ready")]
namespace = {}
exec(compile(ast.Module(body=handlers, type_ignores=[]), str(source_path), "exec"), namespace)
PersonsWorkbench = SimpleNamespace(**{node.name: namespace[node.name] for node in handlers})


class _Signal:
    def __init__(self): self.messages = []

    def emit(self, message): self.messages.append(message)


def test_failed_portrait_releases_tracking():
    error_signal = _Signal()
    workbench = SimpleNamespace(_portrait_pending={(3, "Ada"): object(), (2, "Old"): object()},
                                _portrait_generation=3, _portrait_stopping=False, _portrait_failures={},
                                portrait_status=SimpleNamespace(setText=lambda text: None), portrait_error=error_signal,
                                _current_person_name=lambda: None)
    PersonsWorkbench._portrait_failed(workbench, "Old", 2, "obsolete")
    assert (2, "Old") not in workbench._portrait_pending
    assert not error_signal.messages
    PersonsWorkbench._portrait_failed(workbench, "Ada", 3, "failed")
    assert not workbench._portrait_pending
    assert workbench._portrait_failures == {"Ada": "failed"}
    assert error_signal.messages == ["[Portrait] Ada: failed"]


def test_obsolete_failure_does_not_remove_current_request_for_same_person():
    workbench = SimpleNamespace(_portrait_pending={(2, "Ada"): object(), (3, "Ada"): object()},
                                _portrait_generation=3, _portrait_stopping=False, _portrait_failures={})
    PersonsWorkbench._portrait_failed(workbench, "Ada", 2, "obsolete")
    assert set(workbench._portrait_pending) == {(3, "Ada")}
    assert not workbench._portrait_failures


def test_shutdown_failure_and_later_ready_delivery_are_idempotent():
    workbench = SimpleNamespace(_portrait_pending={(3, "Ada"): object()},
                                _portrait_generation=3, _portrait_stopping=True, _portrait_failures={})
    PersonsWorkbench._portrait_failed(workbench, "Ada", 3, "stopping")
    PersonsWorkbench._portrait_failed(workbench, "Ada", 3, "duplicate")
    PersonsWorkbench._portrait_ready(workbench, "Ada", 3, None)
    assert not workbench._portrait_pending and not workbench._portrait_failures
