"""把 Decimal 序列化为字符串的 JSON 渲染器。

前端（JS Number 是 IEEE-754 双精度）不能直接承载精确金额，因此所有金额
字段都以字符串下发；客户端做分位显示与 Decimal 级运算时自行用 decimal.js
之类的库。
"""
from decimal import Decimal

from rest_framework.renderers import JSONRenderer


class DecimalStringJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        return super().render(
            _stringify_decimals(data),
            accepted_media_type=accepted_media_type,
            renderer_context=renderer_context,
        )


def _stringify_decimals(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _stringify_decimals(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stringify_decimals(v) for v in value]
    return value
