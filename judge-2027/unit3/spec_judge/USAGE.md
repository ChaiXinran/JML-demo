# 手把手添加 JML 一致性测试点

这份说明面向第一次维护本评测器的人。按顺序做即可；不需要先理解求解器或评测核心源码。本文只讲“参考 JML 与学生 JML 是否一致”，**不执行学生 Java，也不使用 OpenJML 检验 Java 实现**。

## 0. 先弄清楚要改什么

一次评测由四样东西组成：

| 名称 | 作用 | `followUser` 对应文件 |
| --- | --- | --- |
| 参考 Java | 方法声明前写着完整、正确的参考 JML；它是判定依据 | `../../../Agent/staff/fixtures/follow_user_complete.java` |
| Suite | 指定方法、Profile、参考文件、测试点文件和评分设置 | `suites/NetworkInterface/followUser/suite.yaml` |
| Points | 列出输入参数、调用前状态、候选调用后状态；**不写标准答案** | `suites/NetworkInterface/followUser/points.yaml` |
| Profile | 解释状态字段及 JML 中的方法调用，例如 `containsUser(1)` 的含义 | `profiles/network_v1/profile.py` |

下文所有相对路径，除非特别说明，均以 `judge-2027/unit3/spec_judge/` 为当前目录。Suite 里的 `reference` 和 `points` 路径则**相对于 Suite 文件所在目录**，不是相对于运行命令的目录。

每个方法各有一个 `suites/<类名>/<方法名>/` 目录：`suite.yaml` 是评测入口，`points.yaml` 放测试点，本方法专用的参考文件和错误样例分别可放 `reference.java`、`wrong.java`。`followUser` 的参考 Java 已在 `Agent/staff/fixtures/`，因此只在 Suite 中引用，不额外复制。添加一个新的测试点时仍写入该方法的**同一个** `points.yaml` 的 `points` 数组，不要为每个测试点建目录。

先判断属于哪种情况：

1. **同一个 `followUser`，只增加测试情形**：只改 `followUser/points.yaml`，见第 2～5 节。
2. **新方法或新类，但状态和 JML 查询仍是“用户／关注／粉丝／屏蔽”**：新建参考 Java、Suite、Points，继续用 `network_v1`，见第 6 节。类名不同并不必然需要新 Profile。
3. **新方法或新类，状态是一个整数，JML 只查询 `getValue()`**：可继续用 `counter_v1`，见第 7 节。
4. **全新领域状态或新的 JML 查询**：除了上述文件，还必须实现或扩展 Profile，见第 8 节。仅写 JSON 格式的测试点无法让评测器理解未知的查询方法。

## 1. 准备环境，并跑通原有例子

在仓库根目录打开终端，先进入评测目录：

```bash
cd judge-2027/unit3/spec_judge
```

以下命令使用 macOS/Linux 的 `python3`。Windows PowerShell 可先运行 `Set-Location judge-2027\unit3\spec_judge` 和 `$env:PYTHONDONTWRITEBYTECODE = "1"`，然后将下文每条命令开头的 `PYTHONDONTWRITEBYTECODE=1 python3` 换成 `python`（或本机实际安装的 Python 命令）。固定测试点模式只需要 Python 标准库，不需要先安装 Z3；若 `solver.mode` 为 `required`，则必须先按 [README](README.md#可选安装-smt) 安装 `requirements-smt.txt`。

先验证已有 Suite：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 validate_suite.py suites/NetworkInterface/followUser/suite.yaml
```

应看到 `"valid": true`、`"profile": "network_v1"`、`"method": "followUser"`，以及前态数、后态数和变异测试结果。再用参考文件充当“学生提交”，确认评测入口可用：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 semantic_check.py \
  ../../../Agent/staff/fixtures/follow_user_complete.java \
  --suite suites/NetworkInterface/followUser/suite.yaml --json
```

应看到 `"score": 100`、`"passed": true`。如果这里还不能运行，先解决环境或原有配置问题，避免把旧问题误认为新测试点造成的。

## 2. 测试点究竟在测什么

一个测试点不是一段 Java 程序，也不是一个“预期输出”。它是给 JML 表达式求值的一张状态快照：

- `args`：调用方法时传入的参数。例如 `{"id1": 1, "id2": 2}`。键名必须和 Suite 的 `parameters` 完全一致；无参数方法写 `{}`。
- `pre`：调用方法**之前**的状态。`requires` 和本项目受限语义下的 `signals` 在这里求值。
- `kind: "pre"`：只检查正常行为是否适用、哪些异常条件成立；不需要 `post`。
- `kind: "post"`：还必须给出 `post`，即一个**候选**调用后状态，用于比较双方 `ensures` 是否接受该状态。它可以故意不正确，正是为了测出漏写或写错的后置条件。

评测器在同一个点上分别运行参考 JML 和学生 JML：两者同意时该点通过，不同意时该点发现语义差异。因此，**不要在 Points 文件里增加 `expected`、`should_pass` 一类答案字段**。测试点也不会自动证明整个无限状态空间上的等价。

`assignable` 当前只在支持的 store-ref 子集中比较参考与学生合同的有效 frame，不会依据这里的前后态检查“实际 Java 是否只修改了允许的字段”。

网络 Profile 的状态字段如下：

```json
{
  "users": [1, 2],
  "following": [[1, 2]],
  "followers": [[2, 1]],
  "blocked": []
}
```

这表示用户 1 关注用户 2，所以 `following` 边是 `[1, 2]`；用户 2 的粉丝包括用户 1，所以 `followers` 边是 `[2, 1]`。两张表的方向相反，最容易填错。`blocked` 的边 `[a, b]` 表示用户 `a` 屏蔽 `b`。关系端点都必须出现在 `users` 中。只有测试点需要的字段才必须写；省略的网络关系默认为空。**加载器不会替你从 `following` 自动推导 `followers`**，需要测试双向一致时应明确写两边。

## 3. 给 `followUser` 手工增加一个前态点

要测“2 已关注 1，但 1 尚未关注 2”这一边界情况：

1. 打开 `suites/NetworkInterface/followUser/points.yaml`。
2. 找到顶层的 `"points": [` 数组。不要把新点写进 `"fixtures"` 或 `"generators"`。
3. 在 `points` 数组**当前最后一个对象**后加逗号，然后在该数组的 `]` 前加入以下对象。不要假设最后一个点始终叫 `normal_minimal`；增加测试点后顺序会变化：

```json
{
  "id": "reverse_already_exists",
  "kind": "pre",
  "args": {"id1": 1, "id2": 2},
  "pre": {
    "users": [1, 2],
    "following": [[2, 1]],
    "followers": [[1, 2]]
  }
}
```

新点的 `id` 必须在该 Points 文件中唯一，也不能与生成器展开后的 ID 冲突。这里不写 `post`：它测的是参考与学生对正常条件和异常分支的判断是否一致。保存时确认 JSON 数组对象之间有逗号，最后一个对象后没有多余逗号。

先检查文件语法，再验证整个 Suite：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m json.tool suites/NetworkInterface/followUser/points.yaml
PYTHONDONTWRITEBYTECODE=1 python3 validate_suite.py suites/NetworkInterface/followUser/suite.yaml
```

第一条只检查 JSON 语法；第二条还会检查状态、参数、重复点、参考 JML 和变异测试。注意 `.yaml` 后缀目前**必须使用 JSON 语法**：键名和字符串加双引号，不能写 YAML 注释或尾随逗号。

## 4. 给 `followUser` 手工增加一个前后态点

继续测上面的前态中，调用成功后是否同时保留原有反向关注，并增加新的正向关注：

1. 仍打开同一个 `followUser/points.yaml`。
2. 在 `"points"` 数组中再加入下面这个对象，并按 JSON 规则处理前一个对象后的逗号：

```json
{
  "id": "reverse_already_exists_after_success",
  "kind": "post",
  "args": {"id1": 1, "id2": 2},
  "pre": {
    "users": [1, 2],
    "following": [[2, 1]],
    "followers": [[1, 2]]
  },
  "post": {
    "copy": "pre",
    "add": {
      "following": [[1, 2]],
      "followers": [[2, 1]]
    }
  }
}
```

`"copy": "pre"` 表示先复制该点的前态，再应用 `add`。所以原有的 `[2, 1]` 仍存在。`remove` 可以删除关系；例如 `"remove": {"following": [[1, 2]]}`。`users`、`following`、`followers`、`blocked` 直接出现在状态对象里时是**覆盖对应字段**，不是追加。尤其直接重写 `users` 会重置关系表；表示状态变化时通常优先使用 `"copy": "pre"` 加 `add`/`remove`。

这个 `post` 是参考 JML 应当接受的成功候选。要测“只更新关注、不更新粉丝”的错误候选，另建一个 `post` 点，仅把 `add` 改为 `{"following": [[1, 2]]}`；**仍然不写预期值**，由参考 JML 自动拒绝。不要把同一组 `args`、`pre`、`post` 重复加入：即使 ID 不同，加载器也会报 `重复 observation`。

再次运行第 3 节的两条检查命令。还应重跑一次第 1 节的参考自评命令，确认 `passed: true`。

## 5. 减少重复劳动：Fixture 和批量生成

### 5.1 复用状态 Fixture

如果多个点的前态相同，可在 Points 文件的顶层 `"fixtures"` 中定义一次：

```json
"fixtures": {
  "two_users": {"users": [1, 2], "following": [], "followers": []}
}
```

注意原文件已经有 `two_users`，**不要重复定义同名键**；上面只是说明格式。点里写 `"pre": {"use": "two_users"}` 即可。`use` 也可以引用其他 Fixture，但不能形成循环。后态可写 `"post": {"copy": "pre", "add": {...}}`。

### 5.2 生成参数和状态的组合

当你想测试多个参数组合与多个前态的全部搭配时，在顶层 `"generators"` 数组中增加对象，而不是逐点复制。例如：

```json
{
  "id": "new_pre_grid",
  "mode": "exhaustive",
  "kind": "pre",
  "args": {"id1": [1, 2], "id2": [1, 2]},
  "pre": [{"use": "two_users"}]
}
```

它生成 4 个 `pre` 点，ID 从 `new_pre_grid.a0.s0` 开始。生成 `post` 点时，把 `kind` 改成 `post` 并增加非空的 `"post": [{"copy": "pre"}, ...]` 数组；组合数是各参数候选数 × 前态数 × 后态数。生成器的 `args` 必须列出 Suite 的全部参数，每个参数域、`pre` 和 `post` 列表都不能是空数组。无参数方法写 `"args": {}`，仍会产生一组参数组合。生成点也会和手写点检查重复 observation；不要无意把已有点再生成一遍。

### 5.3 使用 Profile 已实现的后态变体

`network_v1` 已有 `follow_pair` 规则；现有 `followUser/points.yaml` 正在使用它。规则根据给定前态和参数构造 `correct`、`omit_inverse`、`omit_forward`、`reverse_direction` 等候选后态。如果要增加一批不同参数或不同前态的相同错误模式，可照现有 `"mode": "mutations"` 生成器新增一组，但新的 `id` 必须唯一，且前态必须满足“两个不同、已存在、尚无目标方向关注关系”的规则前提。否则 `validate_suite.py` 会报告规则无法应用。`counter_v1` 对应的现成规则是 `neighbor_values`。

新点可以设置 `"weight": 2`（正数，默认 1）、`"public": false`（布尔值，默认 false）、`"tags": ["boundary"]`（字符串数组）。权重会影响评分；它们不定义预期答案。初次加点建议先保留默认权重，以免无意改变既有评分比例。

## 6. 新方法、已有网络领域：完整示例 `unfollowUser`

这一路**不需要改 `core/judge.py`、`semantic_judge.py` 或 Profile 注册表**。下面以新方法 `NetworkInterface.unfollowUser(int id1, int id2)` 为例；它要求两名用户存在且已经关注，成功后取消正向关注及对应粉丝记录。以下是要创建的三个文件。

### 6.1 创建完整参考 Java

先新建目录 `suites/NetworkInterface/unfollowUser/`，再在其中新建 `reference.java`，内容为：

```java
public interface NetworkInterface {
    /*@ public normal_behavior
      @ requires containsUser(id1) && containsUser(id2)
      @          && getUser(id1).isFollowing(getUser(id2));
      @ assignable users[*];
      @ ensures !getUser(id1).isFollowing(getUser(id2));
      @ ensures !getUser(id2).containsFollower(getUser(id1));
      @*/
    public void unfollowUser(int id1, int id2);
}
```

这里的参考 JML 是**示范规格**，实际课程使用前必须由你依据真实题意审核，不能因为它能通过自检就认定它正确。方法声明前必须有 `/*@ ... @*/` 块；方法名应与下一步 Suite 的 `method` 完全相同。这个评测器不运行方法体；参考文件只需提供可定位的方法声明和 JML。当前定位方式按方法名查找声明，不适合在同一文件放多个同名重载方法让它猜测目标。

### 6.2 创建 Suite

新建 `suites/NetworkInterface/unfollowUser/suite.yaml`：

```json
{
  "schema_version": 1,
  "name": "NetworkInterface.unfollowUser",
  "profile": "network_v1",
  "method": "unfollowUser",
  "parameters": {"id1": "int", "id2": "int"},
  "contract_shape": {"requires": 1, "ensures": 2, "signals": 0},
  "grading": {
    "applicability": 30,
    "postcondition": 60,
    "exceptions": 0,
    "locked": 10
  },
  "solver": {"mode": "off"},
  "reference": "reference.java",
  "points": "points.yaml"
}
```

`parameters` 的键名和类型要与 JML 使用的参数一致；无参数方法写 `{}`。`contract_shape` 限制学生提交的 `requires`、`ensures`、`signals` 数量：整数表示精确数量，也可用 `{"min": 1}` 等范围。`grading` 必须包含四个区域，值是非负整数，至少一个大于 0；上例总和为 100。`solver.mode: "off"` 不需要安装 Z3；确定测试点足够后可参考主 README 决定是否改成 `audit`。初建时可不写 `quality`；如果要强制测试点杀死一定比例的典型错误，再配置 `"quality": {"min_mutation_score": 80}`，并按验证结果补点。

### 6.3 创建 Points

新建 `suites/NetworkInterface/unfollowUser/points.yaml`：

```json
{
  "schema_version": 1,
  "fixtures": {
    "linked": {
      "users": [1, 2],
      "following": [[1, 2]],
      "followers": [[2, 1]]
    },
    "unlinked": {
      "users": [1, 2],
      "following": [],
      "followers": []
    }
  },
  "points": [
    {"id": "before_linked", "kind": "pre", "args": {"id1": 1, "id2": 2}, "pre": {"use": "linked"}},
    {"id": "before_unlinked", "kind": "pre", "args": {"id1": 1, "id2": 2}, "pre": {"use": "unlinked"}},
    {
      "id": "after_correct",
      "kind": "post",
      "args": {"id1": 1, "id2": 2},
      "pre": {"use": "linked"},
      "post": {
        "copy": "pre",
        "remove": {"following": [[1, 2]], "followers": [[2, 1]]}
      }
    },
    {
      "id": "after_missing_inverse",
      "kind": "post",
      "args": {"id1": 1, "id2": 2},
      "pre": {"use": "linked"},
      "post": {"copy": "pre", "remove": {"following": [[1, 2]]}}
    },
    {
      "id": "after_unchanged",
      "kind": "post",
      "args": {"id1": 1, "id2": 2},
      "pre": {"use": "linked"},
      "post": {"copy": "pre"}
    }
  ]
}
```

Suite 至少要有一个 `pre` 点和一个 `post` 点；这里分别测前置条件、正确后态、只删除单向关系、完全不变。点不需要写“正确/错误”标签；ID 只是便于维护。真实方法还应根据题意补齐用户缺失、自操作、异常等边界。

### 6.4 逐层检查新 Suite

仍在 `spec_judge` 目录运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m json.tool suites/NetworkInterface/unfollowUser/suite.yaml
PYTHONDONTWRITEBYTECODE=1 python3 -m json.tool suites/NetworkInterface/unfollowUser/points.yaml
PYTHONDONTWRITEBYTECODE=1 python3 validate_suite.py suites/NetworkInterface/unfollowUser/suite.yaml
PYTHONDONTWRITEBYTECODE=1 python3 semantic_check.py \
  suites/NetworkInterface/unfollowUser/reference.java \
  --suite suites/NetworkInterface/unfollowUser/suite.yaml --json
```

最后一条用参考文件自评，预期 `score: 100` 且 `passed: true`。然后在同一方法目录另存一个**故意错误**的学生 Java，例如 `wrong.java`：保留第二个 `ensures` 子句但把它的条件改成 `true`，再以同一个 Suite 运行 `semantic_check.py suites/NetworkInterface/unfollowUser/wrong.java --suite suites/NetworkInterface/unfollowUser/suite.yaml --json`。预期至少一个相关区域失分；若错误样例仍得 100，说明测试点没有区分出这类错误，应补候选后态再验证。不要直接删除该子句：本示例的 `contract_shape` 要求恰好两条 `ensures`，删除会先触发结构问题，无法单独验证点集的区分能力。`validate_suite.py` 的 `mutations.survivors` 也会提示典型错误中哪些还没被测试点识别。

当前这份 `unfollowUser` Suite 的预检可通过，但变异识别率是 `6/7 ≈ 86%`。唯一存活的 `delete_conjunct.2` 删除了前置条件中显式写出的“两个用户存在”，只保留“id1 关注 id2”。在 `network_v1` 中，合法的关注关系已经保证两端用户存在，所以这个变异在当前抽象模型内等价，并不表示必须再加一个测试点。变异识别率不是学生分数；碰到其他存活变异时也应先判断是否真的改变了语义，再决定是否补点。

评测通过的退出码为 0，学生合同不一致为 1，Suite／参考文件等配置错误为 2；**配置错误不能当学生零分**。最后运行回归测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_semantic_judge.py -v
```

### 6.5 换成另一个 Java 类

如果新类的方法仍查询同一套网络状态和上述五个已支持的调用，沿用第 6.1～6.4 节：把目录、参考文件内的类名、Suite 的 `name`／`method`／文件路径和参数、Points 都换成实际内容，`"profile": "network_v1"` 不变。评测器目前按 Suite 的 `method` 找方法，并不要求类名等于目录名。**不要仅改类名就复用不相干的测试点**：参考 JML 和前后态仍须反映新方法的真实语义。

## 7. 新方法或新类，但只有单个整数状态

可参考现有完整例子：

- `suites/CounterInterface/checkNonNegative/reference.java`：参考 JML；
- `suites/CounterInterface/checkNonNegative/suite.yaml`：选择 `counter_v1`、方法名、参数、评分；
- `suites/CounterInterface/checkNonNegative/points.yaml`：`{"value": 0}` 等前态，以及 `neighbor_values` 后态生成器；
- `profiles/counter_v1/profile.py`：规定 `getValue()` 返回当前抽象状态的 `value`。

实际操作与第 6 节相同：新建三个方法文件、Suite 选 `"profile": "counter_v1"`、在 Points 里用 `"value"` 写状态、运行 JSON 检查、自检、自评、错误样例评测和回归测试。`counter_v1` 目前只认识 `getValue()`，不认识 `setValue()` 或其他 JML 查询。**JML 表达式中目前也不支持 `\result`**，因此不能靠这个 Profile 对方法返回值直接写断言。状态里的 `-1` 可以出现，但 JML 表达式尚不支持写负数字面量 `-1`。

## 8. 真正的新领域：什么时候必须写 Profile

如果参考 JML 出现 Profile 尚不认识的调用，例如 `getBalance()`，或 Points 状态需要网络／整数 Profile 不认识的字段，例如 `balances`，必须先给它们定义语义。当前没有“只填一个 Suite 文件就自动理解任意 Java 类”的能力。

最稳妥的实现顺序是：

1. **定义抽象状态**：明确只保留 JML 需要观察的字段，确定 Points 中每个字段的 JSON 形状、默认值、对象关系的方向。例如单个整数可照 `profiles/counter_v1/profile.py` 的 `CounterState`。
2. **选择扩展或新建**：同一领域增加一个查询／关系，修改现有 Profile 的状态类和求值；完全不同的领域，在 `profiles/<新名字>_v1/` 新建 `__init__.py` 和 `profile.py`，可复制 `counter_v1` 作最小骨架，再逐一替换其状态、方法名和逻辑。不要把不同领域硬塞进 `network_v1`。
3. **实现状态读取**：在 `state_from_data(data, base=None)` 校验字段、构造状态；若支持后态的 `"copy": "pre"`，必须复制而不是原地修改前态。未知字段要报错。
4. **声明 JML 查询**：在 `allowed_calls` 加入准确名称，在 `symbols` 为每个调用写 `SymbolSignature((参数类型...), 返回类型)`，在 `evaluate_call(name, values, context)` 依据 `context.current` 返回确定结果；未知名称或错误参数应报 `ProfileError`，不能默默返回 false。
5. **处理后态生成**：最初可以只写手工 `post` 点。若需要 `"mode": "mutations"`，再实现 `post_variants(rule, pre, arguments)`，返回“变体名 → 独立后态对象”，不能修改传入的前态。
6. **处理 SMT**：先在 Suite 写 `"solver": {"mode": "off"}`，把有限点评测跑通。若要 `audit` 或 `required`，还需核对 Profile 的 `stateful_calls`、`smt_type_aliases`、`smt_identity_calls`、`smt_axioms`、`state_data_from_smt_calls` 是否完整覆盖领域不变量；否则求解器结论可能不符合实际领域。
7. **注册**：在 `profiles/registry.py` 导入新 Profile 的 `DEFAULT_PROFILE`，并把它加入 `PROFILES` 字典。Suite 的 `"profile"` 必须与其 `name` 完全相同。不需要改通用评测核心。
8. **建 Suite 和 Points**：按第 6 节新建参考 Java、Suite、Points，并让状态数据和调用与 Profile 对应。
9. **验证正反例**：先做 JSON 语法检查，再 `validate_suite.py`，用参考文件自评 100 分，再准备一个错误学生 JML，确认应该暴露的错误确实失分；最后增加针对新 Profile 的单元测试，覆盖正常状态、非法字段、非法调用、前后态和 `\old`。

如果新方法仅仅换了名称或参数，而 JML 中所用查询都已存在，**不需要**因为 `parameter_types()` 里没有该方法而修改现有 Profile：Suite 会提供本方法的参数类型并绑定它。只有新状态或新查询才需要 Profile 代码改动。

## 9. 把新方法接入 Web UI：从 Suite 到学生页面

命令行 Suite 可用，**不等于 Web 自动出现新题**。目前一个 Web 进程启动时只加载一个练习目录。这个目录的 `exercise.json` 必须指向所选 Suite；Web 的“提交审查”才会使用该 Suite 评测学生填入的 JML。以下继续使用第 6 节的 `unfollowUser`，换其他类／方法时只需替换相应的文件名、方法名、题面和空位，流程相同。

### 9.1 先确认服务端 Suite 已能独立评测

先按第 6.1～6.4 节创建并验证 `suites/NetworkInterface/unfollowUser/` 中的 `reference.java`、`suite.yaml`、`points.yaml`；若是新领域，还须先完成第 8 节的 Profile。至少确认 `validate_suite.py` 成功、参考 JML 自评 100 分、一个有意写错的 JML 会失分。**不要**把这些文件复制到学生练习目录或公开的静态资源目录：它们是服务端评测材料。

### 9.2 准备出题输入

在 `Agent/` 下新建 `cases/unfollow_user/requirement.md`，用学生能看到的自然语言写清方法功能、输入、正常／异常情况；不要直接贴参考 JML。对于第 6 节的示例，可以先写：

```markdown
# unfollowUser

输入两个用户 ID：id1 是取消关注的人，id2 是被取消关注的人。
本练习只考虑两个用户都存在、且 id1 已经关注 id2 的正常调用。
调用后，id1 不再关注 id2，id2 的粉丝列表也不再包含 id1。
```

这段题面只是示例；实际发布前应按课程的真实题意补足不允许修改的其它关系、异常或边界条件，并同步修改参考 JML 和测试点。再新建 `cases/unfollow_user/blank_plan.json`，例如：

```json
{
  "status": "teacher_approved",
  "method": "NetworkInterface.unfollowUser",
  "student_owned_blanks": [
    {"id": "PRE", "source_jml_selector": {"clause": "requires", "occurrence": 1}},
    {"id": "POST_FORWARD", "source_jml_selector": {"clause": "ensures", "occurrence": 1}},
    {"id": "POST_INVERSE", "source_jml_selector": {"clause": "ensures", "occurrence": 2}}
  ]
}
```

`method` 的最后一段必须等于 Suite 的 `method`；`source_jml_selector` 按目标方法 JML 块内**同类子句从 1 开始**计数。这个计划表示把第 6.1 节参考文件中的一条 `requires` 和两条 `ensures` 的条件挖空，`assignable` 等未选内容保持不变。请逐项核对空位是否确实应由学生填写。出题工具目前要求参考 JML 紧邻方法声明，且该方法声明写明 `public`；第 6.1 节的示例已满足这两点。如果使用自己的官方接口，先核对它是否符合这一格式。

### 9.3 一条命令生成并绑定 Web 练习包

从仓库根目录先进入 `Agent/`。下面是假设目标练习目录**尚不存在**时的首次发布命令；当前工作区已生成 `exercises/unfollow_user/`，重复执行会因防覆盖机制而停止。要检查或使用现有练习，直接跳到第 9.4 节；需要重新出题时换一个新的 `--exercise-dir`，并核对生成内容。macOS／Linux 命令：

```bash
cd Agent
python3 -m hw9_agent publish-exercise \
  --interface-file ../judge-2027/unit3/spec_judge/suites/NetworkInterface/unfollowUser/reference.java \
  --requirement cases/unfollow_user/requirement.md \
  --blank-plan cases/unfollow_user/blank_plan.json \
  --exercise-dir exercises/unfollow_user \
  --semantic-suite ../judge-2027/unit3/spec_judge/suites/NetworkInterface/unfollowUser/suite.yaml \
  --title "unfollowUser JML 填空练习"
```

Windows PowerShell 同样先进入 `Agent`，将上述命令中的 `python3` 改为 `python`，把每个续行符 `\` 改成 PowerShell 的反引号 `` ` ``；或者直接把整条命令写在一行。路径中的 `/` 在这里也可使用。`--title` 可省略；其余路径从运行命令时所在的 `Agent/` 出发。`--interface-file` 是带**完整参考 JML** 的出题输入；`--semantic-suite` 是服务端评测配置，不会作为题目内容发给浏览器。命令会创建 `exercises/unfollow_user/template.java`、`requirement.md`、`exercise.json` 和空的 `samples/`。目标目录必须事先不存在，以免覆盖已有学生提交样例或发布物。

发布命令会检查 Suite 文件存在、能解析、其中的 `method` 与练习方法名相同，然后自动把 `semantic_suite` 写进 `exercise.json`。因此新建练习时**不必手算相对路径，也不必手写 `exercise.json`**。它不会替你审核参考规格或测试点质量，故第 9.1 节仍不可省略。

### 9.4 发布前核对并启动

打开生成的 `exercises/unfollow_user/template.java`，确认只在预期的三处出现 `{{PRE}}`、`{{POST_FORWARD}}`、`{{POST_INVERSE}}`，其它 Java/JML 未意外变化。打开 `exercises/unfollow_user/exercise.json`，应看到 `"method": "unfollowUser"`，以及类似下面的服务器端路径：

```json
"semantic_suite": "../judge-2027/unit3/spec_judge/suites/NetworkInterface/unfollowUser/suite.yaml"
```

这个值**相对于 `Agent/`**，而非相对于 `exercise.json`；发布命令会自动计算，实际值以生成结果为准。检查 `exercises/unfollow_user/` 内没有参考答案、Points 或隐藏样例。若要放学生可见的演示 Java，可放进该目录的 `samples/`，但不要放标准答案；添加后重启 Web 才会更新样例列表。

仍在 `Agent/` 运行：

```bash
python3 -m hw9_agent web --exercise-dir exercises/unfollow_user --host 127.0.0.1 --port 8000
```

PowerShell 把 `python3` 改成 `python`。在浏览器打开 `http://127.0.0.1:8000/`，应看到新标题和 `unfollowUser` 的空位。填完空位后点“提交审查”，核对确定性评分确实来自新 Suite；无 DeepSeek API 密钥时仍会直接显示评测脚本结果，有密钥时再追加模型建议。可用正确填法和故意错误填法各试一次。新练习默认没有演示案例，因此不会显示“运行双检测”；该按钮只属于另行配置了 `consistency_demo_cases` 的独立演示路径，**不用于验证这个新 Suite**。

### 9.5 已有练习包、增加测试点、同时发布多道题

若练习包已存在，`publish-exercise` 不会覆盖它。只需在其 `exercise.json` 的顶层增加或修改 `semantic_suite`，值写成从 `Agent/` 到 Suite 文件的相对路径，注意 JSON 逗号；然后**重启 Web 进程**，因为练习配置在启动时加载。应同时核对练习的 `method` 与 Suite 的 `method` 相同。若需重做模板或空位，建议使用新的练习目录重新发布，再人工核对，不要直接覆盖旧包。

若只是给**同一个方法的现有 Suite 加测试点**，按第 3～5 节修改其 Points 文件并验证即可；下一次“提交审查”会重新运行评测脚本读取点集，通常不必重启 Web。页面不会列出隐藏测试点，只会反映新的分数和诊断；浏览器中已经显示的旧结果不会自动重算，需要重新提交。

目前页面没有“选择题目／方法”的下拉框。要让同一时间两道题都可访问，可分别启动两个 Web 进程，传入不同的 `--exercise-dir` 和 `--port`；单个进程只服务启动时指定的那道题。要实现一个入口切换多题，需另行增加路由和练习目录列表，当前版本尚未提供。

## 10. 报错时按这个顺序排查

1. `json.tool` 失败：先检查双引号、逗号、花括号；文件虽然叫 `.yaml`，现在用的是 JSON 兼容语法。
2. `reference 或 points 文件不存在`：路径相对于 Suite 文件目录，不是终端当前目录。
3. `未知 profile`：检查 Suite 的 `profile` 名称以及 `profiles/registry.py`。
4. `未找到方法`／`未找到紧邻方法的 JML 注释块`：参考或学生 Java 的方法名要与 Suite 一致，JML 须写在方法前的 `/*@ ... @*/` 中。
5. `未定义的变量`／`不允许调用接口外函数`：检查 Suite 的 `parameters` 及 Profile 的 `allowed_calls`、`symbols`；不要在 JML 中使用尚未实现的查询。
6. `参数必须恰好是 ...`：每个点的 `args` 键名必须与 Suite 的 `parameters` 一模一样，包括无参数时的 `{}`。
7. `未知 fixture`／`fixture 出现循环引用`：检查 `use` 名称和引用链。
8. `关系的端点必须出现在 users 中`：检查网络状态的 `users` 是否包含每条边的两个端点。
9. `重复 observation`：检查是否有两个相同参数、前态和后态的同类点；换 ID 不能解决，需删去或改成有区分度的情形。
10. 参考自评 100，但错误 JML 也 100：这不是配置成功的充分证明。检查错误是否真的改变所选点上的真值；补覆盖该错误的前态／候选后态，观察 `mutations.survivors` 是否减少。

## 11. 当前范围与可进一步简化之处

当前最省事的路径是“复制相近 Suite 的**文件结构**，审核并重写参考 JML 与点集，再跑验证”。不要直接照搬测试点的语义。现在的加载器已支持不同方法名、不同参数、不同合同子句数量和多种 Profile，但新方法仍需手工建立三个文件；新领域还需写代码和注册。后续可以考虑开发 `new_suite` 脚手架，按所选 Profile 自动生成参考文件占位、Suite、Points 模板，并在创建时调用校验器；也可让校验器打印每个点被参考 JML 接受／拒绝的摘要，辅助选点。**这些只是优化建议，本次没有实现。**

另外，本评测器只支持主 [README](README.md) 所述的 JML 子集，不是完整 JML。固定点通过只表示在当前测试点上与参考 JML 一致；可选 SMT 也只覆盖当前可建模的子集。部署前仍要由你审核参考规格、状态抽象和测试点覆盖是否符合题意。
