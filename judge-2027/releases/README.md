# 内部评测机发布产物

`jml-judge-2026-11-03.zip` 是本轮上机候选包，根目录为 `spec_judge/`。ZIP 包含参考 JML 和隐藏测试点，仅供课程评测机内部使用。

ZIP、校验和及临时解包目录已由本目录 `.gitignore` 排除。源代码、测试和使用说明仍在 `../unit3/spec_judge/` 维护。重新构建时使用新的输出路径，构建器不会覆盖既有产物。

上机步骤见 [ON_MACHINE.md](../unit3/spec_judge/ON_MACHINE.md)，本地集中验证记录见 [TEST_REPORT_2026-11-03.md](TEST_REPORT_2026-11-03.md)。目标机的 Python、系统、命令退出码和实际测试结果仍需按操作页记录。

另有独立的 `jml-student-inputs-2026-11-03.zip`，内含两份正确、十份错误的模拟学生答案、实测预期反馈和批量提交脚本。它与原评测器 ZIP 配套使用，原评测器包与校验和保持不变。使用方法见 [模拟提交说明](../student_submissions/README.md)，核验记录见 [模拟提交测试报告](STUDENT_INPUTS_TEST_REPORT_2026-11-03.md)。
