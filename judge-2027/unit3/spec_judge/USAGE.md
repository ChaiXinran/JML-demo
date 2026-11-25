# 手把手添加 JML 一致性测试点

这份说明面向第一次维护 JML–JML 评测器的人。按顺序做即可；不需要先理解求解器或评测核心源码。本文只讲评测机组件中的参考 JML、学生提交和测试集。学生 Java 实现的运行验证、OpenJML 和 Web 练习由协作者分别维护，不是本组件的输入依赖。

- **给 HW9、HW10、HW11 补测试点**：直接看[三道独立 JML 题的加点步骤](#add-array-points)。提交路径和 CLI 命令见[三题评测入口](#array-exercises)。
- **给旧网络题补点**：看[前态点](#3-给-followuser-手工增加一个前态点)和[前后态点](#4-给-followuser-手工增加一个前后态点)。
- **增加新方法或新领域**：看下文第 6～8 节。

## 0. 先弄清楚要改什么

一次评测由四样东西组成：

| 名称    | 作用                                                             | `followUser` 对应文件                               |
| ------- | ---------------------------------------------------------------- | ----------------------------------------------------- |
| 参考源  | 方法声明前写着经审核的参考 JML；它是判定依据                     | `suites/NetworkInterface/followUser/reference.java` |
| Suite   | 指定方法、Profile、参考文件、测试点文件和评分设置                | `suites/NetworkInterface/followUser/suite.yaml`     |
| Points  | 列出输入参数、调用前状态、候选后态与需要检验的候选返回值 | `suites/NetworkInterface/followUser/points.yaml`    |
| Profile | 解释状态字段及 JML 中的方法调用，例如 `containsUser(1)` 的含义 | `profiles/network_v1/profile.py`                    |

下文所有相对路径，除非特别说明，均以 `judge-2027/unit3/spec_judge/` 为当前目录。Suite 里的 `reference` 和 `points` 路径则**相对于 Suite 文件所在目录**，不是相对于运行命令的目录。`followUser` 的权威参考源已收在其方法目录中，正式 suite 不依赖 `Agent/`。

每个方法各有一个 `suites/<类名>/<方法名>/` 目录：`suite.yaml` 是评测入口，`points.yaml` 放测试点，本方法专用的参考文件和错误样例分别可放 `reference.java`、`wrong.java`。添加一个新的测试点时仍写入该方法的**同一个** `points.yaml` 的 `points` 数组，不要为每个测试点建目录。

先判断属于哪种情况：

1. **同一个 `followUser`，只增加测试情形**：只改 `followUser/points.yaml`，见第 2～5 节。
2. **新方法或新类，但状态和 JML 查询仍是“用户／关注／粉丝／屏蔽”**：新建参考 Java、Suite、Points，继续用 `network_v1`，见第 6 节。类名不同并不必然需要新 Profile。
3. **新方法或新类，状态是一个整数，JML 只查询 `getValue()`**：可继续用 `counter_v1`，见第 7 节。
4. **全新领域状态或新的 JML 查询**：除了上述文件，还必须实现或扩展 Profile，见第 8 节。仅写 JSON 格式的测试点无法让评测器理解未知的查询方法。

新版三道独立 JML 题使用 `array_v1`，操作见[三题评测与测试点](#array-exercises)。下文以 `followUser` 演示原有 Profile 的维护。

### 0.1 CLI 提交格式

正式入口形状为：

```bash
python3 semantic_check.py SUBMISSION --suite SUITE --json
```

`SUBMISSION` 可以是 UTF-8 `.java` 或 `.jml` 文件，也可以写 `-` 从标准输入读取。文件内容必须包含唯一的 Suite 目标方法声明，以及归属于该声明的唯一、完整 `/*@ ... @*/` 合同块。数组 Suite 也接受连续的 `//@` 合同行。合同块与方法声明之间允许夹普通注释；合同块内部的普通注释不保证支持。参数名称和 Java 类型必须匹配 Suite；返回类型、是否 `static` 和 `throws` 集合必须匹配参考方法声明。`safe`／`pure` 声明标记可以保留。重复/重载目标方法、多个相邻合同块、未完成行为或未知条款（例如 `invariant`、`model`）都会报学生规格错误，不会被忽略。只有 JML 子句而没有方法声明的 sidecar 不符合输入约定；`.jml` 扩展名也不表示支持完整 OpenJML sidecar 语法。源码识别只覆盖本组件需要的受限格式，不是完整 Java 解析器；评测器不编译或运行 Java。

正常 JSON 结果带 `schema_version: 1`、`status: "PASS"` 或 `"FAIL"`，以及兼容的 `score`、`passed`、`diagnostics` 字段。`coverage`、`evaluation` 和 `solver` 可能缺省；例如学生格式或编码错误会产生分数和诊断，但没有完整覆盖统计或求解器结果。退出码 `0` 表示 PASS，`1` 表示 FAIL。提交文件 IO、参数或 Suite 配置错误退出码为 `2`，JSON 使用 `status: "ERROR"` 且不包含 `score`、`passed`；详细错误写入标准错误。评测机应把 ERROR 视作评测配置/输入错误，不能当作学生零分。

资源上限为：学生源码不超过 1 MiB；每条表达式最多 4096 个 token；语法嵌套最多 32 层；表达式 AST 深度最多 128；整数文字最多 4096 位。学生提交超限属于 `FAIL`（JSON、退出码 `1`）；参考源超限或解析失败属于评测端 `ERROR`（JSON、退出码 `2`，不含学生分数）。

## 1. 准备环境，并跑通原有例子

在仓库根目录打开终端，先进入评测目录：

```bash
cd judge-2027/unit3/spec_judge
```

以下命令使用 macOS/Linux 的 `python3`。Windows PowerShell 先运行：

```powershell
Set-Location judge-2027\unit3\spec_judge
$env:PYTHONDONTWRITEBYTECODE = "1"
```

后续命令将 `python3` 换成 `python`，移除 Bash 形式的 `PYTHONDONTWRITEBYTECODE=1` 前缀，并把行末 `\` 换成 PowerShell 反引号 `` ` ``；也可以把命令合并成一行。固定测试点模式只需要 Python 标准库，不需要先安装 Z3；若 `solver.mode` 为 `required`，则必须先按 [README](README.md#可选安装-smt) 安装 `requirements-smt.txt`。

先验证已有 Suite：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 validate_suite.py suites/NetworkInterface/followUser/suite.yaml
```

应看到 `"valid": true`、`"profile": "network_v1"`、`"method": "followUser"`，以及前态数、后态数和变异测试结果。再用参考文件充当“学生提交”，确认评测入口可用：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 semantic_check.py \
  suites/NetworkInterface/followUser/reference.java \
  --suite suites/NetworkInterface/followUser/suite.yaml --json
```

应看到 `"schema_version": 1`、`"status": "PASS"`、`"score": 100`、`"passed": true`。如果这里还不能运行，先解决环境或原有配置问题，避免把旧问题误认为新测试点造成的。

## 2. 测试点究竟在测什么

一个测试点不是一段 Java 程序，也不是一个“预期输出”。它是给 JML 表达式求值的一张状态快照：

- `args`：调用方法时传入的参数。例如 `{"id1": 1, "id2": 2}`。键名必须和 Suite 的 `parameters` 完全一致；无参数方法写 `{}`。
- `pre`：调用方法**之前**的状态。`requires` 和本项目受限语义下的 `signals` 在这里求值。
- `kind: "pre"`：比较正常行为的适用条件、异常分支和有效的可修改范围。省略 `post` 和 `result`。
- `kind: "post"`：还必须给出 `post`，即一个**候选**调用后状态，用于比较双方 `ensures` 是否接受该状态。它可以故意不正确，正是为了测出漏写或写错的后置条件。

评测器在同一个点上分别求值参考 JML 和学生 JML：两者同意时该点通过，不同意时该点发现语义差异。数组题的 `result` 是拿来检验的候选返回值，可以故意写错。可选的 `reference_accepts` 用来核对参考 JML 是否按题意接受或拒绝这个候选。评分依据仍来自参考 JML。有限测试点只比较已列出的情形，详见[三题加点步骤](#add-array-points)。

原有网络和计数题比较合同声明的有效 frame。数组题还用 frame 检查候选后态的可观察变化。这里的 frame 是允许写入的位置范围，整个过程不运行 Java 方法体。

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

<a id="add-network-points"></a>

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

继续用上面的前态，检查已有反向关注时，参考和学生规格是否都接受新增正向关注及对应粉丝记录的后态：

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

这个 `post` 是参考 JML 应当接受的成功候选。候选保留了原有反向关系，但当前参考 JML 只约束新增的关注和粉丝记录。若要评测是否禁止删除原有反向关系，需先确认题意并在参考 JML 中加上相应约束，再增加一个删除反向关系的错误候选。要测“只更新关注、不更新粉丝”，可以复制上面的点，换一个 `id`，把 `add` 改为 `{"following": [[1, 2]]}`；此时参考 JML 会拒绝这个候选。即使 ID 不同，重复加入同一组 `args`、`pre`、`post` 也会报 `重复 observation`。

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
  "args": {"id1": [1, 3], "id2": [1, 4]},
  "pre": [{"use": "two_users"}]
}
```

它生成 4 个 `pre` 点，ID 从 `new_pre_grid.a0.s0` 开始。生成 `post` 点时，把 `kind` 改成 `post` 并增加非空的 `"post": [{"copy": "pre"}, ...]` 数组；组合数是各参数候选数 × 前态数 × 后态数。生成器的 `args` 必须列出 Suite 的全部参数，每个参数域、`pre` 和 `post` 列表都不能是空数组。无参数方法写 `"args": {}`，仍会产生一组参数组合。生成点也会和手写点检查重复 observation；不要无意把已有点再生成一遍。

### 5.3 使用 Profile 已实现的后态变体

`network_v1` 已有 `follow_pair` 规则；现有 `followUser/points.yaml` 正在使用它。规则根据给定前态和参数构造 `correct`、`omit_inverse`、`omit_forward`、`reverse_direction` 等候选后态。如果要增加一批不同参数或不同前态的相同错误模式，可照现有 `"mode": "mutations"` 生成器新增一组，但新的 `id` 必须唯一，且前态必须满足“两个不同、已存在、尚无目标方向关注关系”的规则前提。否则 `validate_suite.py` 会报告规则无法应用。当前 `followUser` 有 12 个手写前态点和 13 个后态点（其中 12 个由生成器产生），覆盖 `id1 == 0`、3/4 等新 ID、调换参数顺序、正确更新、遗漏更新和反向关系后态；因此额外加上 `id1 == 1` 的正常条件会被识别为过度限制。`counter_v1` 对应的现成规则是 `neighbor_values`。

新点可以设置 `"weight": 2`（正数，默认 1）、`"public": false`（布尔值，默认 false）、`"tags": ["boundary"]`（字符串数组）。权重会影响评分；它们不定义预期答案。初次加点建议先保留默认权重，以免无意改变既有评分比例。

### 5.4 检查变异质量并审核等价项

`validate_suite.py` 报告原始 `mutations.total`、`killed`、`score`、`survivors`，也报告 `reviewed_equivalent`、`unexpected_survivors` 和 `effective_score`。原始值保留所有确定性变异的计数；`reviewed_equivalent` 列出经人工审核的变异，`unexpected_survivors` 是仍未被测试点杀死且未获审核豁免的项。`quality.min_mutation_score` 应按剔除审核等价项后的 `effective_score` 判断。

若确认一个存活变异只因 Profile 已保证的领域不变量而等价，在 Suite 的 `quality.equivalent_mutations` 中填入“变异 ID → 该完整变异源码 UTF-8 字节的 SHA-256”。先检查变异源码的语义，再生成哈希并复核 ID；不要只凭 `survivors` 名称自动豁免。之后若变异源码哈希变化、配置中的 ID 不再产生，或新增测试点杀死了已豁免项，预检会报错，必须重新人工审核。不要通过放宽点集状态域、加入不合法状态或下调最低分来消掉质量错误。

当前 `followUser` 的原始识别率为 `25/26`（96%），审核等价项是 `delete_conjunct.8`；`unfollowUser` 为 `6/7`（86%），审核等价项是 `delete_conjunct.2`。两者的 `effective_score` 都是 100，`unexpected_survivors` 均为空，且 `min_mutation_score` 仍为 100。审核记录精确源码哈希，源码变动后不能沿用旧豁免。

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

这里的参考 JML 是**示范规格**，实际课程使用前必须由你依据真实题意审核，不能因为它能通过自检就认定它正确。Suite 的 `method`、`parameters` 必须与该声明的方法名、参数名称和类型一致。返回类型、是否 `static` 和 `throws` 集合会与参考声明比较。参考源和提交都必须只有一个对应的目标声明，且目标方法前只放唯一完整的 `/*@ ... @*/` 块；合同与声明之间可以有普通注释，块内普通注释不保证支持。`safe`／`pure` 声明标记允许存在。多个相邻合同块、未完成行为、`signals_only`、`invariant`、`model` 等未知条款会被拒绝。源码识别不是完整 Java 解析器；评测器不运行方法体。

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

`parameters` 的键名和类型要与 JML 使用的参数一致；无参数方法写 `{}`。`contract_shape` 限制学生提交的 `requires`、`ensures`、`signals` 数量：整数表示精确数量，也可用 `{"min": 1}` 等范围。`grading` 必须包含四个区域，值是非负整数，至少一个大于 0；上例总和为 100。`solver.mode: "off"` 不需要安装 Z3；确定测试点足够后可参考主 README 决定是否改成 `audit`。初建时可不写 `quality`；若启用最低变异分数，应先按第 5.4 节人工审核任何等价变异，再配置 `min_mutation_score`。等价项必须绑定该变异的确切源码哈希，不能靠放宽点集或状态域凑分。

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

最后一条用参考文件自评，预期 `schema_version: 1`、`status: "PASS"`、`score: 100` 且 `passed: true`。然后在同一方法目录另存一个**故意错误**的学生源，例如 `wrong.java`：保留第二个 `ensures` 子句但把它的条件改成 `true`，再以同一个 Suite 运行 `semantic_check.py suites/NetworkInterface/unfollowUser/wrong.java --suite suites/NetworkInterface/unfollowUser/suite.yaml --json`。预期 `status: "FAIL"` 且至少一个相关区域失分；若错误样例仍得 100，说明测试点没有区分出这类错误，应补候选后态再验证。不要直接删除该子句：本示例的 `contract_shape` 要求恰好两条 `ensures`，删除会先触发结构问题，无法单独验证点集的区分能力。`validate_suite.py` 的 `mutations.survivors` 也会提示典型错误中哪些还没被测试点识别。

当前这份 `unfollowUser` Suite 的原始变异识别率是 `6/7 ≈ 86%`。唯一存活的 `delete_conjunct.2` 删除了前置条件中显式写出的“两个用户存在”，只保留“id1 关注 id2”。在 `network_v1` 中，合法的关注关系已经保证两端用户存在，所以这个变异在当前抽象模型内等价，并不表示必须再加一个测试点。Suite 以确切源码哈希审核了它；预检保留原始 6/7，同时报告 `reviewed_equivalent: ["delete_conjunct.2"]`、`unexpected_survivors: []` 和 `effective_score: 100`，`min_mutation_score` 仍是 100。以后修改变异或测试点时必须重新检查这个审核结论。变异识别率不是学生分数；不要加入不合法状态来提高表面分数。

参考合同通过自评的退出码为 0，学生合同不一致为 1，Suite／参考文件／提交读取或参数错误为 2；退出码 2 返回 `status: "ERROR"`，不包含学生分数，**配置或输入错误不能当学生零分**。最后运行回归测试：

```bash
python3 run_tests.py
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

## 9. 评测机接入与测试集发布

本节说明怎样验证一套 JML–JML 评测、制作独立组件包并把学生提交交给 CLI。它不配置 Web 练习，也不执行 Java 方法或 OpenJML。CLI 当前一次评一个提交源和一个 Suite；多方法或多 Suite 的分数汇总由评测机的调用方按课程协议处理，本组件不定义汇总规则。

### 9.1 确认评测材料完整并留在服务端

每个方法使用一个 `suites/<类名>/<方法名>/` 目录，至少包含：

- `reference.java`：已审核的参考 JML 和目标方法声明；
- `suite.yaml`：目标方法、Profile、评分区域和相对文件路径；
- `points.yaml`：有限抽象状态上的前态和候选后态。

领域语义由 `profiles/` 中的 Profile 提供。参考源、suite、points、Profile 和隐藏样例都属于评测侧数据；它们随内部评测机包发布或安装，不能随学生提交包公开。新增方法或新领域按第 6～8 节准备这些内容。

### 9.2 验证正例、反例和完整回归

以 `followUser` 为例，在 `spec_judge/` 目录执行：

```bash
python3 validate_suite.py suites/NetworkInterface/followUser/suite.yaml
python3 semantic_check.py \
  suites/NetworkInterface/followUser/reference.java \
  --suite suites/NetworkInterface/followUser/suite.yaml --json
python3 semantic_check.py \
  tests/fixtures/followUser/wrong-relation-direction.java \
  --suite suites/NetworkInterface/followUser/suite.yaml --json
python3 run_tests.py
```

第一条检查 suite、参考合同和测试点；参考文件自评应返回 `status: "PASS"`、`score: 100`。错误 fixture 应返回 `status: "FAIL"` 和退出码 `1`。最后一条运行组件正式 JML–JML 回归集，不需要安装 Java 或 OpenJML。新增或改动 Profile 时也要补相应测试，再运行正式回归。

### 9.3 构建和检查独立评测包

完成套件校验与回归后，从 `spec_judge/` 目录构建发布 ZIP。构建器不会覆盖已有 ZIP，因此每次先创建新的临时目录，避免与历史归档重名；命令输出 JSON 中的 `output` 字段记录了归档的完整路径，`sha256` 可作为部署版本标识。

```bash
release_dir="$(mktemp -d /tmp/jml-judge.XXXXXX)"
python3 build_release.py --output "$release_dir/jml-judge.zip"
unzip -l "$release_dir/jml-judge.zip"
unzip -q "$release_dir/jml-judge.zip" -d "$release_dir/unpacked"
cd "$release_dir/unpacked/spec_judge"
python3 run_tests.py
python3 validate_suite.py suites/NetworkInterface/followUser/suite.yaml
python3 semantic_check.py \
  suites/NetworkInterface/followUser/reference.java \
  --suite suites/NetworkInterface/followUser/suite.yaml --json
```

PowerShell 可使用 GUID 创建同样唯一的输出目录，`Expand-Archive` 用于解压：

```powershell
$ReleaseDir = Join-Path ([System.IO.Path]::GetTempPath()) ("jml-judge-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null
$ArchivePath = Join-Path $ReleaseDir "jml-judge.zip"
python build_release.py --output $ArchivePath
$UnpackDir = Join-Path $ReleaseDir "unpacked"
Expand-Archive -LiteralPath $ArchivePath -DestinationPath $UnpackDir
Set-Location (Join-Path $UnpackDir "spec_judge")
python run_tests.py
python validate_suite.py suites/NetworkInterface/followUser/suite.yaml
python semantic_check.py suites/NetworkInterface/followUser/reference.java --suite suites/NetworkInterface/followUser/suite.yaml --json
```

归档内以 `spec_judge/` 为根目录，包含正式 CLI、Profiles、Suites、参考源和测试点。解压后的回归、自评和 suite 校验能确认包内材料可用。独立包不需要 `Agent/`、Java 或 OpenJML；如果 suite 选择 `solver.mode: "required"`，评测环境仍须安装 `requirements-smt.txt` 中的依赖。把该包部署到评测侧，避免将含参考答案或隐藏测试点的归档发给学生。

### 9.4 将学生提交交给 CLI

评测机可把已读取的 UTF-8 提交内容通过标准输入交给进程，并将结果流分别捕获：

```bash
python3 semantic_check.py - \
  --suite suites/NetworkInterface/followUser/suite.yaml \
  --json < submission.java
```

提交也可以是含目标方法声明及归属合同块的 `.jml` 文件；合同块与声明之间可夹普通注释，文件扩展名不改变解析方式。CLI 将 JSON 结果写到标准输出，详细 IO／参数／Suite 配置错误写到标准错误。`status: "PASS"`、`"FAIL"`、`"ERROR"` 分别表示通过、不一致、无法执行评测。调用方应保留退出码：`0` 对应 PASS，`1` 对应 FAIL，`2` 对应 ERROR；ERROR 不应转换为学生分数。协议字段与上机步骤见同目录 [INTEGRATION.md](INTEGRATION.md) 和 [ON_MACHINE.md](ON_MACHINE.md)。

### 9.5 更新测试集并重新发布

给已有方法加点，修改对应的 `points.yaml`。数组后态点逐条写在 `points` 中，并填写候选 `result`。先执行[加点后的正反例检查](#check-array-points)，再运行 `python3 run_tests.py` 并重新构建评测 ZIP。调整参考 JML 或评分策略时，也要复核该方法的正反例和质量检查。新增方法的做法见第 6～8 节。

发布包是评测机组件，不是学生练习包。Web 页面、课程题面、学生 Java 实现及 JML–Java/OpenJML 验证由协作者按其接口维护；不要把这些流程或依赖加入本组件的 Suite 或发布脚本。

## 10. 报错时按这个顺序排查

1. `json.tool` 失败：先检查双引号、逗号、花括号；文件虽然叫 `.yaml`，现在用的是 JSON 兼容语法。
2. `reference 或 points 文件不存在`：路径相对于 Suite 文件目录，不是终端当前目录。
3. `未知 profile`：检查 Suite 的 `profile` 名称以及 `profiles/registry.py`。
4. `未找到方法`／`未找到紧邻方法的 JML 注释块`：核对源文件中的方法名和合同位置。原有 Suite 接受一个完整的 `/*@ ... @*/` 合同块。数组 Suite 也接受连续的 `//@` 合同行。
5. `未定义的变量`／`不允许调用接口外函数`：检查 Suite 的 `parameters` 及 Profile 的 `allowed_calls`、`symbols`；不要在 JML 中使用尚未实现的查询。
6. `参数必须恰好是 ...`：每个点的 `args` 键名必须与 Suite 的 `parameters` 一模一样，包括无参数时的 `{}`。
7. `未知 fixture`／`fixture 出现循环引用`：检查 `use` 名称和引用链。
8. `关系的端点必须出现在 users 中`：检查网络状态的 `users` 是否包含每条边的两个端点。
9. `重复 observation`：同类点如果参数、前态、后态和候选返回值全部相同，就是重复点。仅改 ID、权重或 `reference_accepts` 仍算重复。
10. 参考自评 100，但错误 JML 也 100：这不是配置成功的充分证明。检查错误是否真的改变所选点上的真值；补覆盖该错误的前态／候选后态，观察 `mutations.survivors` 是否减少。

## 11. 当前范围与可进一步简化之处

当前最省事的路径是“复制相近 Suite 的**文件结构**，审核并重写参考 JML 与点集，再跑验证”。不要直接照搬测试点的语义。现在的加载器已支持不同方法名、不同参数、不同合同子句数量和多种 Profile，但新方法仍需手工建立三个文件；新领域还需写代码和注册。后续可以考虑开发 `new_suite` 脚手架，按所选 Profile 自动生成参考文件占位、Suite、Points 模板，并在创建时调用校验器；也可让校验器打印每个点被参考 JML 接受／拒绝的摘要，辅助选点。**这些只是优化建议，本次没有实现。**

另外，本评测器只支持主 [README](README.md) 所述的 JML 子集，不是完整 JML。固定点通过只表示在当前测试点上与参考 JML 一致；可选 SMT 也只覆盖当前可建模的子集。部署前仍要由你审核参考规格、状态抽象和测试点覆盖是否符合题意。


<a id="array-exercises"></a>

## 2027 三道独立 JML 题

学生将规格写在项目的 `JML/JML.java`。评测端根据周次选择对应的 Suite，保留指导书给出的方法签名与参数名。进入 `judge-2027/unit3/spec_judge/` 后，把下面的 `/path/to/submission` 换成实际提交目录，按周次执行其中一条：

```sh
python3 semantic_check.py /path/to/submission/JML/JML.java --suite suites/JML/firstDuplicateIndex/suite.yaml --json
python3 semantic_check.py /path/to/submission/JML/JML.java --suite suites/JML/reserveSeats/suite.yaml --json
python3 semantic_check.py /path/to/submission/JML/JML.java --suite suites/JML/longestFreeBlock/suite.yaml --json
```

三题都接受紧邻目标方法的单个 `/*@ ... @*/` 块或连续 `//@` 行。HW9 可以保留题面给的行注释写法。HW10 的字段 `occupied` 由观察点提供，评测器不会执行学生字段的初始化代码。

- 表达式支持一维 `int[]`、`boolean[]`、`null`、数组下标和 `.length`，以及用数学整数求值的 `+`、`-`。数组之间的 `==` 比较引用身份。用 `\old(occupied[i])` 读取旧元素，用 `occupied == \old(occupied)` 判断字段是否仍引用原数组。
- `\result` 只在 `ensures` 中可用，不能放在 `\old` 内。支持短路蕴含 `==>` 和等价 `<==>`。
- 量词支持写成 `(\forall int i; 范围; 条件)`、`\exists` 和 `\num_of`，以及多变量和嵌套。范围中用合取的整数比较给每个变量提供可推导的有限上下界，例如 `0 <= i && i < j && j < ids.length`。边界推导支持整数加减法移项，例如也可写 `i + 1 <= j`，或用 `start + length <= occupied.length` 约束区间终点。空范围的全称为真，存在为假，计数为零。求值有总运算预算，超限或无法求值会给出学生规格诊断。
- `signals_only` 比较明确允许的异常类型。数组 frame 支持 `\nothing`、`\everything`、字段以及 `occupied[i]`、`occupied[*]`、`occupied[start .. end]` 等位置，区间端点包含在内。评测器在前态上求出允许写入的槽位，并用后态检查实际可观察的变化。
- 三题只做固定点评测，结论覆盖的是已配置的输入和候选结果。无需 Z3，也不编译学生代码。

<a id="add-array-points"></a>

### 第一步：找到这一题的 points.yaml

| 周次 | 要编辑的文件 | 数组写在哪里 | 后态点的 `result` |
| --- | --- | --- | --- |
| HW9 首个重复下标 | [firstDuplicateIndex/points.yaml](suites/JML/firstDuplicateIndex/points.yaml) | `args.ids`，整数数组 | 整数，如 `2` 或 `-1` |
| HW10 座位预订 | [reserveSeats/points.yaml](suites/JML/reserveSeats/points.yaml) | `pre.occupied`，布尔数组 | `true` 或 `false` |
| HW11 最长连续空座 | [longestFreeBlock/points.yaml](suites/JML/longestFreeBlock/points.yaml) | `args.occupied`，布尔数组 | 整数数组，如 `[1, 2]` 或 `[]` |

打开文件，找到顶层 `"points": [`。把新点加在这个数组的最后一个 `]` 之前。前一个对象后加逗号，新数组的最后一个对象后不留逗号。下方的 JSON 围栏只是展示格式，复制时只复制其中的内容。文件扩展名虽然是 `.yaml`，内容要按 JSON 写，包括双引号和小写 `true`、`false`、`null`。

每个点都需要唯一的 `id`、`kind`、`args` 和 `pre`。已有题补点通常只改这个文件。数组后态点手写在 `points` 内，旧网络题的后态生成器不会为它们生成 `result`。

### 第二步：写出能区分正误的情形

先想清楚要抓哪种错解。漏掉异常分支、把合法输入排除在外，或写错允许修改的范围，用 `pre` 点。正确输入上给错返回值、漏改元素、改了区间外元素，用 `post` 点。如果同一个输入既要检查能不能调用，又要检查返回结果，可以分别加一个前态点和一个后态点。

- **前态点**带 `args` 和 `pre`。评测器在前态上比较正常行为是否适用、允许哪些异常和哪些位置可写。省略 `post`、`result` 和 `reference_accepts`。例如要检查 HW10 越界是否只允许 `IllegalArgumentException`，这里无需伪造返回值。
- **数组后态点**另带 `post` 和 `result`。它们描述一个候选正常返回，包括故意错误的返回值或状态。查询题没有对象状态变化，`pre` 和 `post` 均写 `{}`。预订题要写座位前态和候选后态。
- **`reference_accepts` 建议给数组后态点填写**。正确候选写 `true`，错误候选写 `false`。预检和实际评测会核对参考 JML 的判定，写反时会报配置错误。学生规格和参考规格都拒绝同一个错误候选，该点就通过。把字段改成 `true` 不会把错解变成正确答案。

数组最多 64 个元素。整数按 Java `int` 取值，布尔值直接写 `true` / `false`。查询题可以把 `null` 写在数组参数处以测试非空前置条件，也可为 HW11 写 `"result": null` 测试拒绝空引用返回。HW10 的 `pre.occupied` 必须是非空引用的布尔数组，允许长度为零的 `[]`。

#### HW9：同一组签到记录，分别给正确和错误下标

对 `[4, 9, 9, 4]`，第一次重复发生在下标 2，返回 3 则是选了后一条重复记录。把下面两个对象一起加入 HW9 的 `points` 数组：

```json
{
  "id": "duplicate_two_different_values_first",
  "kind": "post",
  "args": {"ids": [4, 9, 9, 4]},
  "pre": {},
  "post": {},
  "result": 2,
  "reference_accepts": true
},
{
  "id": "duplicate_two_different_values_later",
  "kind": "post",
  "args": {"ids": [4, 9, 9, 4]},
  "pre": {},
  "post": {},
  "result": 3,
  "reference_accepts": false
}
```

这两点的输入和前后态相同，但候选返回值不同，因此不是重复点。只换 `id`、权重或参考判定标记则没有增加新的观察。

#### HW10：写出座位前后态，再指定返回值

预订下标 2 到 5 共四个空座，成功后这四格应变为 `true`。第一个后态点是正确候选。第二个点保持相同的成功返回值，故意多改下标 6。第三个点把请求换成从下标 6 开始预订两个座位，用来检查异常分支。

```json
{
  "id": "reserve_four_seats_success",
  "kind": "post",
  "args": {"start": 2, "count": 4},
  "pre": {"occupied": [false, true, false, false, false, false, false]},
  "post": {"copy": "pre", "occupied": [false, true, true, true, true, true, false]},
  "result": true,
  "reference_accepts": true
},
{
  "id": "reserve_four_seats_touches_extra_seat",
  "kind": "post",
  "args": {"start": 2, "count": 4},
  "pre": {"occupied": [false, true, false, false, false, false, false]},
  "post": {"copy": "pre", "occupied": [false, true, true, true, true, true, true]},
  "result": true,
  "reference_accepts": false
},
{
  "id": "reserve_past_last_seat",
  "kind": "pre",
  "args": {"start": 6, "count": 2},
  "pre": {"occupied": [false, true, false, false, false, false, false]}
}
```

在 HW10 中，`"post": {"copy": "pre"}` 表示仍引用原数组且内容保持原样，适合构造预订冲突、返回 `false` 的正确候选。加上 `occupied` 则填写整份候选后态数组，长度应与前态一致。若想专门测出「把数组换成新对象」，在 `post` 里同时保留 `"copy": "pre"`、写出 `occupied`，再加 `"fresh": true`。即使元素相同，引用也发生了变化，应将该候选的 `reference_accepts` 写为 `false`。还可以复制四座成功点，把新点的 `result` 改为 `false`，验证「座位改对了但返回值写反」能被识别。

#### HW11：同时检验正确区间和并列错解

`[true, false, false, true, false, false]` 有两个长度为 2 的空座区间。正确返回 `[1, 2]`，选择较晚的 `[4, 2]` 应被拒绝。

```json
{
  "id": "longest_equal_runs_choose_first",
  "kind": "post",
  "args": {"occupied": [true, false, false, true, false, false]},
  "pre": {},
  "post": {},
  "result": [1, 2],
  "reference_accepts": true
},
{
  "id": "longest_equal_runs_reject_later",
  "kind": "post",
  "args": {"occupied": [true, false, false, true, false, false]},
  "pre": {},
  "post": {},
  "result": [4, 2],
  "reference_accepts": false
}
```

还可测试空数组、全部占用、只有一段空座，以及结果数组太长或太短。无空座时的正确结果是 `[]`。

<a id="check-array-points"></a>

### 第三步：分别验证点集、标准答案和错解

以下以 HW10 为例。在仓库根目录先进入 `judge-2027/unit3/spec_judge`。如果改的是 HW9 或 HW11，把命令中的 `reserveSeats` 换成上表的方法名。PowerShell 下可把 `python3` 换成 `python`。

```sh
python3 -m json.tool suites/JML/reserveSeats/points.yaml
python3 validate_suite.py suites/JML/reserveSeats/suite.yaml
python3 semantic_check.py suites/JML/reserveSeats/reference.java --suite suites/JML/reserveSeats/suite.yaml --json
```

第一条检查 JSON。第二条检查重复点、数据类型和参考规格，并运行变异测试。确认它返回 `"valid": true`，`pre_points` 和 `post_points` 按实际新增数量变化，且这三题的 `effective_score` 为 100、`unexpected_survivors` 为空。第三条用参考文件自评，应得到 `PASS`、100 分、退出码 0。

要复现加点前后的差异，先保留未加入示例的点集。把参考文件复制成一份临时提交：

```sh
cp suites/JML/reserveSeats/reference.java reserveSeats-wrong.java
```

PowerShell 可用 `Copy-Item suites/JML/reserveSeats/reference.java reserveSeats-wrong.java`。只在副本里将成功分支的 `ensures \result && occupied == \old(occupied);` 改成 `ensures \result && occupied == \old(occupied) && count <= 3;`。用同一条命令测两次，第一次用原点集，第二次在保存上面的三个 HW10 点后再测：

```sh
python3 semantic_check.py reserveSeats-wrong.java --suite suites/JML/reserveSeats/suite.yaml --json
```

如果旧点集只覆盖到三座，这份错解在加点前会得到 `PASS`。加入上面的四座成功点后应返回 `FAIL`、退出码 1，并包含 `POSTCONDITION_MISMATCH`。这里要看的是 **同一份错解有没有从通过变成失败**。如果错解两个版本都失败，换一份旧点集确实放过的错解再测，或检查预期失分区域是否新增了失败。测试完可移走临时错解文件。

如果 `validate_suite.py` 提示「参考合同与观察点……自检判定不一致」，先用点的 `id` 找回该对象，按题意确认 `args`、前后态、返回值和标记。若报告已有的等价变异被新点识别或出现未知存活变异，按[等价变异审核步骤](#54-检查变异质量并审核等价项)复核。

准备交付时，运行 `python3 run_tests.py` 并按[发布步骤](#93-构建和检查独立评测包)构建新 ZIP。需要对三周的 159 份模拟提交集中复测时，从完整仓库根目录执行 `python3 -B judge-2027/stress_2027/run.py`。脚本会生成新的结果目录，记录每份提交的预期、实际 JSON 和耗时。
