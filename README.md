# 2027 JML 填空训练工具使用说明

## 1. 作用与边界

本仓库包含两条相互独立的链路：

```text
课程组完整官方 JML → 挖空后的接口 → 学生补写 JML → JML 规格评测
课程组完整官方 JML → 学生阅读 JML → 学生 Java 实现 → 既有 Java 功能评测
```

`Agent/` 只辅助第一条链路的出题、模板生成和学习反馈；它不运行学生 Java，也不决定 Java 功能分。Java 功能正确性仍由课程既有的 Runner/SPJ 与标准程序对拍决定。

完整 JML 必须写在官方接口的 `.java` 文件中，以 `/*@ ... @*/` 注释出现。完整官方 JML 是唯一行为权威；`blank_plan.json` 等 JSON 是从它导出的设计信息，不能成为第二份“正确规格”。

## 2. 目录与角色

| 位置 | 用途 | 可否发给学生 |
| --- | --- | --- |
| `Agent/` | 教师侧分析、出题辅助、模板生成、学生学习界面 | 部分 |
| `Agent/cases/follow_user/` | 教师侧题面与经批准的挖空计划 | 不直接发放 |
| `Agent/exercises/follow_user/` | 面向学生的题面、模板和公开样例 | 可以 |
| `Agent/staff/` | 参考填写、rubric 等教师资产 | 不可以 |
| `judge-2027/unit3/spec_judge/` | `followUser` 的受限 JML 规格评测原型 | 服务器侧 |
| `U3 GuideBook/` | 2026 单元指导书参考 | 课程组 |

## 3. 运行前准备

以下命令均以 PowerShell 为例。请先在 `JML-demo` 仓库根目录打开 PowerShell；此时当前目录中应能看到 `Agent` 和 `judge-2027`：

```powershell
Get-ChildItem Agent, judge-2027
python --version
```

Agent 使用 Python 标准库，当前不需要安装第三方包。Python 应为 3.10 或更高版本。

教师侧 Agent 命令必须先进入 `Agent`。第 5--11 节的 Agent 命令都以该目录为当前目录：

```powershell
Set-Location "Agent"
# 官方包不随本仓库提交；此检查应输出 True
Test-Path "..\..\officialpackage\hw9"
```

需要调用模型的 `run`、交互式 `exercise` 和 Web 的“反馈”功能使用 DeepSeek Chat Completions：

```powershell
$env:DEEPSEEK_API_KEY = "YOUR_API_KEY"
# 可选；默认即为 deepseek-v4-flash 和 https://api.deepseek.com
$env:DEEPSEEK_MODEL = "deepseek-v4-flash"
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com"
```

不要把密钥写入仓库、题目 JSON、学生包或 Markdown 文档。接口解析、模板生成、离线结构检查和规格评测原型不需要密钥。

## 4. 先准备官方完整 JML

出一道新题的起点不是 JSON，也不是模型提示词，而是课程组确认的官方接口。例如 `NetworkInterface.java` 中，目标方法紧邻前方必须有完整 JML 块：

```java
/*@ public normal_behavior
  @ requires ...;
  @ assignable ...;
  @ ensures ...;
  @ also
  @ public exceptional_behavior
  @ signals (SomeException e) ...;
  @*/
public /*@ safe @*/ void targetMethod(...)
    throws SomeException;
```

写完后应先人工核对自然语言题面、异常优先级、正常/异常状态变化、`assignable`、`\old` 和量词。学生版模板会保留所有锁定内容，只替换经批准的子句条件。

`--source-root` 不是接口目录本身，而是能包含官方包目录的根目录。当前工作区中的 HW9 官方包是课程组提供的仓库外部输入；以 `JML-demo` 根目录为基准，它位于：

```text
..\officialpackage\hw9\
├─ hw9.jar
├─ com.oocourse.spec1.jar
└─ src\com.oocourse.spec1\main\
   ├─ UserInterface.java
   ├─ VideoInterface.java
   └─ NetworkInterface.java
```

因此，进入 `JML-demo\Agent` 后，本说明中的命令统一使用相对路径 `..\..\officialpackage\hw9`。它指向上面所述的官方包；如果你把官方包放在其他位置，只需把命令中的这一段替换为对应的相对路径。工具会在该目录下定位唯一的 `NetworkInterface.java`。不要把 `--source-root` 写成 `src\com.oocourse.spec1\main`，也不要指向 jar 文件。

只克隆本仓库时，`officialpackage` 不会自动出现；请先把课程组提供的官方包放在 `JML-demo` 同级的 `officialpackage\hw9`，或将命令中的相对路径改成你保存官方包的位置。官方包不应因这份使用说明而提交到 GitHub。

> 当前边界：Demo 解析器已经兼容这份 `spec1` 官方接口中无分号结束的 `invariant`，可用于 `list` 和 `inspect`。它仍是轻量 JML 解析器，不是完整 JML 编译器；若未来官方包采用新的 JML 语法，应先补充解析与回归测试。`template` 命令只做文本级挖空，不依赖接口解析器。

## 5. 教师侧：查看和审计官方接口

### 5.1 列出可识别的方法

```powershell
python -m hw9_agent list `
  --source-root "..\..\officialpackage\hw9"
```

输出为 `接口名.方法名: Java 签名`。这一步用于确认 Agent 找到了预期的官方包。

### 5.2 审计一个方法

```powershell
python -m hw9_agent inspect `
  --source-root "..\..\officialpackage\hw9" `
  --method followUser `
  --interface NetworkInterface
```

它会显示 JML 中的 `requires`、`ensures`、`signals` 数量，以及轻量 critic 的发现和测试义务。若只需要机器可读结果：

```powershell
python -m hw9_agent inspect `
  --source-root "..\..\officialpackage\hw9" `
  --method followUser `
  --interface NetworkInterface `
  --json
```

当方法名在多个接口中重复时，必须传入 `--interface`。教师侧挖空流水线要求目标方法已有嵌入式 JML；若没有，命令会报错，提醒先完成课程组合同。

## 6. 教师侧：建立一个案例目录

以 `Agent/cases/follow_user/` 为模板，为每个新方法创建一个案例目录。案例需要以下文件：

| 文件 | 必需 | 内容 |
| --- | --- | --- |
| `requirement.md` | 是 | 面向学生的自然语言需求。 |
| `blank_plan.json` | 是 | 已批准的挖空位置；每项指向完整 JML 中一个既有子句。 |

### 6.1 `blank_plan.json` 的最小结构

```json
{
  "schema_version": 1,
  "method": "NetworkInterface.followUser",
  "status": "teacher_approved",
  "source_authority": "完整官方 NetworkInterface.java 中 followUser 前的 JML 块",
  "student_owned_blanks": [
    {
      "id": "NORMAL_CONDITION",
      "source_jml_selector": {"clause": "requires", "occurrence": 1},
      "replacement_scope": "condition_only",
      "ability": "正常行为条件的合取与异常排除"
    }
  ],
  "locked_elements": ["Java 签名", "行为头", "assignable", "异常类型"]
}
```

选择器中的 `occurrence` 从 1 开始，表示目标 JML 块内同类子句的出现顺序。例如第 2 个 `ensures` 使用 `{"clause":"ensures","occurrence":2}`；`signals` 可额外记录异常类，便于人工审查。当前模板生成器实际依赖 `clause` 和 `occurrence`，因此二者必须准确。

`status` 必须为 `teacher_approved`。这是课程组已确认“挖哪些空”的标记，不是对行为正确性的批准；行为正确性仍来自完整接口 JML。

### 6.2 设计建议

- 每个学生空应训练一个可说明的能力，例如异常优先级、前后状态方向、`\old`、量词或 frame。
- 将方法签名、行为头、异常类、教师希望学生阅读而非填写的 `assignable` 保持锁定。
- 不要让空的前后相邻文本直接泄露完整答案。
- 每种希望识别的错误，都应在语义评测器的回归测试中对应至少一个可区分的抽象状态或历史；否则不能成为有效测试点。
- 最终评分使用一套服务器端的统一语义测试；完整参考 JML、反例状态和评分规则只保留在教师/服务器侧。

## 7. 可选功能：AI 辅助梳理出题设计

这一节不是“自动出题”，也不会自动发布题目、生成最终 JML、生成学生模板或给学生评分。

它只是一个可选的教师工作台：课程组已经写好完整官方 JML、题面和初步挖空计划后，可让模型按五个固定视角输出**供教师审阅的设计草案**。若助教不需要模型协助，可以完全跳过本节，直接使用第 8 节的确定性模板生成命令。

五个视角及其含义：

| 阶段 | 名称 | 主要产物 |
| --- | --- | --- |
| `analyzer` | 合同阅读 | 把完整 JML 的既有子句标为正常条件、后置条件、异常条件、frame 等，发现题面和 JML 的冲突。 |
| `planner` | 挖空审查 | 讨论某个既有子句是否值得挖、训练什么能力、会有哪些典型误写。 |
| `template` | 变换计划审查 | 核查每个占位符是否准确指向完整 JML 中的既有子句。它不生成 JML。 |
| `critic` | 题目质量审查 | 检查空位是否可解、是否泄露答案、是否缺少上下文。 |
| `assessment` | 语义义务清单 | 列出统一语义评分器必须覆盖的义务和对应的反馈类别；它不运行测试也不产生分数。 |

无论是否使用模型，最终必须由教师批准完整 JML、`blank_plan.json` 和学生模板。模型的任何建议都不是题目权威。

### 7.1 连续生成五份设计草案（可选）

`run` 的“全部阶段”仅指按顺序调用模型五次：先得到合同阅读草案，再把它作为后续草案的输入。它不会自动完成出题。输出目录可为一个新目录，避免覆盖已有记录：

```powershell
$env:DEEPSEEK_API_KEY = "你的密钥"

python -m hw9_agent run `
  --source-root "..\..\officialpackage\hw9" `
  --case-dir "cases\follow_user" `
  --method followUser `
  --interface NetworkInterface `
  --output-dir "outputs\follow_user_2027"
```

可通过 `--model`、`--base-url` 覆盖环境变量。运行后，输出目录中包含题面、挖空计划、五份模型输入和五份文本草案。教师应逐份审阅；若无需这些草案，不应运行该命令。

### 7.2 手动取得某一份设计草案的提示词（可选）

可先只生成 Analyzer 的输入，复制到人工选定的模型中：

```powershell
python -m hw9_agent prepare `
  --source-root "..\..\officialpackage\hw9" `
  --case-dir "cases\follow_user" `
  --stage analyzer `
  --method followUser `
  --interface NetworkInterface `
  --output "outputs\manual\01-analyzer-input.md"
```

`planner` 需要同一 `--case-dir` 内已有 `analyzer.yaml`；`template` 还需要 `plan.md`；`critic` 需要 `template_plan.json`；`assessment` 需要 `review.yaml`。因此，手动流程建议如下：

1. 建一个工作目录，例如 `outputs/manual/`，复制 `requirement.md` 和 `blank_plan.json` 到该目录；
2. 用 `--case-dir outputs/manual --stage analyzer` 生成提示词；
3. 将模型结果保存为 `outputs/manual/analyzer.yaml`；
4. 依次组装并保存 `plan.md`、`template_plan.json`、`review.yaml`；
5. 最后组装 `assessment`。

模型输出若试图新增 JML、改变官方合同或引入接口中不存在的符号，应拒绝该建议，而不是修改官方接口来迁就模型。

## 8. 教师侧：从完整 JML 生成学生练习包

助教只需准备完整官方 JML 接口、`requirement.md` 和已经批准的 `blank_plan.json`。以下命令会创建一个**新的**练习目录，并自动写入学生模板、题面、`exercise.json` 和空的 `samples/` 目录：

```powershell
python -m hw9_agent publish-exercise `
  --interface-file "..\..\officialpackage\hw9\src\com.oocourse.spec1\main\NetworkInterface.java" `
  --requirement "cases\follow_user\requirement.md" `
  --blank-plan "cases\follow_user\blank_plan.json" `
  --exercise-dir "exercises\follow_user_new"
```

默认标题为“`<方法名> JML 填空练习`”；若需要自定义学生可见标题，可追加 `--title "..."`。目标目录已经存在时命令会停止，避免覆盖已发布的学生包或其中的演示样例。

自动生成的 `exercise.json` 包含：方法名、占位符顺序、默认提示/讲解配置，以及从嵌入式 JML 提取的公开符号。助教无需手写它。若要提供演示样例，只需将 `.java` 文件放入 `samples/`；页面会自动识别，并以文件名生成展示名称，无需再修改配置。

### 8.1 低层接口模板命令

若只需要一个学生接口文件、而不使用 Web 练习器，可直接运行低层命令：

在完整 JML 和 `blank_plan.json` 都已确认后，使用确定性工具挖空：

```powershell
python -m hw9_agent template `
  --interface-file "..\..\officialpackage\hw9\src\com.oocourse.spec1\main\NetworkInterface.java" `
  --method followUser `
  --blank-plan "cases\follow_user\blank_plan.json" `
  --output "release\NetworkInterface.java"
```

该命令：

- 只定位目标方法紧邻前方的 `/*@ ... @*/` JML 块；
- 按 `student_owned_blanks` 中的子句类型与序号替换条件内容；
- 保留 Java 文件其余内容、JML 行为头、未选子句、`signals (异常 e)` 声明和分号；
- 生成类似 `requires {{NORMAL_CONDITION}};` 的学生空位。

命令失败时，按下表处理：

| 报错/现象 | 原因与处理 |
| --- | --- |
| `blank_plan.json must be teacher_approved` | 先人工审查并将 `status` 改为 `teacher_approved`。 |
| `Cannot find an embedded JML block...` | 检查目标方法前是否有 `/*@ ... @*/`，以及 `--method` 是否拼写正确。 |
| `No ensures clause #2...` | `occurrence` 与完整 JML 的实际同类子句顺序不一致。 |
| 模板出现不应挖空的片段 | 停止发布，核对 `clause`、`occurrence` 和完整官方接口。 |

生成后应人工 diff 完整接口和学生模板：除已批准的占位符区域外，二者必须完全一致。使用 `publish-exercise` 时，不需要再复制模板或维护 `exercise.json` 的占位符列表。

## 9. 学生侧：离线结构检查

无需 API 密钥，可检查学生提交是否仍有空、是否改动锁定框架：

```powershell
python -m hw9_agent exercise `
  --exercise-dir "exercises\follow_user" `
  --submission "exercises\follow_user\samples\incomplete.java" `
  --offline
```

返回的典型代码：

| 代码 | 含义 |
| --- | --- |
| `UNFILLED_BLANKS` | 至少一个 `{{PLACEHOLDER}}` 未填写。 |
| `FRAMEWORK_CHANGED` | Java 签名、锁定 JML 框架或非填写区被修改。 |
| `EMPTY` | 提交内容为空。 |
| `STRUCTURE_OK` | 空位已填写且锁定框架未变；不代表语义正确。 |

离线结构检查不是正式规格评分，不能替代 JML 解释器或隐藏测试。

## 10. 学生侧：命令行学习反馈

### 10.1 一次性提交

```powershell
$env:DEEPSEEK_API_KEY = "你的密钥"

python -m hw9_agent exercise `
  --exercise-dir "exercises\follow_user" `
  --submission "student\NetworkInterface.java" `
  --mode hint
```

`--mode hint` 使用提示模式：只给一个最高优先级错误类别和一条直接的修复方向。改为 `--mode review` 可使用讲解模式：可指出空位位置、错误类别、抽象反例形状和修复方向，但仍不应给出替换子句或完整参考 JML。两种模式都不改变确定性规格评测的结果。

### 10.2 交互式提交

```powershell
python -m hw9_agent exercise `
  --exercise-dir "exercises\follow_user" `
  --mode hint
```

启动后可用命令：

| 命令 | 行为 |
| --- | --- |
| `/template` | 再次显示学生模板。 |
| `/requirement` | 再次显示自然语言题面。 |
| `/mode hint` | 切换到提示模式。 |
| `/mode review` | 切换到讲解模式。 |
| `/submit` | 结束当前输入缓冲，将此前粘贴的完整 Java 接口提交。 |
| `/quit` | 退出。 |

应先粘贴完整的、已填写的 `.java` 接口文本，再单独输入一行 `/submit`。模型仅收到公开题面、学生模板、允许符号、公开反馈契约、结构检查结果与学生提交；不应向模型发送 `Agent/staff/` 中的参考答案或 rubric。

## 11. 学生侧：Web 界面

启动本地服务：

```powershell
$env:DEEPSEEK_API_KEY = "你的密钥"

python -m hw9_agent web `
  --exercise-dir "exercises\follow_user" `
  --host 127.0.0.1 `
  --port 8000
```

浏览器打开 <http://127.0.0.1:8000>，以 `Ctrl+C` 停止服务。

页面功能包括：题面显示、逐空填写、模板预览、公开错误样例、hint/review 切换、多轮提交记录、重置。服务端接口为：

| HTTP 方法与路径 | 用途 | 是否调用模型 |
| --- | --- | --- |
| `GET /health` | 健康检查 | 否 |
| `GET /api/exercise` | 获取公开题面、模板、样例与反馈契约 | 否 |
| `POST /api/check` | 运行离线结构检查 | 否 |
| `POST /api/review` | 返回结构检查加模型学习反馈 | 是 |

没有密钥时，页面与 `GET /api/exercise`、`POST /api/check` 仍可用；请求 `POST /api/review` 会返回服务不可用错误。不要把服务绑定到公网地址，除非另行完成认证、限流与密钥隔离。

## 12. JML 统一语义评测（仅 followUser Demo）

当前正式 Demo 入口为 `semantic_check.py`：一次运行全部已实现的语义义务，不存在 weak/mid/strong 参数。它不调用 LLM、不执行学生 Java；服务器以完整参考 JML 为参照，返回分数和结构化诊断。旧 `spec_judge.py` 的 weak/mid/all 仅保留为开发回归原型，不能用于课程评分。

从 `JML-demo` 根目录运行（如果刚执行完第 11 节，先用 `Set-Location ..` 返回根目录）：

```powershell
python judge-2027/unit3/spec_judge/semantic_check.py `
  "提交\NetworkInterface.java" `
  --reference "Agent\staff\fixtures\follow_user_complete.java" `
  --method followUser `
  --json
```

参数说明：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `java_source` | 无 | 含 JML 注释的学生 `.java` 接口文件。 |
| `--reference` | 无 | 服务器端完整参考 JML；正式部署时不向学生公开。 |
| `--method` | `followUser` | 被提取和评测的方法名。 |
| `--json` | 关闭 | 输出供平台和 LLM 教学层使用的结构化诊断。 |

当前 Demo 支持 `followUser` 的一个 `requires`、两个关系 `ensures`、四个 `signals` 条件、布尔逻辑、比较、`\old` 及有限的用户关系模型。它不执行 Java、不支持任意 Java 调用，也不是完整 OpenJML。

内部可以按义务组织检查，但学生只得到一次结果和精确的错误类别，不能选择或获知测试分组、状态快照、完整参考 JML 或变异集。Web 端会先调用该评测器，再将诊断交给 LLM 解释；LLM 不参与判分。

## 13. 测试与发布前检查

### 13.1 Agent 回归测试

```powershell
Push-Location "Agent"
python -m unittest discover -s tests -v
node --check web\app.js
Pop-Location
```

### 13.2 规格评测原型回归测试

```powershell
Push-Location "judge-2027\unit3\spec_judge"
python -m unittest -v
Pop-Location
```

### 13.3 题目发布检查清单

- [ ] 完整官方接口 JML 已由课程组确认，且写在 `.java` 注释中。
- [ ] 自然语言题面与完整 JML 没有未决冲突。
- [ ] `blank_plan.json` 的每个选择器都能定位到一个既有 JML 子句。
- [ ] 已用 `publish-exercise` 命令重新生成学生练习包，并人工核对锁定区未变化。
- [ ] 自动生成的 `exercise.json` 中的占位符顺序与模板一致。
- [ ] 每种希望识别的错误都有可区分的状态/历史和对应评测器回归测试。
- [ ] 统一语义评测的反馈不泄露参考子句、状态快照或隐藏变异。
- [ ] 完整参考填写、语义检查规则和 rubric 只在教师/服务器侧保存。
- [ ] Agent 和规格评测原型的测试均通过。

## 14. 常见问题

**为什么不让模型直接根据 JSON 生成 JML？** 这会把 JSON 变成另一份不透明的行为权威，也无法保证与课程组官方接口一致。正确顺序是课程组先写完整 JML，模型只辅助分析和选择挖空。

**学生 Java 是否由 Agent 判分？** 不会。JML 规格分和 Java 功能分独立；后者继续使用课程已有的标准程序对拍。

**学生提交 `.jml` 文件可以吗？** 不可以。课程形式与工具均要求 JML 写在学生提供的 `.java` 接口注释中。

**`STRUCTURE_OK` 是否意味着通过？** 不意味着。它只说明占位符和锁定框架形式正确，之后仍需要语义评测。

**能否把 `--suite all` 当正式规格分？** 不能。它只是当前原型的开发选项。正式系统应只有一次统一的服务器端语义评测。
