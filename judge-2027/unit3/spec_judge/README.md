# JML 一致性评测

第一次添加测试点或新方法，请先看 [手把手使用说明](USAGE.md)；它提供完整的文件示例、逐步命令与排错顺序。

本目录的正式评分入口 `semantic_check.py` 负责比较“参考 JML”和“学生 JML”在指定抽象状态上的语义一致性，不运行学生 Java。另有 `consistency_judge.py` 用于需要时的双链检查：它可将学生 JML 临时绑定到目标 Java 方法后调用 OpenJML，并返回可追溯的验证会话证据；这条链不替代本目录的 JML–JML suite，也不把未证明直接等同于实现错误。`runtime_verifier.py` 在第二阶段 2A＋2B 中为受限的 `unfollowUser` Java 适配器增加 RAC 编译、确定性小规模枚举、前后态观察和独立重跑确认；它同样不把有限范围内未找到反例当作正确性证明。`spec_judge.py` 是早期回归原型。

## 1. 当前能力和保证范围

当前已有五个可运行 Suite，覆盖三个扩展层级：

- `NetworkInterface.followUser`：原始网络方法；
- `NetworkInterface.containsBoth`：复用已有网络 Profile 的新方法；
- `NetworkInterface.canInteract`：给网络 Profile 增加 `blocked/isBlocked` 关系；
- `NetworkInterface.unfollowUser`：独立方法目录中的新练习，已接入 Web；
- `CounterInterface.checkNonNegative`：独立标量 Profile 和无参数方法。

第二阶段的运行反例入口目前只支持教师本地执行：

```bash
python3 runtime_verifier.py \
  --suite suites/NetworkInterface/unfollowUser/suite.yaml \
  --student-jml suites/NetworkInterface/unfollowUser/reference.java \
  --student-java examples/UnfollowUserRuntimeDemo.java \
  --openjml wsl:/home/ranye/.local/openjml-21.0.27/openjml
```

输出同时包含 `static_status` 和 `replay_status`、受限规格支持清单、搜索统计、候选输入、
实际前后态、违反条款和 `session` 证据。当前候选生成、`unfollowUser` 适配器及 RAC 执行均是
明确的窄接口；任意 ZIP、任意对象图、反例缩减、Web 任务入口和 `followUser` 运行检查不在本里程碑内。

其中 `followUser` 使用：

- 参考合同：`Agent/staff/fixtures/follow_user_complete.java`；
- 领域 Profile：`profiles/network_v1/profile.py`；
- 方法配置：`suites/NetworkInterface/followUser/suite.yaml`；
- 测试点：`suites/NetworkInterface/followUser/points.yaml`；
- 9 个前态和 5 个前后态对（含 4 个生成变体）；
- 支持布尔逻辑、整数比较、`\old`、`containsUser`、`getUser`、`isFollowing` 和 `containsFollower`。

默认评分结论只表示参考和学生合同在 suite 声明的有限测试域上一致，不表示任意状态上的完整逻辑等价。当前可对声明的参数域和状态列表做确定性笛卡尔展开，并已按行为归一化 `requires`、`ensures` 和 `signals`。可选 SMT 后端能检查当前 AST 子集的逻辑差异；`network_v1` 已配置部分领域不变量公理，但并非完整的领域或 JML 语义，量词、集合运算和完整 JML frame 语法仍未支持。路线见仓库根目录 `TODO.md`。

### 可选安装 SMT

固定点模式只依赖 Python 标准库。需要 SMT 审计或强制判定时，在仓库根目录运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r judge-2027/unit3/spec_judge/requirements-smt.txt
```

Windows 使用 `.venv\Scripts\python.exe`。之后将下文命令中的 `python3` 换成仓库根目录的 `.venv/bin/python`（Windows 换成对应路径）。

## 2. 开始一次评测

在本目录运行：

```bash
python3 semantic_check.py \
  ../../../Agent/staff/fixtures/follow_user_complete.java \
  --suite suites/NetworkInterface/followUser/suite.yaml \
  --json
```

第一个路径是学生提交。示例中用参考文件自身作为提交，因此结果应为：

```json
{
  "score": 100,
  "passed": true,
  "diagnostics": [],
  "coverage": {"...": "各语义区域通过权重/总权重"},
  "evaluation": {
    "profile": "network_v1",
    "suite": "NetworkInterface.followUser",
    "suite_version": 1,
    "guarantee_scope": "fixed_test_points"
  },
  "solver": {
    "applicability": {"status": "UNAVAILABLE"},
    "postcondition": {"status": "UNAVAILABLE"},
    "exceptions": {"status": "UNAVAILABLE"}
  }
}
```

评测一个错误样例：

```bash
python3 semantic_check.py \
  ../../../Agent/exercises/follow_user/samples/wrong-relation-direction.java \
  --suite suites/NetworkInterface/followUser/suite.yaml \
  --json
```

仍保留旧兼容入口：

```bash
python3 semantic_check.py STUDENT.java \
  --reference REFERENCE.java \
  --method followUser \
  --json
```

使用 `--suite` 时不能再传 `--reference` 或 `--method`，因为 suite 已经锁定二者。参考 JML 和隐藏测试点只能放在评测端，不能随学生包发布。

## 3. 评测过程

1. 从参考 Java 和学生 Java 中找到目标方法前的 JML 块。
2. 解析 `requires`、`ensures`、`signals` 和 `assignable`。
3. suite 选择 Profile 和测试点。
4. Profile 将 JML 方法调用解释为抽象状态查询。
5. 在相同测试点上分别计算参考子句和学生子句。
6. 真值不一致时产生确定性诊断，并按“区域权重 × 测试点通过比例”计分。

参考 JML 是 oracle；测试点不保存答案，也不要求学生文本与参考文本相同。

## 4. Suite 文件

`suites/NetworkInterface/followUser/suite.yaml` 内容示意：

```yaml
{
  "schema_version": 1,
  "name": "NetworkInterface.followUser",
  "profile": "network_v1",
  "method": "followUser",
  "parameters": {"id1": "int", "id2": "int"},
  "contract_shape": {
    "requires": {"min": 1},
    "ensures": {"min": 1},
    "signals": 4
  },
  "grading": {
    "applicability": 20,
    "postcondition": 30,
    "exceptions": 40,
    "locked": 10
  },
  "diagnostics": {
    "postcondition": {
      "slots": ["FORWARD_POSTCONDITION", "INVERSE_POSTCONDITION"]
    }
  },
  "quality": {"min_mutation_score": 100},
  "solver": {"mode": "audit", "timeout_ms": 1000},
  "reference": "../../../../../../Agent/staff/fixtures/follow_user_complete.java",
  "points": "points.yaml"
}
```

当前加载器接受“JSON 语法的 YAML 子集”，目的是保持 Python 标准库零依赖。也就是说文件扩展名是 `.yaml`，但内容暂时必须符合 JSON：属性使用双引号、不能写 YAML 注释、不能使用锚点。未来切换完整 YAML 解析器时不会改变字段结构。

路径均相对于 suite 文件所在目录解析。每个方法单独放在 `suites/<类名>/<方法名>/`，其中 `suite.yaml` 是入口、`points.yaml` 是测试点、`reference.java` 是本方法专用参考合同；可选 `wrong.java` 保存维护者用的反例。`followUser` 的参考合同由 `Agent/staff/fixtures/` 共享，因此其 `reference` 指向该处，不另存一份。增加新方法时复制目录结构，不复制旧点的语义；详见 [USAGE.md](USAGE.md)。

`contract_shape` 可以使用整数表示精确数量，也可以使用 `{"min": 1}`、`{"max": 3}` 或同时提供上下界。通用合同解析器本身不限制子句数量。

`grading` 的四个键分别控制正常适用性、正常后置条件、异常结果和锁定 frame/输出的总分占比。`diagnostics` 可选，用来给某个方法覆盖通用的 `location`、`category`、`observation`、`guidance`，也可用 `slots` 给固定数量的子句设置教学空位标签。它只影响反馈，不定义正确答案。`quality.min_mutation_score` 可设为 `0` 到 `100`，让预检在点集不能识别足够多典型 JML 变异时失败。

`solver.mode` 有三种取值：

- `off`：完全不加载 Z3；
- `audit`：可用时输出 `SAT/UNSAT/UNKNOWN`，不可用时输出 `UNAVAILABLE`，但评分始终只由固定点决定；
- `required`：Z3 必须可用；`SAT` 作为对应区域不一致，`UNKNOWN` 或依赖缺失作为评测配置错误，不会误报学生通过。

若三个逻辑区域均为 `UNSAT`，`evaluation.guarantee_scope` 会变为 `smt_supported_subset`。当前网络 Profile 将 `UserRef` 映射为整数、`getUser` 映射为恒等函数，把状态查询建模为前/后态函数，并用 JML 子集表达式约束关系端点存在及 `following/followers` 的反向一致性。新增 Profile 在启用 `required` 前必须同样确认类型别名、恒等调用和 `smt_axioms` 覆盖了会影响结论的领域不变量。求解器模型只在进程内部使用，不进入 JSON、浏览器或 LLM。

维护者可以把某个错误提交的 `SAT` 模型转成候选测试点：

```bash
../../../.venv/bin/python smt_counterexample.py STUDENT.java \
  --suite suites/NetworkInterface/followUser/suite.yaml
```

输出的 `candidate_points` 已是 points schema 的形状，但不会自动写文件。先人工检查其领域含义，再复制到 points 文件并运行 `validate_suite.py`；这种显式步骤可避免把不完整符号模型直接变成正式隐藏点。此命令是维护工具，不应暴露给学生端。

## 5. 添加测试点

### 5.1 前态测试点

前态用于比较正常条件和异常条件：

```yaml
{
  "id": "second_user_missing",
  "kind": "pre",
  "args": {"id1": 1, "id2": 2},
  "pre": {
    "users": [1],
    "following": [],
    "followers": []
  }
}
```

不需要填写期望真假。引擎会在该状态上分别执行参考 JML 和学生 JML。

### 5.2 后置状态测试点

后置条件需要前态和后态：

```yaml
{
  "id": "missing_inverse_update",
  "kind": "post",
  "args": {"id1": 1, "id2": 2},
  "pre": {"use": "two_users"},
  "post": {
    "copy": "pre",
    "add": {
      "following": [[1, 2]]
    }
  }
}
```

这是一个故意只增加正向关系的后态，用于区分两个成功后置条件。错误后态不是 Java 执行结果，而是用来测试 JML 能否拒绝错误转换。

### 5.3 复用 fixture

在 points 文件顶层声明：

```yaml
"fixtures": {
  "two_users": {
    "users": [1, 2],
    "following": [],
    "followers": []
  }
}
```

测试点通过 `"pre": {"use": "two_users"}` 复用。后态支持：

- `"copy": "pre"`：复制前态；
- `"add": {"following": [[1, 2]]}`：增加关系；
- `"remove": {"followers": [[2, 1]]}`：删除关系；
- 直接给出 `users`、`following` 或 `followers`：覆盖该字段。

每个 `id` 必须唯一，suite 至少包含一个 `pre` 和一个 `post` 点。建议每个方法覆盖：正常、每类异常、异常重叠、正确后态、遗漏更新、方向错误和无关修改。

测试点还可以配置：

```yaml
"weight": 2,
"public": false,
"tags": ["boundary", "missing-update"]
```

`weight` 默认为 1；`public` 和 `tags` 作为发布与筛选元数据，不改变参考 JML 的 oracle 地位。JSON 输出中的 `coverage` 会报告每个区域通过和总测试点权重。

添加后运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 validate_suite.py \
  suites/NetworkInterface/followUser/suite.yaml

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_semantic_judge.py -v
```

`validate_suite.py` 会加载 Profile、检查路径和 schema、解析参考 JML，并让参考合同在全部测试点上进行自比较。它报告 `generated_post` 中正常适用、被参考接受及拒绝的生成后态数量；还会逐个运行逻辑连接/比较翻转、删除否定或 `\old`、简单参数交换、布尔翻转和 frame 放宽等确定性变异，输出 `mutations.total/killed/score/survivors`。存活变异意味着当前点集无法区分该类改错，应补点或人工确认它在限定域内确实等价。变异得分只衡量这些典型错误，不是完整正确性的证明。

例如 `unfollowUser` 当前报告 `killed: 6`、`total: 7`、`score: 86`，这是变异识别率，**不是学生成绩**。唯一存活的 `delete_conjunct.2` 把“两个用户存在且 id1 关注 id2”简化为“id1 关注 id2”；在 `network_v1` 的合法状态中，关注边的两端必须存在，因此两种写法在当前抽象模型内等价，不能靠增加合法测试点区分。遇到存活变异时要先检查是否属于这种等价变异，再决定补点；不要为追求 100% 强行加入不合法的状态。该 Suite 的 `validate_suite.py` 结果仍是 `valid: true`。

### 5.4 批量展开有限测试域

当多组参数需要复用多种状态时，不必手写笛卡尔积。`generators` 会按文件顺序确定性生成测试点：

```yaml
"generators": [
  {
    "id": "result_grid",
    "mode": "exhaustive",
    "kind": "post",
    "args": {"id1": [1, 2], "id2": [2, 3]},
    "pre": [{"use": "empty"}, {"use": "both"}],
    "post": [{"copy": "pre"}]
  }
]
```

这个例子生成 `2 × 2 × 2 × 1 = 8` 个后态点，ID 形如 `result_grid.a0.s0.t0`。`kind: pre` 时省略 `post`。参数键必须与 suite 的 `parameters` 完全相同，每个参数域、`pre` 和后态模式下的 `post` 都不能为空。

### 5.5 由 Profile 生成后态变体

对领域相关的状态转换，suite 不必逐条写补丁。例如当前 `suites/NetworkInterface/followUser/points.yaml` 使用：

```yaml
"generators": [
  {
    "id": "follow_outcomes",
    "mode": "mutations",
    "kind": "post",
    "args": {"id1": [1], "id2": [2]},
    "pre": [{"use": "steady"}],
    "rule": "follow_pair",
    "variants": ["correct", "omit_inverse", "omit_forward", "reverse_direction"]
  }
]
```

加载器对每组参数和前态调用 Profile 的 `post_variants(rule, pre, arguments)`，按 `variants` 顺序选取后态并生成稳定 ID，如 `follow_outcomes.a0.s0.omit_inverse`。规则可返回更多候选：网络 Profile 还提供 `unrelated_change`、`wrong_delete`；是否纳入某个方法的 suite 由配置决定。生成器不写“期望通过/失败”，实际结果完全由参考 JML 判定。未知规则、缺失变体、非法前态和重复 observation 都是配置错误。生成器在隔离副本上运行，不能修改原始前态。`Counter` Profile 的 `neighbor_values` 展示了另一类状态的 `unchanged/above/below` 变体。

当前 `mutations` 是确定性的，没有随机种子；未来若添加随机生成，必须显式记录种子并可冻结生成点。

## 6. Profile：增加领域状态或 JML 方法

通用边界定义在 `core/profile.py`。Profile 负责三件事：

```python
class EvaluationProfile:
    name: str
    allowed_calls: frozenset[str]
    symbols: Mapping[str, tuple[SymbolSignature, ...]]
    grading: Mapping[str, int]
    stateful_calls: frozenset[str]
    smt_type_aliases: Mapping[str, str]
    smt_identity_calls: Mapping[str, int]
    smt_axioms: Sequence[str]

    def parameter_types(self, method_name): ...
    def evaluate_call(self, name, values, context): ...
    def state_from_data(self, data, base=None): ...
    def post_variants(self, rule, pre, arguments): ...
    def state_data_from_smt_calls(self, calls): ...
    def pre_scenarios(self, method_name): ...
    def post_scenarios(self, method_name): ...
```

当前网络实现位于 `profiles/network_v1/profile.py`。

### 增加同一领域的查询方法

例如 JML 新增 `getUser(id).getAge()`：

1. 给 `NetworkState` 增加所需抽象字段，例如 `ages`；
2. 在 `state_from_data` 中加载该字段；
3. 把 `getAge` 加入 `allowed_calls`；
4. 在 `evaluate_call` 中实现其确定语义；
5. 增加正确调用、错误参数和 `\old` 回归测试。

不要根据方法名猜语义，也不要让未知调用默认返回 `false`。无法解释的调用必须产生格式/符号诊断。

### 增加新的状态关系

例如增加群组成员关系：

```text
groups: set[GroupId]
group_members: relation[GroupId, UserId]
```

需要扩展状态类型、配置加载和相关 JML 查询方法。评测核心不应出现这些字段；所有领域访问都留在 Profile 内。

若该领域有常用后态错误模式，在 Profile 的 `post_variants` 中新增有名称的规则，返回“变体名 → 独立后态对象”。规则只构造候选状态，不判断正确性；suite 的 `mode: mutations` 负责选择变体，参考 JML 负责判定。这样同一规则可由该领域多个方法复用，核心加载器无需知道 `following`、`value` 等字段。

## 7. 添加新方法

当前迁移阶段按以下步骤添加：

1. 准备包含完整 JML 的参考 Java 文件。
2. 新建 `suites/<Interface>/<method>.yaml`。
3. 新建 `<method>-points.yaml`，加入前态和前后态。
4. 若方法使用已有 JML 调用，复用 `network_v1`；否则先扩展 Profile。
5. 在 suite 中配置 `parameters`、`contract_shape`、`grading` 和可选 `diagnostics`。
6. 运行 `validate_suite.py`，确认参考合同、状态和全部参数组合可求值。
7. 增加正确、过强、过弱和非法符号样例测试。

新增方法不需要修改 `core/judge.py` 或 `semantic_judge.py`。只有 JML 使用了 Profile 尚不认识的状态/查询，才需要扩展 Profile。

通用解析器已经接受不同子句数量、方法名和多个 `also` 行为，具体范围由 suite 的 `contract_shape` 校验。通过判定会组合适用的正常行为，并按测试点比较整体异常匹配集合；等价的 `ensures` 调序或合并可以通过。`assignable` 在当前支持的 store-ref 子集中按适用行为比较，列表空白和顺序不影响结果；自定义 `(* output-> ... *)` 指令仍作为锁定文本处理。

## 8. 添加新类

先判断新类是否仍可由现有抽象关系表达：

- 可以：扩展 `network_v1` 状态和调用映射，建立新 suite；
- 不适合：复制 Profile 骨架建立新版本，例如 `profiles/message_v1/`；
- 多个类共享状态：让它们引用同一个 Profile，不要复制模型。

新 Profile 完成后，在 `profiles/registry.py` 注册：

```python
load_suite(path, {
    "network_v1": NETWORK_PROFILE,
    "message_v1": MESSAGE_PROFILE,
})
```

随后用 suite 的 `"profile": "message_v1"` 选择它。注册表是唯一的 Profile 选择入口；核心 judge 不导入具体领域。

## 9. 扩展支持的 JML 语法

AST、解析器和通用运算位于 `core/expressions.py`，合同抽取位于 `core/contracts.py`，Profile 只负责领域方法调用。增加语法时必须同步完成：

1. tokenizer 识别符号；
2. AST 增加节点；
3. parser 定义优先级和结合性；
4. evaluator 定义前态/后态语义；
5. 类型和非法输入检查；
6. 正确、边界和拒绝用例。

例如增加量词不能只修改 tokenizer，还必须定义变量作用域、有限取值域和空集合语义。所有 Profile 共享这些核心语法能力。

## 10. 测试与排错

统一评测测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_semantic_judge.py -v
```

全部本目录测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -p 'test_*.py' -v
```

当前 macOS 上 `test_wsl_openjml_converts_windows_source_path` 会因 Windows 路径语义不同而失败；它属于旧 JML–Java/OpenJML 链，不影响这里的 JML 一致性 suite。

常见配置错误：

- `未知 profile`：尚未在 CLI registry 注册；
- `reference 或 points 文件不存在`：相对路径以 suite 所在目录为基准；
- `未知 fixture`：`use` 名称没有出现在 `fixtures`；
- `id 缺失或重复`：每个测试点需要稳定唯一 ID；
- `kind/args 无效`：`kind` 只能是 `pre` 或 `post`，`args` 必须是对象；
- `参数必须恰好是 ...`：测试点参数名与 suite 的 `parameters` 不一致；
- `fixture 出现循环引用`：fixture 的 `use` 链形成了环；
- `network_v1 不支持关系`：points 使用了 Profile 尚未声明的状态字段。

CLI 退出码 `1` 表示学生 JML 未通过，退出码 `2` 表示 suite、参考合同或服务器文件配置错误。后者不能折算成学生零分。学生语法/非法符号使用 `JML_FORMAT_OR_SYMBOL`，语义差异使用各区域的 mismatch 代码；诊断中的 `lines`（若存在）是学生 Java 的 1 起始源码行号。

## 11. 安全边界

- 参考 JML、隐藏测试点和完整反例状态不得发送给浏览器或 LLM。
- 学生提交中的任意方法调用不会被执行；只解释白名单 AST。
- Profile 配置错误与学生语义错误应分别处理，不能把服务器错误记为学生失败。
- Web 服务仍应只绑定本地地址，除非另行加入认证、限流和资源隔离。
