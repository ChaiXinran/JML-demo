"""Finite network semantics used by the current followUser exercise."""

from __future__ import annotations

import copy
import dataclasses
from typing import Any, Mapping, Sequence

from core.profile import EvaluationContext, ProfileError, Scenario, SymbolSignature


@dataclasses.dataclass
class NetworkState:
    users: set[int]
    following: dict[int, set[int]]
    followers: dict[int, set[int]]
    blocked: dict[int, set[int]] = dataclasses.field(default_factory=dict)

    def copy(self) -> "NetworkState":
        return copy.deepcopy(self)

    def follows(self, first: int, second: int) -> bool:
        return second in self.following.get(first, set())

    def is_follower(self, user: int, follower: int) -> bool:
        return follower in self.followers.get(user, set())

    def is_blocked(self, user: int, other: int) -> bool:
        return other in self.blocked.get(user, set())


@dataclasses.dataclass(frozen=True)
class NetworkUserRef:
    user_id: int


def _state(users: set[int], edges: set[tuple[int, int]] | None = None) -> NetworkState:
    edges = set() if edges is None else edges
    following = {user: set() for user in users}
    followers = {user: set() for user in users}
    for first, second in edges:
        following.setdefault(first, set()).add(second)
        followers.setdefault(second, set()).add(first)
    return NetworkState(
        set(users), following, followers, {user: set() for user in users}
    )


class NetworkV1Profile:
    name = "network_v1"
    contract_shape = {"requires": 1, "ensures": 2, "signals": 4}
    grading = {"applicability": 1, "postcondition": 2, "exceptions": 4, "locked": 1}
    diagnostics = {
        "applicability": {
            "location": "NORMAL_CONDITION",
            "category": "正常行为条件",
            "observation": "存在前态使你的正常行为条件与标准合同的行为分类不一致。",
            "guidance": "检查正常执行是否同时排除了缺失用户、自关注和重复关注。",
        },
        "postcondition": {
            "category": "后置状态关系",
            "observation": "某个成功后的抽象状态被你的后置条件错误接受或拒绝。",
            "guidance": "核对关注关系的方向，以及该条件描述的是关注还是粉丝关系。",
            "slots": ["FORWARD_POSTCONDITION", "INVERSE_POSTCONDITION"],
        },
        "exceptions": {
            "category": "异常分支与优先级",
            "observation": "该异常分支在某些前态下的匹配结果或异常类型与标准合同不一致。",
            "guidance": "检查该分支是否覆盖了自己的情形，并正确排除了更早的异常情形。",
            "slots": [
                "FIRST_USER_MISSING", "SECOND_USER_MISSING", "SELF_FOLLOW",
                "DUPLICATE_FOLLOW",
            ],
        },
    }
    allowed_calls = frozenset(
        {"containsUser", "getUser", "isFollowing", "containsFollower", "isBlocked"}
    )
    symbols = {
        "containsUser": (SymbolSignature(("int",), "bool"),),
        "getUser": (SymbolSignature(("int",), "UserRef"),),
        "isFollowing": (SymbolSignature(("UserRef", "UserRef"), "bool"),),
        "containsFollower": (SymbolSignature(("UserRef", "UserRef"), "bool"),),
        "isBlocked": (SymbolSignature(("UserRef", "UserRef"), "bool"),),
    }
    stateful_calls = frozenset(
        {"containsUser", "isFollowing", "containsFollower", "isBlocked"}
    )
    smt_type_aliases = {"UserRef": "int"}
    smt_identity_calls = {"getUser": 0}
    smt_axioms = tuple(
        expression
        for first, second in (("id1", "id1"), ("id1", "id2"), ("id2", "id1"), ("id2", "id2"))
        for expression in (
            f"!isFollowing(getUser({first}), getUser({second})) || "
            f"(containsUser({first}) && containsUser({second}))",
            f"!containsFollower(getUser({first}), getUser({second})) || "
            f"(containsUser({first}) && containsUser({second}))",
            f"containsFollower(getUser({first}), getUser({second})) == "
            f"isFollowing(getUser({second}), getUser({first}))",
            f"!isBlocked(getUser({first}), getUser({second})) || "
            f"(containsUser({first}) && containsUser({second}))",
        )
    )

    def parameter_types(self, method_name: str) -> Mapping[str, str]:
        if method_name not in {"followUser", "canInteract"}:
            raise ProfileError(f"network_v1 尚未配置方法 {method_name}")
        return {"id1": "int", "id2": "int"}

    def evaluate_call(
        self, name: str, values: Sequence[Any], context: EvaluationContext
    ) -> Any:
        state = context.current
        if not isinstance(state, NetworkState):
            raise ProfileError("network_v1 收到了不兼容的抽象状态")
        if name == "containsUser" and len(values) == 1:
            return int(values[0]) in state.users
        if name == "getUser" and len(values) == 1:
            return NetworkUserRef(int(values[0]))
        if name == "isFollowing" and len(values) == 2 and all(
            isinstance(value, NetworkUserRef) for value in values
        ):
            return state.follows(values[0].user_id, values[1].user_id)
        if name == "containsFollower" and len(values) == 2 and all(
            isinstance(value, NetworkUserRef) for value in values
        ):
            return state.is_follower(values[0].user_id, values[1].user_id)
        if name == "isBlocked" and len(values) == 2 and all(
            isinstance(value, NetworkUserRef) for value in values
        ):
            return state.is_blocked(values[0].user_id, values[1].user_id)
        raise ProfileError(f"函数 {name} 的参数不符合 network_v1 受限语法")

    def state_from_data(
        self, data: Mapping[str, Any], base: NetworkState | None = None
    ) -> NetworkState:
        allowed_fields = {"use", "copy", "users", "following", "followers", "blocked", "add", "remove"}
        unknown = set(data) - allowed_fields
        if unknown:
            raise ProfileError(f"network_v1 不支持状态字段 {sorted(unknown)}")
        state = _state(set()) if base is None else base.copy()
        if "users" in data:
            state.users = {int(value) for value in data["users"]}
            state.following = {user: set() for user in state.users}
            state.followers = {user: set() for user in state.users}
            state.blocked = {user: set() for user in state.users}
        for relation in ("following", "followers", "blocked"):
            if relation in data:
                table = {user: set() for user in state.users}
                for edge in data[relation]:
                    if not isinstance(edge, (list, tuple)) or len(edge) != 2:
                        raise ProfileError(f"关系 {relation} 的边必须是二元数组")
                    first, second = map(int, edge)
                    if first not in state.users or second not in state.users:
                        raise ProfileError(f"关系 {relation} 的端点必须出现在 users 中")
                    table.setdefault(first, set()).add(second)
                setattr(state, relation, table)
        for operation in ("add", "remove"):
            changes = data.get(operation, {})
            if not isinstance(changes, Mapping):
                raise ProfileError(f"状态补丁 {operation} 必须是对象")
            for relation, edges in changes.items():
                if relation not in {"following", "followers", "blocked"}:
                    raise ProfileError(f"network_v1 不支持关系 {relation}")
                table = getattr(state, relation)
                for edge in edges:
                    if not isinstance(edge, (list, tuple)) or len(edge) != 2:
                        raise ProfileError(f"关系 {relation} 的边必须是二元数组")
                    first, second = map(int, edge)
                    if first not in state.users or second not in state.users:
                        raise ProfileError(f"关系 {relation} 的端点必须出现在 users 中")
                    bucket = table.setdefault(first, set())
                    if operation == "add":
                        bucket.add(second)
                    else:
                        bucket.discard(second)
        return state

    def state_data_from_smt_calls(
        self, calls: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        users: set[int] = set()
        relations = {"following": set(), "followers": set(), "blocked": set()}
        call_to_relation = {
            "isFollowing": "following",
            "containsFollower": "followers",
            "isBlocked": "blocked",
        }
        for call in calls:
            name = call["name"]
            arguments = [int(value) for value in call["args"]]
            if name == "containsUser" and call["result"]:
                users.add(arguments[0])
            elif name in call_to_relation and call["result"]:
                users.update(arguments)
                relations[call_to_relation[name]].add(tuple(arguments))
        return {
            "users": sorted(users),
            **{
                name: [list(edge) for edge in sorted(edges)]
                for name, edges in relations.items()
            },
        }

    def post_variants(
        self, rule: str, pre: NetworkState, arguments: Mapping[str, Any]
    ) -> Mapping[str, NetworkState]:
        if rule != "follow_pair":
            raise ProfileError(f"network_v1 不支持后态变异规则 {rule}")
        if not isinstance(pre, NetworkState):
            raise ProfileError("follow_pair 需要网络前态")
        try:
            first, second = arguments["id1"], arguments["id2"]
        except KeyError as error:
            raise ProfileError("follow_pair 需要 id1 和 id2 参数") from error
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in (first, second)):
            raise ProfileError("follow_pair 参数必须是整数")
        if first not in pre.users or second not in pre.users or first == second or pre.follows(first, second):
            raise ProfileError("follow_pair 需要两个不同且尚未建立关注关系的现有用户")

        def changed(*, forward=False, inverse=False, reverse=False) -> NetworkState:
            state = pre.copy()
            if forward:
                state.following[first].add(second)
            if inverse:
                state.followers[second].add(first)
            if reverse:
                state.following[second].add(first)
                state.followers[first].add(second)
            return state

        result = {
            "correct": changed(forward=True, inverse=True),
            "omit_forward": changed(inverse=True),
            "omit_inverse": changed(forward=True),
            "reverse_direction": changed(reverse=True),
        }
        unrelated = result["correct"].copy()
        unrelated.blocked.setdefault(first, set()).add(second)
        result["unrelated_change"] = unrelated
        prior_edges = sorted(
            (source, target)
            for source, targets in pre.following.items()
            for target in targets
            if (source, target) != (first, second)
        )
        if prior_edges:
            source, target = prior_edges[0]
            wrong_delete = result["correct"].copy()
            wrong_delete.following[source].discard(target)
            wrong_delete.followers[target].discard(source)
            result["wrong_delete"] = wrong_delete
        return result

    def pre_scenarios(self, method_name: str) -> list[Scenario]:
        self._require_follow_user(method_name)
        steady = _state({1, 2, 3}, {(3, 1)})
        return [
            Scenario(steady, steady.copy(), {"id1": 1, "id2": 2}),
            Scenario(_state(set()), _state(set()), {"id1": 1, "id2": 2}),
            Scenario(_state({2}), _state({2}), {"id1": 1, "id2": 2}),
            Scenario(_state({1}), _state({1}), {"id1": 1, "id2": 2}),
            Scenario(_state(set()), _state(set()), {"id1": 1, "id2": 1}),
            Scenario(_state({1}), _state({1}), {"id1": 1, "id2": 1}),
            Scenario(_state({1}, {(1, 1)}), _state({1}, {(1, 1)}), {"id1": 1, "id2": 1}),
            Scenario(_state({1, 2}), _state({1, 2}, {(1, 2)}), {"id1": 1, "id2": 2}),
            Scenario(_state({1, 2}), _state({1, 2}), {"id1": 1, "id2": 2}),
        ]

    def post_scenarios(self, method_name: str) -> list[Scenario]:
        self._require_follow_user(method_name)
        pre = _state({1, 2, 3}, {(3, 1)})
        correct = _state({1, 2, 3}, {(3, 1), (1, 2)})
        only_following = _state({1, 2, 3}, {(3, 1), (1, 2)})
        only_following.followers[2].remove(1)
        only_followers = _state({1, 2, 3}, {(3, 1)})
        only_followers.followers[2].add(1)
        reversed_relation = _state({1, 2, 3}, {(3, 1), (2, 1)})
        return [
            Scenario(pre, correct, {"id1": 1, "id2": 2}),
            Scenario(pre, only_following, {"id1": 1, "id2": 2}),
            Scenario(pre, only_followers, {"id1": 1, "id2": 2}),
            Scenario(pre, reversed_relation, {"id1": 1, "id2": 2}),
        ]

    @staticmethod
    def _require_follow_user(method_name: str) -> None:
        if method_name != "followUser":
            raise ProfileError(f"network_v1 尚未配置方法 {method_name}")


DEFAULT_PROFILE = NetworkV1Profile()
