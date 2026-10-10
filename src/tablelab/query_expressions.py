"""Small, non-executing grammars for arithmetic and grouped filter conditions."""
import ast
import operator
import re
from functools import reduce


_OPERATIONS = {ast.Add: ('+', operator.add), ast.Sub: ('-', operator.sub),
               ast.Mult: ('*', operator.mul), ast.Div: ('/', operator.truediv),
               ast.FloorDiv: ('//', operator.floordiv), ast.Mod: ('%', operator.mod)}


def arithmetic_code(expression, columns, variable='source'):
    try:
        tree = ast.parse(expression, mode='eval')
    except SyntaxError as exc:
        raise ValueError('Enter a valid arithmetic expression.') from exc
    if sum(1 for _ in ast.walk(tree)) > 100:
        raise ValueError('The arithmetic expression is too long.')

    def column_code(column):
        if column not in columns:
            raise ValueError(f'Unknown column: {column!r}')
        return f'{variable}[{column!r}]'

    def visit(node):
        if isinstance(node, ast.Name):
            return column_code(node.id)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return repr(node.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'col':
            if len(node.args) == 1 and not node.keywords and isinstance(node.args[0], ast.Constant):
                if type(node.args[0].value) in (str, int):
                    return column_code(node.args[0].value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATIONS:
            return f'({visit(node.left)} {_OPERATIONS[type(node.op)][0]} {visit(node.right)})'
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            sign = '+' if isinstance(node.op, ast.UAdd) else '-'
            return f'({sign}{visit(node.operand)})'
        raise ValueError("Use columns, numbers, parentheses, +, -, *, /, //, or %. "
                         "Use col('column name') for names with spaces.")
    return visit(tree.body)


def arithmetic_value(expression, df):
    code = arithmetic_code(expression, df.columns)
    def visit(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Subscript):
            return df[node.slice.value]
        if isinstance(node, ast.BinOp):
            return _OPERATIONS[type(node.op)][1](visit(node.left), visit(node.right))
        return (operator.neg if isinstance(node.op, ast.USub) else operator.pos)(visit(node.operand))
    return visit(ast.parse(code, mode='eval').body)


def condition_tree(expression, count, mode):
    if not expression.strip():
        expression = (' and ' if mode == 'and' else ' or ').join(str(i + 1) for i in range(count))
    expression = re.sub(r'\b(AND|OR)\b', lambda match: match[0].lower(), expression, flags=re.I)
    try:
        tree = ast.parse(expression.strip(), mode='eval').body
    except SyntaxError as exc:
        raise ValueError('Combine condition numbers using AND, OR, and parentheses.') from exc
    if sum(1 for _ in ast.walk(tree)) > 100:
        raise ValueError('The condition expression is too long.')
    def validate(node):
        if isinstance(node, ast.Constant) and type(node.value) is int and 1 <= node.value <= count:
            return
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            for value in node.values:
                validate(value)
            return
        raise ValueError(f'Use condition numbers 1–{count}, AND, OR, and parentheses.')
    validate(tree)
    return tree


def combine_code(tree):
    if isinstance(tree, ast.Constant):
        return f'masks[{tree.value - 1}]'
    symbol = ' & ' if isinstance(tree.op, ast.And) else ' | '
    return '(' + symbol.join(combine_code(value) for value in tree.values) + ')'


def combine_masks(tree, masks):
    if isinstance(tree, ast.Constant):
        return masks[tree.value - 1]
    operation = operator.and_ if isinstance(tree.op, ast.And) else operator.or_
    return reduce(operation, (combine_masks(value, masks) for value in tree.values))
