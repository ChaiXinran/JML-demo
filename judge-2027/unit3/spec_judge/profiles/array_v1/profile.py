"""Snapshots for the independent array contract exercises."""

from __future__ import annotations

from core.profile import ArrayValue, ProfileError, typed_point_value


class ArrayProfile:
    name = "array_v1"
    extended_jml = True
    allowed_calls = frozenset()
    symbols = {}
    stateful_calls = frozenset()
    smt_type_aliases = {}
    smt_identity_calls = {}
    smt_axioms = ()

    def state_variables_for(self, method_name):
        return {"occupied": "bool[]"} if method_name == "reserveSeats" else {}

    def state_name(self, name, state):
        if name != "occupied" or not isinstance(state, ArrayValue):
            raise ProfileError("观察点缺少已声明的座位数组")
        return state

    def state_from_data(self, data, base=None):
        if set(data) - {"occupied", "fresh", "use", "copy"}:
            raise ProfileError("数组状态只支持 occupied、fresh、use 和 copy")
        fresh = data.get("fresh", False)
        if type(fresh) is not bool or (fresh and (data.get("copy") != "pre" or "occupied" not in data)):
            raise ProfileError("fresh 只能随显式的后态数组及 copy: pre 使用")
        if "occupied" not in data:
            return base
        identity = "occupied.fresh" if fresh else "occupied"
        value = typed_point_value(data["occupied"], "bool[]", identity)
        if value is None:
            raise ProfileError("occupied 状态必须是非 null 数组")
        if data.get("copy") == "pre" and base is not None and not fresh and len(value.values) != len(base.values):
            raise ProfileError("同一个数组的前后态长度必须相同")
        return value

    def evaluate_call(self, name, values, context):
        raise ProfileError("独立 JML 题不支持调用 Java 方法")

    def post_variants(self, rule, pre, arguments):
        raise ProfileError("数组 Suite 请显式配置带 result 的后态")


DEFAULT_PROFILE = ArrayProfile()
