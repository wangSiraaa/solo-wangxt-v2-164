"""
规则表达式安全求值器（培训沙箱）。

不是 eval()：用 Python ast 白名单解析，只允许比较、布尔、算术、in、
列表/数值/字符串字面量与上下文中的名字。规则作者无法调用函数或访问属性。

示例表达式：
    min_layover_minutes >= 45 and max_layover_minutes < 1440
    stopover_count <= 1 and stopover_count >= 0
    stay_days >= 3 and stay_days <= 30
    date_change_count == 0
    booking_class in ['M', 'H', 'Q']
    has_saturday_night == true
"""

import ast
import operator

_COMPARE = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_BOOL = {ast.And: all, ast.Or: any}

_UNARY = {ast.Not: operator.not_, ast.USub: operator.neg}

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}


class RuleSyntaxError(Exception):
    pass


class RuleContextError(Exception):
    pass


def _literal(node):
    try:
        return ast.literal_eval(node)
    except ValueError as exc:
        raise RuleSyntaxError(f'不支持的字面量: {ast.dump(node)}') from exc


def _eval(node, ctx):
    if isinstance(node, ast.Expression):
        return _eval(node.body, ctx)

    if isinstance(node, ast.BoolOp):
        reducer = _BOOL[type(node.op)]
        return reducer(_eval(v, ctx) for v in node.values)

    if isinstance(node, ast.UnaryOp):
        return _UNARY[type(node.op)](_eval(node.operand, ctx))

    if isinstance(node, ast.BinOp):
        return _BIN[type(node.op)](_eval(node.left, ctx), _eval(node.right, ctx))

    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, ctx)
            if type(op) not in _COMPARE:
                raise RuleSyntaxError('只允许 == != < <= > >= in/not in 比较')
            if not _COMPARE[type(op)](left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal(n) if isinstance(n, (ast.List, ast.Tuple))
                else _eval(n, ctx) for n in node.elts]

    if isinstance(node, ast.Name):
        # 规则里允许小写 true/false/null（更接近常见规则语言）
        aliases = {'true': True, 'false': False, 'null': None}
        if node.id in aliases:
            return aliases[node.id]
        if node.id not in ctx:
            raise RuleContextError(f'表达式引用了不存在的变量: {node.id}')
        return ctx[node.id]

    raise RuleSyntaxError(f'不允许的语法节点: {type(node).__name__}')


def evaluate(expression: str, context: dict):
    """返回 (bool, 是否求值成功, 错误信息)。"""
    try:
        tree = ast.parse(expression.strip(), mode='eval')
    except SyntaxError as exc:
        raise RuleSyntaxError(str(exc)) from exc
    # 二次确认：任何属性访问 / 调用 / 下标都不允许
    for node in ast.walk(tree):
        if isinstance(node, (ast.Attribute, ast.Call, ast.Subscript,
                             ast.Lambda, ast.comprehension,
                             ast.Import, ast.ImportFrom)):
            raise RuleSyntaxError(f'表达式中禁止 {type(node).__name__}')
    return bool(_eval(tree, context))
