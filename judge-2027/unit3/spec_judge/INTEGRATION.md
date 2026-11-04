# 评测机集成协议（结果格式 v1）

本组件评测参考 JML 与学生 JML 在 Suite 声明范围内的一致性。课程的学生练习 Web 独立分发；评测机可直接调用这里的 CLI，无需启动 Web、安装 Java、配置 OpenJML 或模型 API。

本次上机候选版本正式支持五个现有 Suite 和两个 Profile（`network_v1`、`counter_v1`）。当前不增加 JML 语法或任意领域支持；有限测试点结果不能解释为完整 JML 或无限状态空间的证明。

## 1. 提交材料与调用

评测机为一次提交选择一个可信的 Suite。学生提交的 Java 实现由实现评测链处理，本组件读取其 JML 提交文件：

```bash
python3 /opt/jml-judge/spec_judge/semantic_check.py \
  /work/submission/NetworkInterface.jml \
  --suite /opt/jml-judge/spec_judge/suites/NetworkInterface/followUser/suite.yaml \
  --json
```

以上是部署路径示例；路径由评测机填写。输入路径相对于调用方当前目录，Suite 中的 `reference` 和 `points` 相对于 Suite 所在目录。脚本也支持绝对路径，与进程当前目录无关。

### 源码格式

输入为 UTF-8 文本，允许 UTF-8 BOM。文件可以扩展名为 `.jml`，也可以是带 JML 注释的 `.java`。两者采用相同的受限源码格式：包含目标方法声明，且合同使用归属于该声明的唯一完整 `/*@ ... @*/` 块。合同块与方法声明之间允许夹有普通注释；合同块内部的普通注释不保证支持。例如一个支持的标量方法：

```java
public interface CounterInterface {
    /*@ public normal_behavior
      @ requires true;
      @ assignable \nothing;
      @ ensures getValue() >= 0;
      @*/
    public void checkNonNegative();
}
```

方法名、参数名和受支持的查询由所选 Suite/Profile 决定。只有一段脱离方法声明的 JML 子句不能直接提交；`.jml` 扩展名也不代表本组件支持完整 OpenJML sidecar 语法。输入需要的类型与查询含义由 Profile 解释，不进行 Java 编译。

提交中必须存在且只存在一个 Suite 目标方法声明，不能通过重载/重复声明让评测器猜目标。参数名称和 Java 类型须匹配 Suite；返回类型、是否 `static` 和 `throws` 集合须与参考声明相符。JML 合同必须是归属于目标方法的单个完整 `/*@ ... @*/` 块；合同块与声明之间可以有普通注释，块内普通注释不保证支持。`safe`／`pure` 声明标记允许存在。多个相邻合同块、未完成行为、`signals_only`、`invariant`、`model` 等未知条款会被拒绝。源码识别只覆盖本组件需要的受限格式，不是完整 Java 解析器。学生提交中的此类问题返回 `FAIL`，评测端参考合同中的此类问题返回 `ERROR`。

学生源码上限为 1 MiB；每条表达式最多 4096 个 token；语法嵌套最多 32 层；表达式 AST 深度最多 128；整数文字最多 4096 位。触发这些上限的学生提交属于 `FAIL`，退出码为 `1` 且返回成绩 JSON。评测端的参考源触发上限或解析异常属于 `ERROR`，退出码为 `2`，JSON 不含 `score`、`passed`；服务器诊断细节只写入标准错误。

评测机已持有源码文本时，可以使用标准输入：

```bash
python3 /opt/jml-judge/spec_judge/semantic_check.py - \
  --suite /opt/jml-judge/spec_judge/suites/NetworkInterface/followUser/suite.yaml \
  --json < /work/submission/NetworkInterface.jml
```

当前一次调用只评一个 Suite。对多个方法分别调用后，课程评测机按其评分规则汇总。本组件暂未定义 ZIP 提交布局或 Java/JML 文件配对规则。

## 2. 输出与退出码

带 `--json` 时，正常结果和已处理错误均在标准输出产生一条 JSON 对象，结尾换行。标准错误供评测机维护者排错，不能直接作为学生反馈。

| 退出码 | `status` | 解释 | 学生分数 |
| --- | --- | --- | --- |
| `0` | `PASS` | 在当前评测范围内一致 | 有 `score`，一般为 100 |
| `1` | `FAIL` | 学生语法、符号、编码或语义不符合要求 | 有 `score`，格式错误为 0 |
| `2` | `ERROR` | 调用参数、文件读取、参考合同、Suite 或 Profile 配置错误 | 无 `score`、无 `passed` |

学生失败和评测未完成必须分别处理。超时、进程启动失败、异常终止或无法解析 JSON 时，由评测机记录执行错误并按其流程重试或报警，不能据此给学生记零分。

### 完成评测的结果

```json
{
  "schema_version": 1,
  "status": "PASS",
  "score": 100,
  "passed": true,
  "diagnostics": [],
  "coverage": {"applicability": {"passed_weight": 9, "total_weight": 9}},
  "evaluation": {
    "profile": "network_v1",
    "suite": "NetworkInterface.followUser",
    "suite_version": 1,
    "guarantee_scope": "fixed_test_points"
  }
}
```

这是字段示例，不是完整覆盖统计。`schema_version` 是本 JSON 结果协议的版本；`evaluation.suite_version` 是 Suite schema 版本，不能当作测试集内容版本。部署时使用发布包哈希标识实际评测资产。

`diagnostics` 的每项含 `code`、`location`、`category`、`observation`、`guidance`，可有 `lines`（提交源码中从 1 开始的行号）。`coverage`、`evaluation`、`solver` 依评测阶段可缺省；调用方不能强行要求格式失败也包含完整覆盖统计。`score` 与 `passed` 由评测器决定，调用方不根据展示文案重新推导。

`evaluation.guarantee_scope` 给出结论范围；有限测试点通过不能当作所有状态上的证明。SMT `audit` 只报告求解结果，评分仍由点集决定；`required` 的后端错误或无法得出结论使评测失败为 `ERROR`。JSON 不包含参考源码、隐藏状态、逐点数据或求解器模型。

### 评测未完成

```json
{
  "schema_version": 1,
  "status": "ERROR",
  "diagnostics": [{
    "code": "JUDGE_CONFIGURATION",
    "location": "JUDGE",
    "category": "评测未完成",
    "observation": "服务器端 Suite、Profile 或参考合同不可用。",
    "guidance": "请由评测机维护者检查标准错误中的详细信息，再重新评测。"
  }]
}
```

该结构保留机器错误类别，原始路径和配置细节仅写入标准错误。缺失学生文件是 `SUBMISSION_UNAVAILABLE`，调用参数错误是 `JUDGE_ARGUMENTS`。这两者表示评测机尚未取得可评测材料或未正确调用。

显式的提交字节数、表达式 token/嵌套/AST/整数长度超限属于学生格式限制，返回 `FAIL`；未预期的内部内存或递归异常返回 `JUDGE_RESOURCE_ERROR` / `ERROR`，不会生成学生分数。若操作系统直接终止进程，评测机调用方应按执行错误处理。

结果 v1 保留原 CLI 的字段与退出码，并增加 `schema_version` 和 `status`。调用方应允许未来的可选字段，先检查协议版本、退出码和状态，再读取学生成绩。

## 3. 生成独立发布包

在组件目录执行；发布器拒绝覆盖已有归档，因此每次先使用新的输出目录：

```bash
release_dir="$(mktemp -d /tmp/jml-judge.XXXXXX)"
PYTHONDONTWRITEBYTECODE=1 python3 run_tests.py
PYTHONDONTWRITEBYTECODE=1 python3 build_release.py --output "$release_dir/jml-judge-v1.zip"
```

将构建结果 JSON 中的 `output` 和 `sha256` 记录下来。ZIP 根目录为 `spec_judge/`，包括 CLI、解析/求值核心、Profile、所有 Suite、参考合同、测试样例、维护工具和文档。历史 Web/OpenJML 代码、IDE 文件和缓存不进入包；构建器拒绝指向包外的 Suite 参考和 Points 路径。

`release.json` 列出包内文件的 SHA-256 和结果格式版本，构建输出另给整个 ZIP 的 SHA-256。它们供评测机记录使用的评测版本；同一份源文件以相同 Python/zlib 工具链构建时，固定 ZIP 时间戳可避免文件时间造成不同产物。

解压后在 `spec_judge/` 执行 `python3 run_tests.py`，再运行参考自评与一个错误样例，便可确认部署：

```bash
python3 validate_suite.py suites/NetworkInterface/followUser/suite.yaml
python3 semantic_check.py suites/NetworkInterface/followUser/reference.java \
  --suite suites/NetworkInterface/followUser/suite.yaml --json
python3 semantic_check.py tests/fixtures/followUser/wrong-relation-direction.java \
  --suite suites/NetworkInterface/followUser/suite.yaml --json
```

分别预期配置有效、退出码 `0`、退出码 `1`。错误样例的非零退出码属于正常验证结果。

固定点模式只需 Python 3.10+ 标准库。启用 SMT 的评测机应安装 `requirements-smt.txt`；`required` 必须具备该依赖，`audit` 在缺失时报告 `UNAVAILABLE`。正式使用前按作业规模设置外层进程超时和资源预算。

2026-11-03 上机候选包的操作清单见 [ON_MACHINE.md](ON_MACHINE.md)。该清单是待执行流程；只有在目标上机机完成并记录结果后，才可报告实机验收。

## 4. 测试集变更

新增方法或测试点只修改对应 Suite/Profile。完成 `validate_suite.py`、正确和错误提交验证、正式回归后重新生成发布包。Suite 的变异质量预检保留原始变异统计，并按 `quality.equivalent_mutations` 中的精确源码 UTF-8 SHA-256 标记人工审核的等价变异；源码哈希漂移、变异 ID 缺失或新测试点杀死已豁免变异时应停止发布并重新审核。最低变异分数按去除已审核等价项后的 `effective_score` 检查，不能通过放宽状态域凑分。评测机管理员将新包部署到新的版本目录，记录 ZIP 哈希，并为后续提交选择其中的 Suite。

已产生的成绩不会自动重算；是否重新评测历史提交由课程评测流程决定。参考合同和隐藏 Points 保留在评测端，不随学生练习工具的二进制分发。
