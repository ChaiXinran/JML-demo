# 模拟学生提交输入与反馈核验

本轮准备了 12 份完整的 `followUser` 规格提交：2 份正确、10 份错误。每份都可以单独上传到 JML 评测入口，或用批量脚本调用 CLI。

## 配套产物

- 测试输入包：`jml-student-inputs-2026-11-03.zip`。
- 输入包 SHA-256：`1b0998d517b92599f9bff9c1ebdf2c32d031b1f47cf4cbcccf2ce22940cd3dbb`。
- 配套评测器：原 `jml-judge-2026-11-03.zip`，SHA-256 仍是 `01bb965c5faf1172256571a135bc074bcce77d5f0c7e321b11d0731619daf121`，本轮没有改动该评测器 ZIP。
- ZIP 根目录是 `student_submissions/`：`inputs/` 为待提交答案，`expected/` 为配套发布版的实测 JSON 反馈，`cases.json` 记录版本与预期，`check_submissions.py` 逐个模拟提交，`README.md` 提供操作步骤。

## 实测预期

所有案例使用 `suites/NetworkInterface/followUser/suite.yaml`。分数是当前固定点集的评分，不表示错误严重程度的线性排序。

| 案例 | 内容 | 状态 | 分数 | CLI 退出码 |
| --- | --- | --- | ---: | ---: |
| 01 | 正确完整合同 | PASS | 100 | 0 |
| 02 | 正确等价改写，合并后置条件 | PASS | 100 | 0 |
| 03 | 正常条件遗漏自关注检查 | FAIL | 98 | 1 |
| 04 | 反向后置条件弱化为 true | FAIL | 93 | 1 |
| 05 | 两条关系方向写反 | FAIL | 86 | 1 |
| 06 | 用户缺失异常条件重叠 | FAIL | 93 | 1 |
| 07 | 额外要求 id1 等于 1 | FAIL | 79 | 1 |
| 08 | 正常 frame 放宽为任意位置 | FAIL | 96 | 1 |
| 09 | 使用未知查询 hasUser | FAIL | 0 | 1 |
| 10 | 返回类型从 void 改成 int | FAIL | 0 | 1 |
| 11 | 添加未支持的 signals_only | FAIL | 0 | 1 |
| 12 | 合同块属于 unrelated 方法 | FAIL | 0 | 1 |

第 07 份的额外前置限制同时影响 frame 的适用性，实际有 `NORMAL_CONDITION_MISMATCH` 和 `LOCKED_CLAUSE_CHANGED` 两种诊断；预期文件如实记录了它们。完整诊断文案和源码行号见包内 `expected/*.stdout.json`。

## 验证结果

- 使用原发布 ZIP 的独立解压目录逐份执行 CLI：2 份 PASS、10 份 FAIL，所有结果均为有效 JSON，标准错误为空。
- 源码目录的批量脚本核对：12/12 MATCH，脚本退出码 0。
- 独立解压测试输入包后再次核对：12/12 MATCH，脚本退出码 0。
- 重用已存在的结果目录：脚本拒绝覆盖并退出 2。
- 故意将临时评测器副本中正确答案的分数改为 99：批量脚本发现两个正确案例不匹配，退出 1，汇总为 10/12 MATCH；原发布 ZIP 与源评测器未被修改。

批量脚本只对照稳定的评分、诊断、覆盖统计与退出码，允许可选 SMT 后端导致的 `solver` 和保证范围说明变化。它会检查配套评测器 `release.json` 与输入文件的 SHA-256，避免不同材料沿用同一份预期。

## 交给测试人员

将本输入 ZIP 和原评测器 ZIP 解压到同一个新目录，进入 `student_submissions/`，运行：

```bash
python3 check_submissions.py --judge-dir ../spec_judge --output-dir ../submission-results
```

预期末尾显示 `反馈符合预期：12/12`。请回传 `submission-results/report.json` 和 `actual/` 中的 stdout、stderr、退出码文件。若通过真实评测机上传入口测试，只提交 `inputs/` 中的某份答案文件，使用 `cases.json` 与 `expected/` 核对反馈。

这些 `.java` 和 `.jml` 都是 JML 规格提交，不包含学生 Java 实现；应进入 JML–JML 评测入口。测试人员仍需记录目标机或提交入口的实际结果，本地通过不代替该步骤。
