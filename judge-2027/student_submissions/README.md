# 外部测试人员使用说明

本包提供 12 份 `followUser` 模拟提交，用于检查课程评测机能否按当前发布版返回预期反馈。测试人员在隔离目录中解压本包和现有评测器包后，既可批量对照预期结果，也可逐个把输入文件交给 CLI 或评测机入口。

## 1. 使用的文件包

需要两份 ZIP：

- `jml-judge-2026-11-03.zip`：现有评测器发布包，解压后包含 `spec_judge/`，使用其中的 `NetworkInterface.followUser` Suite。
- `jml-student-inputs-2026-11-03.zip`：本模拟提交包，解压后得到 `student_submissions/`，其中有 `inputs/`、`cases.json`、`expected/` 和批量脚本 `check_submissions.py`。

模拟提交包内包含正确样例和实测公开反馈的参考文件，只供外部评测人员内部验证。**不要将这 12 个输入或 `cases.json`、`expected/` 发给正式学生。** 新包是独立的测试素材，不会替换或改写原评测器 ZIP。

## 2. 解压后运行全部样例

把两个 ZIP 解压到同一个新目录，使 `spec_judge/` 与 `student_submissions/` 成为并列目录。以下 macOS/Linux 示例从临时目录运行，不依赖仓库路径：

```bash
WORK_DIR="$(mktemp -d /tmp/jml-external-check.XXXXXX)"
unzip -q /path/to/jml-judge-2026-11-03.zip -d "$WORK_DIR"
unzip -q /path/to/jml-student-inputs-2026-11-03.zip -d "$WORK_DIR"
cd "$WORK_DIR/student_submissions"
python3 --version
python3 check_submissions.py --judge-dir ../spec_judge --output-dir ../submission-results
```

评测器要求 Python 3.10 或更新版本。`--output-dir` 必须指定一个尚不存在的新目录；如该目录已存在，请另选目录名。脚本逐个显示案例、预期结果、是否匹配，并将汇总保存为 `report.json`；每个案例的实际 JSON 标准输出、标准错误和退出码也保存在结果目录中。

将结果目录中的 `report.json` 和各案例的实际输出一并回传给组织者。若某案例未匹配，不要改写提交或预期文件；保留完整结果以便排查。`cases.json` 记录每个案例的预期和基准信息；`expected/*.stdout.json` 是使用当前发布版实测后保存的公开反馈参考。详细分数、诊断内容及具体预期以这些文件为准，本说明不预设分数。

`solver` 字段可能因运行环境是否安装可选 Z3 而不同；批量比较不要求该字段的原始 JSON 完全相同。其他匹配行为由随包的案例定义和 runner 决定。

脚本会核对配套评测器的 `release.json` 哈希，以及每份输入的 SHA-256。固定样例被修改后，批量预期就不再有效；如要探索修改后的答案，请另存一份并按下节单次运行。第 07 份虽然只增加了参数限制，但该限制也改变了 frame 的适用性，因此当前基线会同时报告正常条件与锁定条款问题。

## 3. 单独运行一份提交

从解压后的 `student_submissions/` 目录运行。正确样例：

```bash
python3 ../spec_judge/semantic_check.py inputs/01_correct.jml \
  --suite ../spec_judge/suites/NetworkInterface/followUser/suite.yaml \
  --json
```

`01_correct.jml` 预期是正确合同，CLI 应返回 `PASS`，退出码为 `0`。正确的等价改写 `02_equivalent.java` 也可用同一命令运行，只需替换提交路径。

错误样例：

```bash
python3 ../spec_judge/semantic_check.py inputs/05_wrong_direction.java \
  --suite ../spec_judge/suites/NetworkInterface/followUser/suite.yaml \
  --json
```

`05_wrong_direction.java` 预期返回 `FAIL`，退出码为 `1`。也可把单个 `.jml` 或 `.java` 输入文件复制/上传到评测机的提交入口，以模拟实际提交；只选择要评测的输入文件，**不要提交 `cases.json`、`expected/` 或 runner 输出目录**。提交文件的详细预期反馈仍以 `expected/` 和 `cases.json` 为准。

## 4. 十二个模拟提交

所有提交都使用发布包中的 `NetworkInterface.followUser` Suite。文件名中的类别用于定位测试目的；具体分数与诊断以案例数据为准。

其中 `.java` 文件也只是包含 JML 合同的规格提交，未提供 Java 方法实现。上传到真实评测机时应选择 JML 评测入口；本套输入不用于测试 Java 功能评分。

| 输入文件（在 `inputs/` 下） | 用途 | 预期状态 | 分数 | 退出码 |
| --- | --- | --- | ---: | ---: |
| `01_correct.jml` | 完整正确合同 | PASS | 100 | 0 |
| `02_equivalent.java` | 等价改写：条件调序、ensures 合并 | PASS | 100 | 0 |
| `03_missing_self_check.jml` | 遗漏自关注检查 | FAIL | 98 | 1 |
| `04_weak_inverse_post.jml` | 反向后置条件写成 true | FAIL | 93 | 1 |
| `05_wrong_direction.java` | 关注与粉丝方向写反 | FAIL | 86 | 1 |
| `06_overlapping_exceptions.jml` | 异常条件重叠 | FAIL | 93 | 1 |
| `07_constant_id_restriction.jml` | 附加 id1 == 1 限制 | FAIL | 79 | 1 |
| `08_wrong_frame.jml` | assignable 放宽为 \\everything | FAIL | 96 | 1 |
| `09_unknown_query.jml` | 不存在的查询 hasUser | FAIL | 0 | 1 |
| `10_wrong_signature.jml` | 返回类型从 void 改成 int | FAIL | 0 | 1 |
| `11_unsupported_clause.jml` | 尚未支持的 signals_only | FAIL | 0 | 1 |
| `12_detached_contract.jml` | 合同属于 unrelated 方法 | FAIL | 0 | 1 |

## 5. 怎样判断结果

单次 CLI 调用将一个 JSON 对象写到标准输出。`score` 和 `diagnostics` 是面向学生的评测反馈；标准错误用于评测端管理员排查配置、文件和执行问题，不应直接展示给学生。

| CLI 退出码 | 状态 | 含义 |
| --- | --- | --- |
| `0` | `PASS` | 提交在当前 Suite 范围内与参考合同一致 |
| `1` | `FAIL` | 学生提交不符合要求，结果中包含学生成绩 |
| `2` | `ERROR` | 参数、输入读取或评测配置错误；没有学生成绩 |

批量脚本退出码 `0` 表示**所有案例的实际反馈都符合案例预期**。其中十个错误样例通常应得到学生级 `FAIL`，所以 runner 整体成功不表示所有输入都通过评测。若批量脚本报告不匹配，应结合 `report.json` 和该案例实际 stdout、stderr、退出码排查；不要把评测端 `ERROR` 当作学生零分。
