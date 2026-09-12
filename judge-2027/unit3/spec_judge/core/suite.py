"""Load method suites and declarative test points.

Files currently use the JSON-compatible subset of YAML so the judge keeps its
standard-library-only installation.  They can later be parsed by a full YAML
loader without changing the schema.
"""

from __future__ import annotations

import dataclasses
import copy
import itertools
import json
from pathlib import Path
from typing import Any, Mapping

from .profile import EvaluationProfile, ProfileError, Scenario


@dataclasses.dataclass(frozen=True)
class LoadedSuite:
    name: str
    version: int
    method: str
    reference: Path
    profile: EvaluationProfile
    contract_shape: Mapping[str, Any]
    parameters: Mapping[str, str]
    grading: Mapping[str, int]
    diagnostics: Mapping[str, Any]
    quality: Mapping[str, Any]
    solver: Mapping[str, Any]
    pre_points: tuple[Scenario, ...]
    post_points: tuple[Scenario, ...]


@dataclasses.dataclass(frozen=True)
class _GeneratedPost:
    state: Any


@dataclasses.dataclass(frozen=True)
class SuiteProfile:
    """Bind declarative points to a reusable domain profile."""

    base: EvaluationProfile
    method: str
    configured_pre: tuple[Scenario, ...]
    configured_post: tuple[Scenario, ...]
    contract_shape: Mapping[str, Any]
    configured_parameters: Mapping[str, str]
    grading: Mapping[str, int]
    diagnostics: Mapping[str, Any]
    solver: Mapping[str, Any]
    suite_name: str
    suite_version: int
    guarantee_scope: str = "fixed_test_points"

    @property
    def name(self) -> str:
        return self.base.name

    @property
    def allowed_calls(self) -> frozenset[str]:
        return self.base.allowed_calls

    @property
    def symbols(self):
        return self.base.symbols

    @property
    def stateful_calls(self):
        return self.base.stateful_calls

    @property
    def smt_type_aliases(self):
        return self.base.smt_type_aliases

    @property
    def smt_identity_calls(self):
        return self.base.smt_identity_calls

    @property
    def smt_axioms(self):
        return self.base.smt_axioms

    def state_data_from_smt_calls(self, calls):
        return self.base.state_data_from_smt_calls(calls)

    def parameter_types(self, method_name: str) -> Mapping[str, str]:
        self._check_method(method_name)
        return self.configured_parameters

    def evaluate_call(self, name, values, context):
        return self.base.evaluate_call(name, values, context)

    def state_from_data(self, data, base=None):
        return self.base.state_from_data(data, base)

    def post_variants(self, rule, pre, arguments):
        return self.base.post_variants(rule, pre, arguments)

    def pre_scenarios(self, method_name: str) -> list[Scenario]:
        self._check_method(method_name)
        return list(self.configured_pre)

    def post_scenarios(self, method_name: str) -> list[Scenario]:
        self._check_method(method_name)
        return list(self.configured_post)

    def _check_method(self, method_name: str) -> None:
        if method_name != self.method:
            raise ProfileError(f"suite 配置的是 {self.method}，不能评测 {method_name}")


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ProfileError(
            f"{path} 必须使用 JSON 兼容的 YAML 语法：{error.msg}"
        ) from error
    if not isinstance(value, dict):
        raise ProfileError(f"{path} 的顶层必须是对象")
    return value


def _state(
    raw: Any,
    fixtures: Mapping[str, Any],
    profile: EvaluationProfile,
    pre: Any | None = None,
    resolving: tuple[str, ...] = (),
) -> Any:
    if not isinstance(raw, dict):
        raise ProfileError("测试点状态必须是对象")
    base = None
    if "use" in raw:
        name = raw["use"]
        if not isinstance(name, str):
            raise ProfileError("fixture 名称必须是字符串")
        if name not in fixtures:
            raise ProfileError(f"未知 fixture：{name}")
        if name in resolving:
            chain = " -> ".join((*resolving, name))
            raise ProfileError(f"fixture 出现循环引用：{chain}")
        base = _state(fixtures[name], fixtures, profile, resolving=(*resolving, name))
    if "copy" in raw:
        if raw["copy"] != "pre" or pre is None:
            raise ProfileError("只有后态可以使用 copy: pre")
        if "use" in raw:
            raise ProfileError("状态不能同时使用 use 和 copy")
        base = pre
    return profile.state_from_data(raw, base)


def _argument_matches(value: Any, type_name: str) -> bool:
    if type_name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "bool":
        return isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    # Domain-specific reference types normally come from JML calls rather than
    # suite arguments.  Their serialized representation is owned by a Profile.
    return True


def _expand_generators(
    generators: Any,
    parameters: Mapping[str, str],
    profile: EvaluationProfile,
    fixtures: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if generators is None:
        return []
    if not isinstance(generators, list):
        raise ProfileError("points 文件中的 generators 必须是数组")
    expanded: list[dict[str, Any]] = []
    prefixes: set[str] = set()
    for generator in generators:
        if not isinstance(generator, dict):
            raise ProfileError("每个 generator 必须是对象")
        prefix = generator.get("id")
        mode = generator.get("mode", "exhaustive")
        kind = generator.get("kind")
        domains = generator.get("args")
        pre_states = generator.get("pre")
        post_states = generator.get("post")
        if not isinstance(prefix, str) or not prefix or prefix in prefixes:
            raise ProfileError(f"generator id 缺失或重复：{prefix!r}")
        prefixes.add(prefix)
        if mode not in {"exhaustive", "mutations"}:
            raise ProfileError(f"generator {prefix} 暂不支持 mode {mode!r}")
        if kind not in {"pre", "post"}:
            raise ProfileError(f"generator {prefix} 的 kind 无效")
        if not isinstance(domains, dict) or set(domains) != set(parameters):
            raise ProfileError(f"generator {prefix} 的 args 必须配置全部方法参数")
        if not all(isinstance(values, list) and values for values in domains.values()):
            raise ProfileError(f"generator {prefix} 的每个参数域必须是非空数组")
        if not isinstance(pre_states, list) or not pre_states:
            raise ProfileError(f"generator {prefix} 的 pre 必须是非空状态数组")
        if mode == "exhaustive":
            if kind == "post" and (not isinstance(post_states, list) or not post_states):
                raise ProfileError(f"generator {prefix} 的 post 必须是非空状态数组")
            if kind == "pre" and post_states is not None:
                raise ProfileError(f"generator {prefix} 的 pre 模式不能配置 post")
        else:
            rule = generator.get("rule")
            variants = generator.get("variants")
            if kind != "post" or post_states is not None:
                raise ProfileError(f"generator {prefix} 的 mutations 模式只能生成 post")
            if not isinstance(rule, str) or not rule:
                raise ProfileError(f"generator {prefix} 缺少非空 rule")
            if not isinstance(variants, list) or not variants or not all(
                isinstance(item, str) and item for item in variants
            ) or len(set(variants)) != len(variants):
                raise ProfileError(f"generator {prefix} 的 variants 必须是无重复的非空字符串数组")
        names = list(parameters)
        argument_rows = [
            dict(zip(names, values))
            for values in itertools.product(*(domains[name] for name in names))
        ]
        for argument_index, arguments in enumerate(argument_rows):
            for name, type_name in parameters.items():
                if not _argument_matches(arguments[name], type_name):
                    raise ProfileError(
                        f"generator {prefix} 的参数 {name} 不符合类型 {type_name}"
                    )
            for pre_index, pre_state in enumerate(pre_states):
                if mode == "mutations":
                    try:
                        concrete_pre = _state(pre_state, fixtures, profile)
                        working_pre = copy.deepcopy(concrete_pre)
                        produced = profile.post_variants(
                            rule, working_pre, arguments
                        )
                    except (ProfileError, TypeError, ValueError) as error:
                        raise ProfileError(
                            f"generator {prefix} 的规则 {rule} 无法应用：{error}"
                        ) from error
                    if not isinstance(produced, Mapping) or not produced:
                        raise ProfileError(f"generator {prefix} 的规则 {rule} 未生成后态")
                    if concrete_pre != working_pre:
                        raise ProfileError(f"generator {prefix} 的规则 {rule} 修改了前态")
                    if not all(
                        isinstance(name, str) and isinstance(state, type(concrete_pre))
                        for name, state in produced.items()
                    ):
                        raise ProfileError(
                            f"generator {prefix} 的规则 {rule} 返回了无效变体或状态类型"
                        )
                    missing = set(variants) - set(produced)
                    if missing:
                        raise ProfileError(
                            f"generator {prefix} 的规则 {rule} 不含变体 {sorted(missing)}"
                        )
                    targets = [_GeneratedPost(copy.deepcopy(produced[name])) for name in variants]
                else:
                    targets = [None] if kind == "pre" else post_states
                for post_index, post_state in enumerate(targets):
                    suffix = f"a{argument_index}.s{pre_index}"
                    if kind == "post":
                        suffix += (
                            f".{variants[post_index]}" if mode == "mutations"
                            else f".t{post_index}"
                        )
                    point = {
                        "id": f"{prefix}.{suffix}",
                        "kind": kind,
                        "args": arguments,
                        "pre": pre_state,
                    }
                    if kind == "post":
                        point["post"] = post_state
                    for key in ("weight", "public", "tags"):
                        if key in generator:
                            point[key] = generator[key]
                    if mode == "mutations":
                        point["tags"] = [*point.get("tags", []), "generated-mutation", variants[post_index]]
                    expanded.append(point)
    return expanded


def load_suite(
    path: Path, profiles: Mapping[str, EvaluationProfile]
) -> LoadedSuite:
    config = _read_mapping(path)
    version = config.get("schema_version")
    if version != 1:
        raise ProfileError(f"不支持的 suite schema_version：{version!r}")
    method = config.get("method")
    profile_name = config.get("profile")
    if not isinstance(method, str) or not method:
        raise ProfileError("suite 缺少 method")
    if profile_name not in profiles:
        raise ProfileError(f"未知 profile：{profile_name!r}")
    reference_value = config.get("reference")
    points_value = config.get("points")
    if not isinstance(reference_value, str) or not isinstance(points_value, str):
        raise ProfileError("suite 必须提供 reference 和 points 路径")
    contract_shape = config.get("contract_shape")
    parameters = config.get("parameters")
    grading = config.get("grading")
    diagnostics = config.get("diagnostics", {})
    quality = config.get("quality", {})
    solver = config.get("solver", {"mode": "off", "timeout_ms": 1000})
    required_shape_keys = {"requires", "ensures", "signals"}
    if not isinstance(contract_shape, dict) or set(contract_shape) != required_shape_keys:
        raise ProfileError("suite 的 contract_shape 必须配置 requires/ensures/signals")
    if not isinstance(parameters, dict) or not all(
        isinstance(name, str) and isinstance(type_name, str)
        for name, type_name in parameters.items()
    ):
        raise ProfileError("suite 必须提供 parameters 类型映射")
    grading_keys = {"applicability", "postcondition", "exceptions", "locked"}
    if not isinstance(grading, dict) or set(grading) != grading_keys or not all(
        isinstance(value, int) and value >= 0 for value in grading.values()
    ) or sum(grading.values()) <= 0:
        raise ProfileError("suite 的 grading 必须为四个语义区域提供非负整数权重")
    diagnostic_keys = {"location", "category", "observation", "guidance", "slots"}
    if not isinstance(diagnostics, dict) or set(diagnostics) - grading_keys:
        raise ProfileError("suite 的 diagnostics 只能配置四个语义区域")
    for region, diagnostic in diagnostics.items():
        if not isinstance(diagnostic, dict) or set(diagnostic) - diagnostic_keys:
            raise ProfileError(f"diagnostics.{region} 的字段无效")
        text_values = (
            diagnostic.get(key) for key in diagnostic_keys - {"slots"}
            if key in diagnostic
        )
        slots = diagnostic.get("slots", [])
        if not all(isinstance(value, str) and value for value in text_values):
            raise ProfileError(f"diagnostics.{region} 的文案必须是非空字符串")
        if not isinstance(slots, list) or not all(
            isinstance(value, str) and value for value in slots
        ):
            raise ProfileError(f"diagnostics.{region}.slots 必须是字符串数组")
    if not isinstance(quality, dict) or set(quality) - {"min_mutation_score"}:
        raise ProfileError("suite 的 quality 只支持 min_mutation_score")
    minimum_mutation_score = quality.get("min_mutation_score", 0)
    if not isinstance(minimum_mutation_score, int) or not 0 <= minimum_mutation_score <= 100:
        raise ProfileError("quality.min_mutation_score 必须是 0 到 100 的整数")
    if not isinstance(solver, dict) or set(solver) - {"mode", "timeout_ms"}:
        raise ProfileError("suite 的 solver 只支持 mode 和 timeout_ms")
    solver_mode = solver.get("mode", "off")
    solver_timeout = solver.get("timeout_ms", 1000)
    if solver_mode not in {"off", "audit", "required"}:
        raise ProfileError("solver.mode 必须是 off/audit/required")
    if not isinstance(solver_timeout, int) or solver_timeout <= 0:
        raise ProfileError("solver.timeout_ms 必须是正整数")
    solver = {"mode": solver_mode, "timeout_ms": solver_timeout}
    for value in contract_shape.values():
        if isinstance(value, int) and value >= 0:
            continue
        if isinstance(value, dict) and set(value).issubset({"min", "max"}) and value:
            if all(isinstance(item, int) and item >= 0 for item in value.values()):
                continue
        raise ProfileError("contract_shape 必须是非负整数或包含 min/max 的对象")
    reference = (path.parent / reference_value).resolve()
    points_path = (path.parent / points_value).resolve()
    if not reference.is_file() or not points_path.is_file():
        raise ProfileError("suite 的 reference 或 points 文件不存在")

    document = _read_mapping(points_path)
    if document.get("schema_version") != 1:
        raise ProfileError(
            f"不支持的 points schema_version：{document.get('schema_version')!r}"
        )
    fixtures = document.get("fixtures", {})
    points = document.get("points", [])
    if not isinstance(fixtures, dict) or not isinstance(points, list):
        raise ProfileError("points 文件中的 fixtures/points 类型错误")
    profile = profiles[profile_name]
    if not all(isinstance(name, str) and isinstance(value, dict) for name, value in fixtures.items()):
        raise ProfileError("fixtures 必须把字符串名称映射到状态对象")
    for fixture_name in fixtures:
        try:
            _state({"use": fixture_name}, fixtures, profile)
        except (ProfileError, TypeError, ValueError) as error:
            raise ProfileError(f"fixture {fixture_name} 无效：{error}") from error
    points = [*points, *_expand_generators(
        document.get("generators"), parameters, profile, fixtures
    )]
    pre_points: list[Scenario] = []
    post_points: list[Scenario] = []
    ids: set[str] = set()
    for raw in points:
        if not isinstance(raw, dict):
            raise ProfileError("每个测试点必须是对象")
        point_id = raw.get("id")
        kind = raw.get("kind")
        arguments = raw.get("args")
        if not isinstance(point_id, str) or not point_id or point_id in ids:
            raise ProfileError(f"测试点 id 缺失或重复：{point_id!r}")
        if kind not in {"pre", "post"} or not isinstance(arguments, dict):
            raise ProfileError(f"测试点 {point_id} 的 kind/args 无效")
        if set(arguments) != set(parameters):
            raise ProfileError(
                f"测试点 {point_id} 的参数必须恰好是 {sorted(parameters)}"
            )
        for name, type_name in parameters.items():
            if not _argument_matches(arguments[name], type_name):
                raise ProfileError(
                    f"测试点 {point_id} 的参数 {name} 不符合类型 {type_name}"
                )
        weight = raw.get("weight", 1)
        public = raw.get("public", False)
        tags = raw.get("tags", [])
        if not isinstance(weight, (int, float)) or weight <= 0:
            raise ProfileError(f"测试点 {point_id} 的 weight 必须为正数")
        if not isinstance(public, bool) or not isinstance(tags, list) or not all(
            isinstance(tag, str) for tag in tags
        ):
            raise ProfileError(f"测试点 {point_id} 的 public/tags 无效")
        ids.add(point_id)
        try:
            pre = _state(raw.get("pre"), fixtures, profile)
            post_data = raw.get("post")
            post = (
                pre if kind == "pre" else
                post_data.state if isinstance(post_data, _GeneratedPost) else
                _state(post_data, fixtures, profile, pre)
            )
        except (ProfileError, TypeError, ValueError) as error:
            raise ProfileError(f"测试点 {point_id} 的状态无效：{error}") from error
        scenario = Scenario(
            pre, post, dict(arguments), point_id, float(weight), public, tuple(tags)
        )
        target = pre_points if kind == "pre" else post_points
        duplicate = next((
            existing for existing in target
            if existing.pre == scenario.pre
            and existing.post == scenario.post
            and existing.arguments == scenario.arguments
        ), None)
        if duplicate is not None:
            raise ProfileError(
                f"测试点 {point_id} 与 {duplicate.id} 是重复 observation"
            )
        target.append(scenario)
    if not pre_points or not post_points:
        raise ProfileError("suite 至少需要一个 pre 和一个 post 测试点")
    suite_name = str(config.get("name") or path.stem)
    bound = SuiteProfile(
        profile, method, tuple(pre_points), tuple(post_points), dict(contract_shape),
        dict(parameters), dict(grading), dict(diagnostics), dict(solver), suite_name, version,
    )
    return LoadedSuite(
        name=suite_name,
        version=version,
        method=method,
        reference=reference,
        profile=bound,
        contract_shape=dict(contract_shape),
        parameters=dict(parameters),
        grading=dict(grading),
        diagnostics=dict(diagnostics),
        quality=dict(quality),
        solver=dict(solver),
        pre_points=tuple(pre_points),
        post_points=tuple(post_points),
    )
