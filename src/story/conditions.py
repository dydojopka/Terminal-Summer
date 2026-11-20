"""Ограниченные условия DSL: без eval, Python-вызовов и арифметики."""

from __future__ import annotations

import ast
import operator
import re
from functools import lru_cache

TOKEN_RE = re.compile(
    r"\s*(?:\$[a-zA-Z_][a-zA-Z0-9_.]*|true\b|false\b|null\b|-?\d+"
    r"|==|!=|<=|>=|&&|\|\||[()!<>])", re.IGNORECASE,
)
VARIABLE_RE = re.compile(r"\$([a-zA-Z_][a-zA-Z0-9_.]*)")
COMPARISONS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne,
    ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge,
}


@lru_cache(maxsize=512)
def _condition_tree(expression: str) -> ast.Expression:
    source = expression.strip()
    cursor = 0
    while cursor < len(source):
        match = TOKEN_RE.match(source, cursor)
        if match is None:
            raise ValueError(f"Invalid condition token at column {cursor + 1}: {source[cursor:]}")
        cursor = match.end()
    translated = VARIABLE_RE.sub(lambda m: f'V("{m[1]}")', source)
    translated = translated.replace("&&", " and ").replace("||", " or ")
    translated = re.sub(r"!(?!=)", " not ", translated)
    for literal, python_literal in (("true", "True"), ("false", "False"), ("null", "None")):
        translated = re.sub(rf"\b{literal}\b", python_literal, translated, flags=re.I)
    try:
        return ast.parse(translated.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid condition syntax: {exc.msg}") from exc


def parse_script_condition(expression: str, state_types: dict) -> ast.Expression:
    """Проверяет каждую ветку выражения, даже если она short-circuited."""
    tree = _condition_tree(expression)

    def types(node: ast.AST) -> tuple[type, ...]:
        if isinstance(node, ast.Constant) and type(node.value) in (bool, int, type(None)):
            return (type(node.value),)
        if isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Name) and node.func.id == "V"
            and len(node.args) == 1 and not node.keywords
            and isinstance(node.args[0], ast.Constant) and type(node.args[0].value) is str
        ):
            name = node.args[0].value
            if name not in state_types:
                raise ValueError(f"Unknown script variable: ${name}")
            return state_types[name]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and (
            isinstance(node.operand, ast.Constant) and type(node.operand.value) is int
        ):
            return (int,)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            types(node.operand)
            return (bool,)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            for item in node.values:
                types(item)
            return (bool,)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = types(node.left), types(node.comparators[0])
            comparison = node.ops[0]
            if type(comparison) not in COMPARISONS:
                raise ValueError("Unsupported comparison operator")
            if isinstance(comparison, (ast.Eq, ast.NotEq)):
                if not set(left).intersection(right):
                    raise ValueError("Incompatible comparison types (bool is not int)")
            elif int not in left or int not in right or bool in left or bool in right:
                raise ValueError("Ordered comparison requires integers")
            return (bool,)
        raise ValueError(f"Unsupported condition syntax: {type(node).__name__}")

    types(tree.body)
    return tree


def evaluate_script_condition(expression: str, state: dict, state_types: dict) -> bool:
    tree = parse_script_condition(expression, state_types)

    def value(node: ast.AST):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Call):
            name = node.args[0].value
            if name not in state:
                raise ValueError(f"Missing script variable: ${name}")
            result = state[name]
            if type(result) not in state_types[name]:
                raise ValueError(f"Invalid condition value for ${name}: {type(result).__name__}")
            return result
        if isinstance(node, ast.UnaryOp):
            return not value(node.operand) if isinstance(node.op, ast.Not) else -value(node.operand)
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(bool(value(item)) for item in node.values)
            return any(bool(value(item)) for item in node.values)
        if isinstance(node, ast.Compare):
            try:
                return COMPARISONS[type(node.ops[0])](value(node.left), value(node.comparators[0]))
            except TypeError as exc:
                raise ValueError(f"Invalid comparison values: {exc}") from exc
        raise ValueError(f"Unsupported condition syntax: {type(node).__name__}")

    return bool(value(tree.body))
