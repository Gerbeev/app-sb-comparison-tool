"""Tests for skeleton_normalize.erase_plumbing: N3 erasure fixpoint."""

from __future__ import annotations

from stonebranch_graph import expr
from stonebranch_graph.alias import AliasTable
from stonebranch_graph.skeleton import KIND_CONTAINER, KIND_UNIT, Skeleton, SkeletonNode
from stonebranch_graph.skeleton_normalize import erase_plumbing


def _node(id_, kind, parent, trigger, meta=None):
    return SkeletonNode(id=id_, kind=kind, parent=parent, trigger=trigger, meta=dict(meta or {}))


def test_task_monitor_erased_by_substitution():
    skeleton = Skeleton()
    skeleton.add_node(_node("a", KIND_UNIT, None, None))
    skeleton.add_node(
        _node(
            "mon",
            KIND_UNIT,
            None,
            expr.Atom("a", expr.SUCCESS),
            meta={"plumbing": "task_monitor", "monitor": {"target": "a", "predicate": expr.SUCCESS}},
        )
    )
    skeleton.add_node(_node("b", KIND_UNIT, None, expr.Atom("mon", expr.SUCCESS)))

    result = erase_plumbing(skeleton)

    assert "mon" not in result.nodes
    assert expr.render(result.nodes["b"].trigger) == "a:SUCCESS"
    assert len(result.erasures) == 1
    assert result.erasures[0]["id"] == "mon"


def test_sleep_dummy_erased_using_own_trigger():
    skeleton = Skeleton()
    skeleton.add_node(_node("a", KIND_UNIT, None, None))
    skeleton.add_node(
        _node("gate", KIND_UNIT, None, expr.Atom("a", expr.SUCCESS), meta={"plumbing": "sleep"})
    )
    skeleton.add_node(_node("b", KIND_UNIT, None, expr.Atom("gate", expr.SUCCESS)))

    result = erase_plumbing(skeleton)

    assert "gate" not in result.nodes
    assert expr.render(result.nodes["b"].trigger) == "a:SUCCESS"


def test_alias_marked_gate_task_erased_task04():
    skeleton = Skeleton()
    skeleton.add_node(_node("a", KIND_UNIT, None, None))
    skeleton.add_node(
        _node(
            "gate_fanin",
            KIND_UNIT,
            None,
            expr.Atom("a", expr.SUCCESS),
            meta={"plumbing": "alias"},
        )
    )
    skeleton.add_node(_node("b", KIND_UNIT, None, expr.Atom("gate_fanin", expr.SUCCESS)))

    result = erase_plumbing(skeleton)

    assert "gate_fanin" not in result.nodes
    assert expr.render(result.nodes["b"].trigger) == "a:SUCCESS"


def test_container_never_erased_even_if_marked_plumbing():
    skeleton = Skeleton()
    skeleton.add_node(
        _node("box", KIND_CONTAINER, None, None, meta={"plumbing": "task_monitor"})
    )
    result = erase_plumbing(skeleton)
    assert "box" in result.nodes
    assert any("never erased" in warning for warning in result.warnings)


def test_unsafe_predicate_keeps_node_and_emits_warning():
    skeleton = Skeleton()
    skeleton.add_node(_node("a", KIND_UNIT, None, None))
    skeleton.add_node(
        _node(
            "mon",
            KIND_UNIT,
            None,
            None,
            meta={"plumbing": "task_monitor", "monitor": {"target": "a", "predicate": expr.SUCCESS}},
        )
    )
    # b depends on mon via FAILURE -- an unsafe predicate for substitution erasure.
    skeleton.add_node(_node("b", KIND_UNIT, None, expr.Atom("mon", expr.FAILURE)))

    result = erase_plumbing(skeleton)

    assert "mon" in result.nodes
    assert "plumbing" not in result.nodes["mon"].meta
    assert any("kept plumbing" in warning for warning in result.warnings)


def test_monitor_cycle_is_broken_with_warning_not_infinite_loop():
    skeleton = Skeleton()
    skeleton.add_node(
        _node(
            "mon_a",
            KIND_UNIT,
            None,
            expr.Atom("mon_b", expr.SUCCESS),
            meta={"plumbing": "task_monitor", "monitor": {"target": "mon_b", "predicate": expr.SUCCESS}},
        )
    )
    skeleton.add_node(
        _node(
            "mon_b",
            KIND_UNIT,
            None,
            expr.Atom("mon_a", expr.SUCCESS),
            meta={"plumbing": "task_monitor", "monitor": {"target": "mon_a", "predicate": expr.SUCCESS}},
        )
    )

    # Must terminate (bounded iterations), not loop forever.
    result = erase_plumbing(skeleton)

    assert any("cycle" in warning.lower() for warning in result.warnings)


def test_collisions_and_ambiguous_externals_survive_erasure():
    """Regression guard: erase_plumbing must not silently drop diagnostics (task 02/05)."""

    skeleton = Skeleton()
    skeleton.add_node(_node("a", KIND_UNIT, None, None, meta={"native": "A1"}))
    skeleton.add_node(_node("a", KIND_UNIT, None, None, meta={"native": "A2"}))
    skeleton.ambiguous_externals.add("ext:leaf")

    result = erase_plumbing(skeleton)

    assert len(result.collisions) == 1
    assert result.collisions[0]["kept_native"] == "A1"
    assert result.collisions[0]["dropped_native"] == "A2"
    assert result.ambiguous_externals == {"ext:leaf"}


def test_ambiguous_monitor_target_diagnostic_survives_erasure_via_erasures_list():
    """Task 06: the monitor node is erased, but the ambiguity signal must not vanish."""

    skeleton = Skeleton()
    skeleton.add_node(_node("a", KIND_UNIT, None, None))
    skeleton.add_node(
        _node(
            "mon",
            KIND_UNIT,
            None,
            None,
            meta={
                "plumbing": "task_monitor",
                "monitor": {"target": "a", "predicate": expr.SUCCESS},
                "ambiguous_monitor_target": {"name": "load", "candidates": ["a", "a2"]},
            },
        )
    )
    skeleton.add_node(_node("b", KIND_UNIT, None, expr.Atom("mon", expr.SUCCESS)))

    result = erase_plumbing(skeleton)

    assert "mon" not in result.nodes
    ambiguous_erasures = [e for e in result.erasures if e.get("ambiguous_monitor_target")]
    assert len(ambiguous_erasures) == 1
    assert ambiguous_erasures[0]["ambiguous_monitor_target"]["name"] == "load"
