"""受限规则表达式语言（DSL）。

规则作者写的是示例风格表达式，如：

    stay_days >= 3
    stopovers <= 1 and transfers <= 2
    component.rbd in ["Y", "B"]
    components_count == 1

实现方式：Python ast 解析后按节点白名单解释执行，不暴露内建函数、
不允许属性逃逸、不允许调用任意函数，因此不是 eval() 沙箱，而是 AST 遍历器。
"""
from __future__ import annotations

import ast
import operator
from typing import Any

_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}

_UNARY_OPS = {ast.Not: operator.not_, ast.USub: operator.neg, ast.UAdd: operator.pos}

# 只读工具函数，仅作用于规则上下文里的普通数据。
_ALLOWED_FUNCS = {
    "len": len,
    "min": min,
    "max": max,
    "any": any,
    "all": all,
    "abs": abs,
}

_MAX_EXPRESSION_NODES = 400


class RuleSyntaxError(Exception):
    """表达式不在白名单语法内。"""


class RuleContextError(Exception):
    """表达式引用了上下文中不存在的名字。"""


class _Evaluator:
    def __init__(self, context: dict[str, Any]):
        self.context = context
        self.nodes_seen = 0

    def evaluate(self, expression: str) -> Any:
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise RuleSyntaxError(f"表达式语法错误: {exc.msg}") from exc
        return self._eval(tree.body)

    def _eval(self, node: ast.AST) -> Any:
        self.nodes_seen += 1
        if self.nodes_seen > _MAX_EXPRESSION_NODES:
            raise RuleSyntaxError("表达式过长")

        if isinstance(node, ast.BoolOp):
            values = [self._eval(v) for v in node.values]
            if isinstance(node.op, ast.And):
                result = True
                for v in values:
                    result = result and v
                return bool(result)
            return bool(any(values))

        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in _UNARY_OPS:
                raise RuleSyntaxError(f"不支持的一元运算符 {op_type.__name__}")
            return _UNARY_OPS[op_type](self._eval(node.operand))

        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in _BIN_OPS:
                raise RuleSyntaxError(f"不支持的运算符 {op_type.__name__}")
            return _BIN_OPS[op_type](self._eval(node.left), self._eval(node.right))

        if isinstance(node, ast.Compare):
            left = self._eval(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval(comparator)
                op_type = type(op)
                if op_type not in _COMPARE_OPS:
                    raise RuleSyntaxError(
                        f"不支持的比较 {op_type.__name__}"
                    )
                # null 安全：None 只与 == / != 比较，其它有序比较一律视为 False。
                # 这样 `stay_days == None or stay_days >= 3` 才能按短路求值。
                if left is None or right is None:
                    if op_type in (ast.Eq, ast.NotEq):
                        matched = (left is None and right is None)
                        if op_type is ast.NotEq:
                            matched = not matched
                        if not matched:
                            return False
                        left = right
                        continue
                    return False
                if not _COMPARE_OPS[op_type](left, right):
                    return False
                left = right
            return True

        if isinstance(node, ast.IfExp):
            return self._eval(node.body) if self._eval(node.test) else self._eval(
                node.orelse
            )

        if isinstance(node, ast.Constant):
            if isinstance(node.value, (bool, int, float, str)) or node.value is None:
                return node.value
            raise RuleSyntaxError("不支持的常量类型")

        if isinstance(node, ast.List):
            return [self._eval(e) for e in node.elts]

        if isinstance(node, ast.Tuple):
            return tuple(self._eval(e) for e in node.elts)

        if isinstance(node, ast.Name):
            if node.id in self.context:
                return self.context[node.id]
            raise RuleContextError(f"上下文中没有变量 {node.id}")

        if isinstance(node, ast.Attribute):
            # 只允许在上下文字典里做 dotted 读取，杜绝 __class__ 之类逃逸。
            value = self._eval(node.value)
            if isinstance(value, dict) and node.attr in value:
                return value[node.attr]
            raise RuleContextError(f"无法读取属性 {node.attr}")

        if isinstance(node, ast.Subscript):
            value = self._eval(node.value)
            key = self._eval(node.slice)
            try:
                return value[key]
            except (KeyError, IndexError, TypeError) as exc:
                raise RuleContextError(f"下标取值失败: {exc}") from exc

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                raise RuleSyntaxError("只允许白名单内的工具函数")
            if node.keywords:
                raise RuleSyntaxError("工具函数不接受关键字参数")
            args = [self._eval(a) for a in node.args]
            return _ALLOWED_FUNCS[node.func.id](*args)

        raise RuleSyntaxError(f"不支持的语法节点: {type(node).__name__}")


def evaluate(expression: str, context: dict[str, Any]) -> Any:
    """在给定上下文里求一条表达式。抛出 RuleSyntaxError/RuleContextError。"""
    return _Evaluator(context).evaluate(expression)


def evaluate_bool(expression: str, context: dict[str, Any]) -> bool:
    return bool(evaluate(expression, context))
