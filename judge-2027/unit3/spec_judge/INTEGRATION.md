# 评测机集成协议（结果格式 v1）

本组件评测参考 JML 与学生 JML 在 Suite 声明范围内的一致性。课程的学生练习 Web 独立分发；评测机可直接调用这里的 CLI，无需启动 Web、安装 Java、配置 OpenJML 或模型 API。

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

输入为 UTF-8 文本，允许 UTF-8 BOM。文件可以扩展名为 `.jml`，也可以是带 JML 注释的 `.java`。两者采用相同的受限源码格式：包含目标方法声明，且合同使用紧邻该声明的 `/*@ ... @*/` 块。例如一个支持的标量方法：

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

结果 v1 保留原 CLI 的字段与退出码，并增加 `schema_version` 和 `status`。调用方应允许未来的可选字段，先检查协议版本、退出码和状态，再读取学生成绩。

## 3. 生成独立发布包

在组件目录执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 run_tests.py
PYTHONDONTWRITEBYTECODE=1 python3 build_release.py --output /tmp/jml-judge-v1.zip
```

输出路径必须是新文件；构建器不会覆盖旧发布包。ZIP 根目录为 `spec_judge/`，包括 CLI、解析/求值核心、Profile、所有 Suite、参考合同、测试样例、维护工具和文档。历史 Web/OpenJML 代码、IDE 文件和缓存不进入包；构建器拒绝指向包外的 Suite 参考和 Points 路径。

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

## 4. 测试集变更

新增方法或测试点只修改对应 Suite/Profile。完成 `validate_suite.py`、正确和错误提交验证、正式回归后重新生成发布包。评测机管理员将新包部署到新的版本目录，记录 ZIP 哈希，并为后续提交选择其中的 Suite。

已产生的成绩不会自动重算；是否重新评测历史提交由课程评测流程决定。参考合同和隐藏 Points 保留在评测端，不随学生练习工具的二进制分发。
