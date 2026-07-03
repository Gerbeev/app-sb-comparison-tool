"""Unit tests for stonebranch_graph.expr: canonical form, N4/N5 rules, projections."""

from __future__ import annotations

from stonebranch_graph import expr


def test_parse_render_idempotent():
    text = "AND(a:SUCCESS, b:SUCCESS)"
    once = expr.render(expr.parse(text))
    twice = expr.render(expr.parse(once))
    assert once == twice
    assert once == text


def test_n4_nested_and_flattens_sorts_dedupes():
    # AND(AND(a:SUCCESS, b:SUCCESS), c:SUCCESS) -> flat sorted AND, no DNF.
    nested = expr.And((expr.And((expr.Atom("a", expr.SUCCESS), expr.Atom("b", expr.SUCCESS))), expr.Atom("c", expr.SUCCESS)))
    assert expr.render(nested) == "AND(a:SUCCESS, b:SUCCESS, c:SUCCESS)"


def test_n4_duplicate_atoms_dedupe():
    dup = expr.And((expr.Atom("a", expr.SUCCESS), expr.Atom("a", expr.SUCCESS)))
    assert expr.render(dup) == "a:SUCCESS"


def test_n5_fold_done_success_and_failure():
    assert expr.render(expr.parse("AND(A:FAILURE, A:SUCCESS)")) == "A:DONE"


def test_n5_fold_requires_matching_qualifier():
    # Different qualifiers must NOT fold into DONE.
    text = "AND(A:SUCCESS[04:00], A:FAILURE)"
    rendered = expr.render(expr.parse(text))
    assert rendered == "AND(A:FAILURE, A:SUCCESS[04:00])"


def test_n5_fold_only_applies_inside_and_not_or():
    # s(A) | f(A) is not "done" -- OR must not fold. Canonical child order sorts
    # by (node_ref, predicate, qualifier), so FAILURE sorts before SUCCESS.
    text = "OR(A:SUCCESS, A:FAILURE)"
    assert expr.render(expr.parse(text)) == "OR(A:FAILURE, A:SUCCESS)"


def test_n5_fold_preserves_unrelated_siblings():
    text = "AND(A:FAILURE, A:SUCCESS, B:SUCCESS)"
    assert expr.render(expr.parse(text)) == "AND(A:DONE, B:SUCCESS)"


def test_n5_fold_after_nary_flatten():
    # AND(AND(A:SUCCESS), A:FAILURE) must also fold once nested ANDs flatten.
    nested = expr.And((expr.And((expr.Atom("A", expr.SUCCESS),)), expr.Atom("A", expr.FAILURE)))
    assert expr.render(nested) == "A:DONE"


def test_exit_atoms_never_fold():
    text = "AND(A:EXIT[=4], A:SUCCESS)"
    rendered = expr.render(expr.parse(text))
    assert "DONE" not in rendered


def test_substitute_replaces_success_and_done_atoms():
    original = expr.parse("AND(a:SUCCESS, b:FAILURE)")
    replacement = expr.Atom("x", expr.SUCCESS)
    substituted = expr.canonicalize(expr.substitute(original, "a", replacement))
    assert expr.render(substituted) == "AND(b:FAILURE, x:SUCCESS)"


def test_substitute_drops_atom_when_replacement_is_none():
    original = expr.parse("AND(a:SUCCESS, b:SUCCESS)")
    substituted = expr.substitute(original, "a", None)
    assert expr.render(substituted) == "b:SUCCESS"


def test_success_and_only_pure_conjunction():
    assert expr.success_and_only(expr.parse("AND(a:SUCCESS, b:SUCCESS)")) == ["a", "b"]


def test_success_and_only_single_atom():
    assert expr.success_and_only(expr.parse("a:SUCCESS")) == ["a"]


def test_success_and_only_none_when_mixed_predicate():
    assert expr.success_and_only(expr.parse("AND(a:SUCCESS, b:FAILURE)")) is None


def test_success_and_only_none_for_or():
    assert expr.success_and_only(expr.parse("OR(a:SUCCESS, b:SUCCESS)")) is None


def test_topology_view_drops_and_or_shape():
    # N9a: topology is a sorted set of node refs, boolean shape is dropped.
    and_view = expr.topology_view(expr.parse("AND(a:SUCCESS, b:SUCCESS)"))
    or_view = expr.topology_view(expr.parse("OR(a:SUCCESS, b:SUCCESS)"))
    assert and_view == or_view == "a, b"


def test_topology_view_single_atom_has_no_wrapper():
    assert expr.topology_view(expr.parse("a:SUCCESS")) == "a"


def test_topology_view_dedupes_refs_from_folded_predicates():
    # AND(A:FAILURE, A:SUCCESS) folds to A:DONE -- one ref, not a wrapper.
    assert expr.topology_view(expr.parse("AND(A:FAILURE, A:SUCCESS)")) == "A"


def test_logic_view_keeps_predicates_drops_qualifiers():
    text = "AND(a:SUCCESS[04:00], b:FAILURE)"
    assert expr.logic_view(expr.parse(text)) == "AND(a:SUCCESS, b:FAILURE)"


def test_strict_view_keeps_everything():
    text = "AND(a:SUCCESS[04:00], b:FAILURE)"
    assert expr.strict_view(expr.parse(text)) == text
