from __future__ import annotations

import re
from dataclasses import dataclass

from stonebranch_graph import expr
from stonebranch_graph.skeleton import logical_leaf

_DEPENDENCY_PREDICATES = {
    "s": expr.SUCCESS,
    "success": expr.SUCCESS,
    "f": expr.FAILURE,
    "failure": expr.FAILURE,
    "d": expr.DONE,
    "done": expr.DONE,
    "t": expr.TERMINATED,
    "terminated": expr.TERMINATED,
    "n": expr.NOT_RUNNING,
    "notrunning": expr.NOT_RUNNING,
}
_VARIABLE_FUNCTIONS = {"v", "value"}
_COMPARE_OPS = ("==", "!=", "<=", ">=", "=", "<", ">")


class JilConditionError(ValueError):
    """JIL condition parser error carrying the character position."""

    def __init__(
        self,
        message: str,
        position: int,
        warnings: tuple[str, ...] = (),
    ) -> None:
        self.message = message
        self.position = position
        self.warnings = warnings
        super().__init__(f"{message} at position {position}")


@dataclass(frozen=True)
class ParsedJilCondition:
    expression: expr.Expr
    atom_names: dict[tuple[str, str, str], str]
    warnings: tuple[str, ...] = ()


def parse_jil_condition(text: str) -> expr.Expr:
    """Parse an AutoSys JIL condition string into a canonical expression tree."""

    return parse_jil_condition_details(text).expression


def parse_jil_condition_details(text: str, *, job_name: str = "") -> ParsedJilCondition:
    """Parse a JIL condition and retain raw atom names for legacy graph edges."""

    parser = _Parser(text, job_name=job_name)
    try:
        parsed = parser.parse()
    except JilConditionError as exc:
        if parser.warnings and not exc.warnings:
            raise JilConditionError(exc.message, exc.position, tuple(parser.warnings)) from exc
        raise
    return ParsedJilCondition(
        expression=parsed,
        atom_names=dict(parser.atom_names),
        warnings=tuple(parser.warnings),
    )


class _Parser:
    def __init__(self, text: str, *, job_name: str) -> None:
        self.text = text
        self.pos = 0
        self.job_name = job_name or "<unknown>"
        self.atom_names: dict[tuple[str, str, str], str] = {}
        self.warnings: list[str] = []

    def parse(self) -> expr.Expr:
        parsed = self._parse_or()
        self._skip_ws()
        if self.pos != len(self.text):
            raise JilConditionError("Unexpected trailing input", self.pos)
        if parsed is None:
            raise JilConditionError("No dependency atoms found", 0, tuple(self.warnings))
        return expr.canonicalize(parsed)

    def _parse_or(self) -> expr.Expr | None:
        children = [self._parse_and()]
        while True:
            self._skip_ws()
            if self._consume_char("|") or self._consume_word("OR"):
                children.append(self._parse_and())
                continue
            return self._combine(expr.Or, children)

    def _parse_and(self) -> expr.Expr | None:
        children = [self._parse_term()]
        while True:
            self._skip_ws()
            if self._consume_char("&") or self._consume_word("AND"):
                children.append(self._parse_term())
                continue
            return self._combine(expr.And, children)

    def _parse_term(self) -> expr.Expr | None:
        self._skip_ws()
        if self._consume_char("!") or self._consume_word("NOT"):
            child = self._parse_term()
            return expr.Not(child) if child is not None else None
        return self._parse_primary()

    def _parse_primary(self) -> expr.Expr | None:
        self._skip_ws()
        if self.pos >= len(self.text):
            raise JilConditionError("Expected expression", self.pos)

        if self._consume_char("("):
            parsed = self._parse_or()
            self._skip_ws()
            if not self._consume_char(")"):
                raise JilConditionError("Expected ')'", self.pos)
            return parsed

        name_start = self.pos
        function_name = self._read_identifier()
        if not function_name:
            raise JilConditionError("Expected function name", self.pos)
        self._skip_ws()
        if not self._consume_char("("):
            raise JilConditionError("Expected '(' after function name", self.pos)
        args = self._read_call_args(name_start)
        return self._function_expr(function_name, args, name_start)

    def _function_expr(
        self, function_name: str, args: list[tuple[str, int]], position: int
    ) -> expr.Expr | None:
        normalized_function = function_name.lower()
        if normalized_function in _DEPENDENCY_PREDICATES:
            return self._dependency_expr(normalized_function, args, position)
        if normalized_function == "exitcode":
            return self._exitcode_expr(args, position)
        self._consume_optional_comparison_value()
        if normalized_function in _VARIABLE_FUNCTIONS:
            variable_name = _clean_arg(args[0][0]) if args else "<missing>"
            self.warnings.append(
                f"JIL condition ignored variable condition for job {self.job_name}: "
                f"{variable_name}"
            )
            return None
        self.warnings.append(
            f"JIL condition ignored unknown function for job {self.job_name}: {function_name}"
        )
        return None

    def _dependency_expr(
        self, function_name: str, args: list[tuple[str, int]], position: int
    ) -> expr.Atom:
        if not args or len(args) > 2:
            raise JilConditionError(
                f"{function_name}() expects one name and optional lookback", position
            )
        raw_name = _clean_arg(args[0][0])
        if not raw_name:
            raise JilConditionError("Empty dependency name", args[0][1])
        qualifier = _normalize_lookback(args[1][0], args[1][1]) if len(args) == 2 else ""
        atom = expr.Atom(_node_ref(raw_name), _DEPENDENCY_PREDICATES[function_name], qualifier)
        self.atom_names.setdefault(_atom_key(atom), raw_name)
        return atom

    def _exitcode_expr(self, args: list[tuple[str, int]], position: int) -> expr.Atom:
        if len(args) != 1:
            raise JilConditionError("exitcode() expects one job name", position)
        raw_name = _clean_arg(args[0][0])
        if not raw_name:
            raise JilConditionError("Empty exitcode job name", args[0][1])

        self._skip_ws()
        op = self._consume_compare_op()
        if not op:
            raise JilConditionError("Expected exitcode comparison operator", self.pos)
        self._skip_ws()
        number_start = self.pos
        if self._peek() in {"+", "-"}:
            self.pos += 1
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1
        if self.pos == number_start or self.text[number_start : self.pos] in {"+", "-"}:
            raise JilConditionError("Expected integer exitcode value", number_start)

        normalized_op = "=" if op == "==" else op
        atom = expr.Atom(
            _node_ref(raw_name),
            expr.EXIT,
            f"{normalized_op}{self.text[number_start:self.pos]}",
        )
        self.atom_names.setdefault(_atom_key(atom), raw_name)
        return atom

    def _read_call_args(self, function_start: int) -> list[tuple[str, int]]:
        args: list[tuple[str, int]] = []
        start = self.pos
        quote = ""
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if quote:
                if char == quote:
                    quote = ""
                self.pos += 1
                continue
            if char in {"'", '"'}:
                quote = char
                self.pos += 1
                continue
            if char == ",":
                args.append((self.text[start : self.pos].strip(), start))
                self.pos += 1
                start = self.pos
                continue
            if char == ")":
                args.append((self.text[start : self.pos].strip(), start))
                self.pos += 1
                return [arg for arg in args if arg[0] != ""]
            self.pos += 1
        raise JilConditionError("Unclosed function call", function_start)

    def _read_identifier(self) -> str:
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", self.text[self.pos :])
        if not match:
            return ""
        self.pos += match.end()
        return match.group(0)

    def _consume_optional_comparison_value(self) -> None:
        checkpoint = self.pos
        self._skip_ws()
        if not self._consume_compare_op():
            self.pos = checkpoint
            return
        quote = ""
        depth = 0
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if quote:
                if char == quote:
                    quote = ""
                self.pos += 1
                continue
            if char in {"'", '"'}:
                quote = char
                self.pos += 1
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    return
                depth -= 1
            elif depth == 0 and char in {"&", "|"}:
                return
            self.pos += 1

    def _consume_compare_op(self) -> str:
        for op in _COMPARE_OPS:
            if self.text.startswith(op, self.pos):
                self.pos += len(op)
                return op
        return ""

    def _consume_word(self, word: str) -> bool:
        self._skip_ws()
        end = self.pos + len(word)
        if self.text[self.pos : end].upper() != word:
            return False
        before_ok = self.pos == 0 or not _is_word_char(self.text[self.pos - 1])
        after_ok = end == len(self.text) or not _is_word_char(self.text[end])
        if not before_ok or not after_ok:
            return False
        self.pos = end
        return True

    def _consume_char(self, char: str) -> bool:
        self._skip_ws()
        if self._peek() == char:
            self.pos += 1
            return True
        return False

    def _skip_ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _peek(self) -> str:
        if self.pos >= len(self.text):
            return ""
        return self.text[self.pos]

    def _combine(
        self, cls: type[expr.And] | type[expr.Or], children: list[expr.Expr | None]
    ) -> expr.Expr | None:
        kept = tuple(child for child in children if child is not None)
        if not kept:
            return None
        if len(kept) == 1:
            return kept[0]
        return cls(kept)


def _node_ref(raw_name: str) -> str:
    if "^" not in raw_name:
        return logical_leaf(raw_name)
    job_name, instance = raw_name.split("^", 1)
    return f"ext:{instance}/{logical_leaf(job_name)}"


def _normalize_lookback(raw_value: str, position: int) -> str:
    value = raw_value.strip()
    if re.fullmatch(r"\d+", value):
        return f"{int(value):02d}:00"
    match = re.fullmatch(r"(\d+)[.:](\d{1,2})", value)
    if match:
        return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"
    raise JilConditionError("Invalid lookback window", position)


def _clean_arg(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return text


def _atom_key(atom: expr.Atom) -> tuple[str, str, str]:
    return (atom.node_ref, atom.predicate, atom.qualifier)


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"
