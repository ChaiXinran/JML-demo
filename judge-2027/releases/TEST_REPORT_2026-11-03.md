# 2026-11-03 JML–JML 评测器集中测试记录

本记录是开发机上的源码测试及最终 ZIP 独立解包测试，供当天上机使用。目标评测机尚需按包内 `ON_MACHINE.md` 执行验收；本记录不代替目标机结果。

## 发布产物

- 文件：`jml-judge-2026-11-03.zip`，ZIP 根目录为 `spec_judge/`。
- SHA-256：`01bb965c5faf1172256571a135bc074bcce77d5f0c7e321b11d0731619daf121`。
- 共 55 个文件，其中 `release.json` 记录其余 54 个文件的 SHA-256；独立解包核验未发现哈希不一致。
- 结果协议：`schema_version: 1`，退出码 `0/1/2` 对应 `PASS/FAIL/ERROR`。
- 源码基于 `e163716` 后的本轮工作区修复；所有本轮源码改动在 `judge-2027/`。
- ZIP 与 `.sha256` 是本地构建产物，已被 `.gitignore` 排除。包内有参考答案和隐藏测试点，仅供内部评测机。

## 环境与集中回归

开发机：Darwin 25.6.0 arm64，Python 3.14.7；未安装可选 `z3-solver`。未调用学生 Java、Web、OpenJML 或模型 API。

执行 `PYTHONDONTWRITEBYTECODE=1 python3 run_tests.py`：

| 位置 | 测试总数 | 通过 | 失败/错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| 源码组件目录 | 57 | 54 | 0 | 3 |
| 最终 ZIP 解压后的独立临时目录 | 57 | 54 | 0 | 3 |

跳过项为现有三个可选 SMT 用例。缺失 `required` SMT 后端的错误路径仍已执行，确认返回 `ERROR`/退出码 2 且不带学生成绩。独立目录的回归还会重新构建并解包发布物，逐个 Suite 执行参考自评和质量预检。

## 已修复问题的回归

- 合同移到无关方法前、目标声明重复或重载均被拒绝；源码中的普通方法调用、字符串和普通注释不被当作声明。
- 返回类型、参数类型/名称/顺序、`static`、`throws` 变化均返回格式失败；现有 `safe`、`pure` 声明标记可以正常评测。
- `signals_only`、`invariant`、拼错的条款、尾部垃圾、未完成行为、多个相邻合同块和额外 `//@` 条款均明确拒绝。
- 额外附加 `id1 == 1`、`id2 == 2` 或 `id1 != 0` 的过强正常前置条件，均被 `followUser` 新边界点区分。
- 2000 层否定、深括号、超 token 数、超 AST 深度、超长整数字面量和超 1 MiB 文件/stdin 均返回学生 `FAIL` JSON。
- 1000 项平坦 `&&` 合取仍能正确评测，未因左深语法树溢出而崩溃。
- 超深或超大参考合同返回无分数的 `ERROR`；模拟内部内存/递归异常同样不计为学生失败。
- `.jml` 扩展名、UTF-8 BOM、标准输入、无关工作目录、缺失文件、非法 UTF-8 和错误 CLI 参数均覆盖。

## Suite 自检结果

五个 Suite 均为 `valid: true`、有效变异得分 100、`unexpected_survivors: []`：

| Suite | 前态点 | 前后态点 | 原始变异得分 | 审核等价变异 |
| --- | ---: | ---: | ---: | --- |
| `CounterInterface.checkNonNegative` | 1 | 3 | 100 | 无 |
| `NetworkInterface.canInteract` | 4 | 12 | 100 | 无 |
| `NetworkInterface.containsBoth` | 4 | 16 | 100 | 无 |
| `NetworkInterface.followUser` | 12 | 13 | 96（25/26） | `delete_conjunct.8` |
| `NetworkInterface.unfollowUser` | 2 | 3 | 86（6/7） | `delete_conjunct.2` |

两个审核变异都删除了关注条件中冗余的用户存在判断；当前 `network_v1` 状态加载器已要求关注边两端用户存在，所以在这个抽象域内等价。审核记录绑定确切变异源码 SHA-256；哈希失配、ID 缺失或新点区分了已审核变异都会使预检失败。原始统计保留，最低质量门槛没有降低。

## 最终 ZIP 的独立 CLI 冒烟

| 提交 | 实际状态 | 退出码 | 学生成绩 |
| --- | --- | ---: | --- |
| `followUser/reference.java` 自评 | `PASS` | 0 | 100 |
| `wrong-relation-direction.java` | `FAIL` | 1 | 86 |
| 缺失提交文件 | `ERROR` | 2 | JSON 无 `score`、无 `passed` |

## 目标机待记录

目标机应重新核对 ZIP SHA-256，记录其系统、Python 版本、回归结果、五个 Suite 自检、CLI 正反例与错误退出码，以及评测机外层超时/内存限额。Linux、Windows 或其他 Python 版本的实际兼容性由该步骤确认。

当天可用范围为现有两个 Profile 与五个 Suite 的受限 JML 数据点评测；量词、`\result`、完整 sidecar、任意作业的多方法汇总和完整 JML 等价证明不在本次产物范围内。
