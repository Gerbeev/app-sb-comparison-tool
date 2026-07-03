"""Canonical trigger expressions from docs/mapping-theory.md sections 2, 5, and 7."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import TypeAlias

SUCCESS = "SUCCESS"
FAILURE = "FAILURE"
DONE = "DONE"
TERMINATED = "TERMINATED"
NOT_RUNNING = "NOT_RUNNING"
EXIT = "EXIT"

PREDICATES = frozenset({SUCCESS, FAILURE, DONE, TERMINATED, NOT_RUNNING, EXIT})


@dataclass(frozen=True)
class Atom:
    """A dependency predicate on one skeleton node reference."""

    node_ref: str
    predicate: str
    qualifier: str = ""


@dataclass(frozen=True)
class And:
    """An n-ary conjunction expression."""

    children: tuple[Expr, ...]


@dataclass(frozen=True)
class Or:
    """An n-ary disjunction expression."""

    children: tuple[Expr, ...]


@dataclass(frozen=True)
class Not:
    """A negated expression branch."""

    child: Expr


Expr: TypeAlias = Atom | And | Or | Not


class ExprSyntaxError(ValueError):
    """Expression parser error carrying the character position."""

    def __init__(self, message: str, position: int) -> None:
        self.position = position
        super().__init__(f"{message} at position {position}")


def canonicalize(expr: Expr) -> Expr:
    """Return the N4 canonical form without distribution or negation pushing."""

    return _canonicalize(expr)


@lru_cache(maxsize=131_072)
def _canonicalize(expr: Expr) -> Expr:
    """Cached implementation for immutable expression trees."""

    if isinstance(expr, Atom):
        return expr
    if isinstance(expr, Not):
        return Not(canonicalize(expr.child))
    if isinstance(expr, And):
        return _canonical_nary(And, expr.children)
    if isinstance(expr, Or):
        return _canonical_nary(Or, expr.children)
    raise TypeError(f"Unsupported expression type: {type(expr)!r}")


def render(expr: Expr) -> str:
    """Render an expression in canonical skeleton trigger syntax."""

    return _render(canonicalize(expr))


def parse(text: str) -> Expr:
    """Parse canonical skeleton trigger syntax into an expression tree."""

    parser = _Parser(text)
    expr = parser.parse_expr()
    if parser.pos != len(text):
        raise ExprSyntaxError("Unexpected trailing input", parser.pos)
    return canonicalize(expr)


def atoms(expr: Expr) -> tuple[Atom, ...]:
    """Return all atoms in document order."""

    if isinstance(expr, Atom):
        return (expr,)
    if isinstance(expr, Not):
        return atoms(expr.child)
    result: list[Atom] = []
    for child in expr.children:
        result.extend(atoms(child))
    return tuple(result)


def substitute(expr: Expr, ref_id: str, replacement: Expr | None) -> Expr | None:
    """Replace SUCCESS/DONE atoms pointing at ref_id with replacement."""

    if isinstance(expr, Atom):
        if expr.node_ref == ref_id and expr.predicate in {SUCCESS, DONE}:
            return replacement
        return expr
    if isinstance(expr, Not):
        child = substitute(expr.child, ref_id, replacement)
        return Not(child) if child is not None else None

    children = tuple(
        child
        for child in (substitute(child, ref_id, replacement) for child in expr.children)
        if child
    )
    if not children:
        return None
    if len(children) == 1:
        return children[0]
    return canonicalize(type(expr)(children))


def success_and_only(expr: Expr) -> list[str] | None:
    """Return sorted node refs for pure SUCCESS conjunctions, otherwise None."""

    canonical = canonicalize(expr)
    if _is_plain_success(canonical):
        return [canonical.node_ref]  # type: ignore[union-attr]
    if not isinstance(canonical, And):
        return None
    refs: list[str] = []
    for child in canonical.children:
        if not _is_plain_success(child):
            return None
        refs.append(child.node_ref)  # type: ignore[union-attr]
    return sorted(refs)


def fold_done(pairs: Iterable[tuple[str, str, str]]) -> tuple[Atom, ...]:
    """Fold SUCCESS plus FAILURE pairs in one AND context into DONE atoms."""

    atoms_by_key = {
        Atom(node_ref, predicate, qualifier) for node_ref, predicate, qualifier in pairs
    }
    folded = _fold_done_siblings(list(atoms_by_key))
    return tuple(sorted(folded, key=_atom_key))


def topology_view(expr: Expr) -> str:
    """Render the topology projection: a sorted set of node refs only (N9a).

    ``mapping-theory.md`` §5 level 1 defines topology as "node set + containment
    + atom nodeRefs only (are the same things wired?)". Boolean AND/OR/NOT
    structure is dropped entirely here rather than merely erasing predicates
    and qualifiers, so ``AND(a, b)`` and ``OR(a, b)`` are topology-identical
    (they wire the same things); the boolean shape first becomes visible at
    the logic level. Duplicate refs from folded predicates collapse to one.
    """

    refs = sorted({atom.node_ref for atom in atoms(expr)})
    return ", ".join(refs)


def logic_view(expr: Expr) -> str:
    """Render the canonical logic projection with qualifiers erased."""

    return render(_project(expr, predicate=True, qualifier=False))


def strict_view(expr: Expr) -> str:
    """Render the full strict canonical expression."""

    return render(expr)


def _canonical_nary(cls: type[And] | type[Or], children: tuple[Expr, ...]) -> Expr:
    flattened: list[Expr] = []
    for child in children:
        canonical_child = canonicalize(child)
        if isinstance(canonical_child, cls):
            flattened.extend(canonical_child.children)
        else:
            flattened.append(canonical_child)

    if cls is And:
        flattened = _fold_done_siblings(flattened)

    unique = sorted(set(flattened), key=_sort_key)
    if len(unique) == 1:
        return unique[0]
    return cls(tuple(unique))


def _fold_done_siblings(children: list[Expr]) -> list[Expr]:
    """Fold sibling Atom(ref, SUCCESS, q) + Atom(ref, FAILURE, q) into Atom(ref, DONE, q).

    Only applies to direct Atom children of an And (never Or). Runs after n-ary
    flattening so nested ANDs are already exposed as siblings. Deterministic:
    atoms are sorted before folding.
    """

    atom_children = sorted(
        (child for child in children if isinstance(child, Atom)), key=_atom_key
    )
    non_atom_children = [child for child in children if not isinstance(child, Atom)]

    by_ref_qualifier: dict[tuple[str, str], set[str]] = {}
    for atom in atom_children:
        by_ref_qualifier.setdefault((atom.node_ref, atom.qualifier), set()).add(atom.predicate)

    consumed: set[Atom] = set()
    folded: list[Atom] = []
    for (node_ref, qualifier), predicates in by_ref_qualifier.items():
        if SUCCESS in predicates and FAILURE in predicates:
            consumed.add(Atom(node_ref, SUCCESS, qualifier))
            consumed.add(Atom(node_ref, FAILURE, qualifier))
            folded.append(Atom(node_ref, DONE, qualifier))

    remaining = [atom for atom in atom_children if atom not in consumed]
    return non_atom_children + remaining + folded


def _sort_key(expr: Expr) -> tuple[int, str, str, str]:
    if isinstance(expr, Atom):
        return (0, expr.node_ref, expr.predicate, expr.qualifier)
    return (1, _render(expr), "", "")


def _atom_key(atom: Atom) -> tuple[str, str, str]:
    return (atom.node_ref, atom.predicate, atom.qualifier)


def _render(expr: Expr) -> str:
    if isinstance(expr, Atom):
        if expr.qualifier:
            return f"{expr.node_ref}:{expr.predicate}[{expr.qualifier}]"
        return f"{expr.node_ref}:{expr.predicate}"
    if isinstance(expr, And):
        return f"AND({', '.join(_render(child) for child in expr.children)})"
    if isinstance(expr, Or):
        return f"OR({', '.join(_render(child) for child in expr.children)})"
    return f"NOT({_render(expr.child)})"


_render = lru_cache(maxsize=131_072)(_render)


def _project(expr: Expr, *, predicate: bool, qualifier: bool) -> Expr:
    if isinstance(expr, Atom):
        projected_predicate = expr.predicate if predicate else ""
        projected_qualifier = expr.qualifier if qualifier else ""
        return Atom(expr.node_ref, projected_predicate, projected_qualifier)
    if isinstance(expr, And):
        children = tuple(
            _project(child, predicate=predicate, qualifier=qualifier) for child in expr.children
        )
        return And(children)
    if isinstance(expr, Or):
        children = tuple(
            _project(child, predicate=predicate, qualifier=qualifier) for child in expr.children
        )
        return Or(children)
    return Not(_project(expr.child, predicate=predicate, qualifier=qualifier))


def _is_plain_success(expr: Expr) -> bool:
    return isinstance(expr, Atom) and expr.predicate == SUCCESS and expr.qualifier == ""


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def parse_expr(self) -> Expr:
        if self.text.startswith("AND(", self.pos):
            return self._parse_nary("AND", And)
        if self.text.startswith("OR(", self.pos):
            return self._parse_nary("OR", Or)
        if self.text.startswith("NOT(", self.pos):
            return self._parse_not()
        return self._parse_atom()

    def _parse_nary(self, name: str, cls: type[And] | type[Or]) -> Expr:
        self.pos += len(name) + 1
        children: list[Expr] = []
        if self._peek() == ")":
            raise ExprSyntaxError(f"{name} requires at least one child", self.pos)
        while True:
            children.append(self.parse_expr())
            char = self._peek()
            if char == ")":
                self.pos += 1
                return cls(tuple(children))
            if self.text[self.pos : self.pos + 2] != ", ":
                raise ExprSyntaxError("Expected ', ' or ')'", self.pos)
            self.pos += 2

    def _parse_not(self) -> Expr:
        self.pos += 4
        child = self.parse_expr()
        if self._peek() != ")":
            raise ExprSyntaxError("Expected ')'", self.pos)
        self.pos += 1
        return Not(child)

    def _parse_atom(self) -> Atom:
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in ",)":
            self.pos += 1
        raw = self.text[start : self.pos]
        if not raw:
            raise ExprSyntaxError("Expected expression", start)

        qualifier = ""
        predicate_part = raw
        if raw.endswith("]"):
            bracket = raw.rfind("[")
            if bracket == -1:
                raise ExprSyntaxError("Unmatched qualifier bracket", start)
            qualifier = raw[bracket + 1 : -1]
            if qualifier == "":
                raise ExprSyntaxError("Empty qualifier", start + bracket + 1)
            predicate_part = raw[:bracket]

        separator = predicate_part.rfind(":")
        if separator <= 0 or separator == len(predicate_part) - 1:
            raise ExprSyntaxError("Expected atom as node_ref:PREDICATE", start)
        node_ref = predicate_part[:separator]
        predicate = predicate_part[separator + 1 :]
        if predicate not in PREDICATES:
            raise ExprSyntaxError(f"Unknown predicate {predicate!r}", start + separator + 1)
        return Atom(node_ref, predicate, qualifier)

    def _peek(self) -> str:
        if self.pos >= len(self.text):
            raise ExprSyntaxError("Unexpected end of input", self.pos)
        return self.text[self.pos]
