# 2026-11-03 上机操作（候选版本）

本页给今天上机使用的 JML–JML 评测器候选包列出检查步骤。它不是实机验收报告：只有在目标机实际执行并记录结果后，才可标记验收完成。正式范围是现有五个 Suite、两个 Profile（`network_v1`、`counter_v1`）；固定点结果不代表完整 JML 或无限状态空间的证明。

## 1. 准备发布包与 Python

从仓库根目录开始，使用主代理构建的内部发布 ZIP `judge-2027/releases/jml-judge-2026-11-03.zip`。请保留原发布 ZIP，并把解压内容放在一个新建的临时目录中。

该 ZIP 含参考答案和隐藏 Points，只能放在评测机内部使用；不要部署到学生 Web 或公开静态文件目录。

macOS/Linux：

```bash
PACKAGE="judge-2027/releases/jml-judge-2026-11-03.zip"
shasum -a 256 "$PACKAGE"
work_dir="$(mktemp -d /tmp/jml-machine.XXXXXX)"
unzip -q "$PACKAGE" -d "$work_dir"
cd "$work_dir/spec_judge"
python3 --version
cat release.json
```

确认 Python 为 3.10 或更新版本。固定点模式只使用 Python 标准库，不需要安装依赖、Java 或 OpenJML。保存构建输出中的 ZIP `sha256`，并与上机机对 `$PACKAGE` 计算出的 SHA-256 对照；包内的 `release.json` 记录文件清单哈希和结果格式版本。

PowerShell：

```powershell
$Package = "judge-2027\releases\jml-judge-2026-11-03.zip"
Get-FileHash -Algorithm SHA256 -LiteralPath $Package
$WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) ("jml-machine-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $WorkDir | Out-Null
Expand-Archive -LiteralPath $Package -DestinationPath $WorkDir
Set-Location (Join-Path $WorkDir "spec_judge")
python --version
Get-Content release.json
```

确认 `python` 是 Python 3.10 或更新版本。将构建输出的 ZIP SHA-256 与 `Get-FileHash` 的结果核对，并保存包内 `release.json`。

## 2. 标准库冒烟与正式回归

在解压出的 `spec_judge/` 目录执行正式回归：

```bash
python3 run_tests.py
```

本地回归共 57 项，未安装 Z3 时为 54 项通过、3 项跳过。上机仍需记录实际输出；若已安装 Z3，可选用例的执行/跳过数量会变化。固定点测试不需要 Z3。

再自检当前正式支持的五个 Suite：

```bash
for suite in suites/NetworkInterface/*/suite.yaml suites/CounterInterface/*/suite.yaml; do
  python3 validate_suite.py "$suite" || exit $?
done
```

通过条件是五个 Suite 都返回 `valid: true`。当前候选包对应的预期前态/后态数如下；如果目标机输出不同，先停止并核对 ZIP 与 `release.json`：

| Suite | 前态点 | 后态点 |
| --- | ---: | ---: |
| `NetworkInterface.followUser` | 12 | 13（12 个生成） |
| `NetworkInterface.containsBoth` | 4 | 16 |
| `NetworkInterface.canInteract` | 4 | 12 |
| `NetworkInterface.unfollowUser` | 2 | 3 |
| `CounterInterface.checkNonNegative` | 1 | 3 |

变异质量字段也应显示无未预期存活项、`effective_score: 100`。`followUser` 的原始统计是 25/26（96%），人工审核等价项为 `delete_conjunct.8`；`unfollowUser` 是 6/7（86%），审核项为 `delete_conjunct.2`。两项豁免均绑定 suite 配置中记录的精确 UTF-8 源码 SHA-256，最低有效分仍为 100。原始计数低于 100% 是合法结果；不要改点集或状态域来提高它。

PowerShell 可用：

```powershell
Get-ChildItem -Path suites -Recurse -Filter suite.yaml | ForEach-Object {
    python validate_suite.py $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "Suite validation failed: $($_.FullName)" }
}
```

当前发布范围应只有 `network_v1` 和 `counter_v1` 两个 Profile。若发现额外 Suite/Profile，暂停部署并让维护者检查归档内容。

## 3. CLI 正例、反例与评测错误

以下检查均使用 `followUser` Suite。参考合同自评应返回 `schema_version: 1`、`status: "PASS"`，以及 `score: 100`、`passed: true`；退出码为 `0`：

```bash
python3 semantic_check.py \
  suites/NetworkInterface/followUser/reference.java \
  --suite suites/NetworkInterface/followUser/suite.yaml --json
```

故意错误的学生回归样例应返回 `status: "FAIL"`，退出码为 `1`：

```bash
python3 semantic_check.py \
  tests/fixtures/followUser/wrong-relation-direction.java \
  --suite suites/NetworkInterface/followUser/suite.yaml --json
```

将提交通过标准输入传入也应可用。`.jml` 文件采用与 `.java` 相同的受限源码格式，必须带目标方法声明以及归属于该方法的 `/*@ ... @*/` 合同块；合同块与声明之间可以夹普通注释，单独的 JML 子句 sidecar 不符合 CLI 输入约定：

```bash
python3 semantic_check.py - \
  --suite suites/NetworkInterface/followUser/suite.yaml \
  --json < /路径/到/包含目标方法声明的学生提交.jml
```

缺失学生文件用于确认服务器/输入错误不会变成学生分数。预期 JSON 为 `status: "ERROR"`，不含 `score`、`passed`，退出码为 `2`，详细信息写入标准错误：

```bash
python3 semantic_check.py /不存在的目录/not-submitted.java \
  --suite suites/NetworkInterface/followUser/suite.yaml --json
```

目标方法声明必须唯一；目标名、参数名称和 Java 类型与 Suite 相符，返回类型、`static` 状态和 `throws` 集合与参考声明相同。目标方法须归属唯一完整的 JML 块；普通注释可以夹在合同块和方法声明之间，块内普通注释不保证支持。`safe`／`pure` 标记可留存；多个相邻合同块、未完成行为及 `signals_only`、`invariant`、`model` 等未知条款应被拒绝。源码识别只覆盖本组件需要的受限格式，不是完整 Java 解析器。学生提交的这些错误应为 `FAIL`/退出码 `1`，参考源的这些错误应为 `ERROR`/退出码 `2` 且不含分数。

提交源码超过 1 MiB、表达式超过 4096 tokens、语法嵌套超过 32 层、AST 深度超过 128 或整数文字超过 4096 位时，也应确认学生输入得到 `FAIL`/退出码 `1`；同一类问题出现在评测端参考源时应得到 `ERROR`/退出码 `2`，且没有学生分数。资源边界回归应由 `run_tests.py` 覆盖；上机记录实际回归结果，不以手工造超大输入代替正式回归。

未预期的内部内存或递归异常应返回 `JUDGE_RESOURCE_ERROR` / `ERROR`、退出码 `2` 且无分数；操作系统终止进程的情况由外层评测机作为执行错误处理。

## 4. 可选 SMT 检查和评测机资源限制

检查本机是否已有 Z3：

```bash
python3 -c 'import importlib.util; print("z3 available:", importlib.util.find_spec("z3") is not None)'
```

只有本机已安装 Z3 时才额外检查 SMT `audit` 路径，并记录 `solver` 字段的实际输出。若未安装，记录为“可选 SMT 跳过”；不要为今天的固定点评测临时安装依赖，也不要因此阻断上机。固定点评分仍由 Suite 测试点决定。

评测机外层应为每个 CLI 子进程配置 wall-clock timeout 与内存上限，并记录实际配置。限额需结合目标机资源和批量提交规模确定；CLI 超时、被系统终止或无法解析结果 JSON 时，调用方应记为评测执行错误，不能给学生记零分。

## 5. 上机记录

保存以下信息，供主代理更新本目录 `TODO.md` 和发布记录：

| 项目 | 实际记录 |
| --- | --- |
| 上机日期 | 2026-11-03 |
| 发布 ZIP 路径 | `judge-2027/releases/jml-judge-2026-11-03.zip` |
| 发布 ZIP SHA-256 | 与构建输出核对后的值 |
| `release.json` 中结果格式版本 | 实际值 |
| Python 版本 | 实际值，须为 3.10+ |
| `python3 run_tests.py` | 实际通过／失败／跳过数量 |
| Suite 自检 | 五个 Suite 的实际结果 |
| 参考自评 | `PASS`、退出码 0 或实际偏差 |
| 错误提交样例 | `FAIL`、退出码 1 或实际偏差 |
| 缺失输入 | `ERROR`、退出码 2、无分数或实际偏差 |
| 可选 Z3 | 已安装并检查，或因未安装而跳过 |
| 评测机 timeout / 内存限额 | 实际配置值 |

未填写以上实际结果前，本包只能称为“2026-11-03 上机候选版本”；不得描述为已实机验收，也不得据此声称支持全部 JML。
