# HW9 Specification Agent

这是一个面向 OO Unit 3 HW9 的最小规格分析智能体。它读取官方 Java 接口中的
JML，把方法规格拆成结构化信息，再执行一致性检查并生成测试义务。

确定性代码负责接口 grounding、解析和基础检查；五阶段草案流程可使用 DeepSeek API。
密钥只从环境变量读取，不写入仓库。

仓库还提供 5 个教师侧阶段 Prompt、1 个学生反馈 Prompt 与 HW9 专用 Skill。可以人工逐阶段调用模型，也可以先
用 `prepare` 命令组装包含真实接口上下文的完整输入。

## 快速开始

```powershell
cd Agent
python -m hw9_agent inspect `
  --source-root "D:\01_OO\Learn\Unit3\_code\u3_hw9" `
  --method queryMutualFollowingSum
```

查看全部方法：

```powershell
python -m hw9_agent list --source-root "D:\01_OO\Learn\Unit3\_code\u3_hw9"
```

输出 JSON：

```powershell
python -m hw9_agent inspect --source-root "...\u3_hw9" --method followUser --json
```

当方法名在多个接口中重复时，可追加 `--interface UserInterface`。

组装 `followUser` Analyzer 输入：

```powershell
python -m hw9_agent prepare `
  --source-root "D:\01_OO\Learn\Unit3\_code\u3_hw9" `
  --case-dir "cases\follow_user" `
  --stage analyzer `
  --method followUser `
  --output "outputs\follow_user\01-analyzer-input.md"
```

将阶段改为 `planner`、`template`、`critic`、`assessment` 即可生成后续输入。组装器会读取案例目录
中的上游产物，并在缺失时立即报错。

## DeepSeek 自动运行

在当前 PowerShell 会话设置密钥：

```powershell
$env:DEEPSEEK_API_KEY = "你的密钥"
```

执行完整五阶段：

```powershell
python -m hw9_agent run `
  --source-root "D:\01_OO\Learn\Unit3\_code\u3_hw9" `
  --case-dir "cases\follow_user" `
  --method followUser `
  --output-dir "outputs\deepseek-follow-user"
```

默认使用 `deepseek-chat` 和 `https://api.deepseek.com`。可以通过 `--model`、`--base-url`
或 `DEEPSEEK_MODEL`、`DEEPSEEK_BASE_URL` 覆盖。每阶段的完整输入和模型输出都会保存，
便于复现实验和统计人工修改量。

在课程组完成完整接口 JML、学生题面和 `blank_plan.json` 后，优先使用本地确定性工具生成完整练习目录：

```powershell
python -m hw9_agent publish-exercise `
  --interface-file "官方包\com\oocourse\spec3\main\NetworkInterface.java" `
  --requirement "cases\follow_user\requirement.md" `
  --blank-plan "cases\follow_user\blank_plan.json" `
  --exercise-dir "exercises\follow_user_new"
```

该命令确定性生成 `template.java`、`requirement.md`、`exercise.json` 和空的 `samples/` 目录。
`exercise.json` 的方法名、占位符、默认反馈配置和公开符号均由输入自动派生；助教无需填写它。若已有通过验证的 JML 一致性 Suite，可在发布命令末尾追加 `--semantic-suite "../judge-2027/unit3/spec_judge/suites/NetworkInterface/followUser/suite.yaml"`，命令会校验方法名并自动把 Web 所需的 `semantic_suite` 路径写进 `exercise.json`。若需公开演示样例，只需把 `.java` 文件放入 `samples/`，页面会按文件名自动识别。`--title` 仅在需要自定义学生可见标题时使用。新方法完整步骤见 [USAGE.md](../judge-2027/unit3/spec_judge/USAGE.md#9-把新方法接入-web-ui从-suite-到学生页面)。

低层的 `template` 命令仍可在只需要一个学生接口文件时使用：

```powershell
python -m hw9_agent template `
  --interface-file "官方包\com\oocourse\spec3\main\NetworkInterface.java" `
  --method followUser `
  --blank-plan "cases\follow_user\blank_plan.json" `
  --output "release\NetworkInterface.java"
```

该命令只替换 `blank_plan.json` 明确定位的既有 JML 子句内容；它不会让模型重写合同。

## 学生 JML 填空审查

离线检查示例提交是否填完、框架是否被破坏：

```powershell
python -m hw9_agent exercise `
  --exercise-dir "exercises\follow_user" `
  --submission "exercises\follow_user\samples\incomplete.java" `
  --offline
```

启动 DeepSeek 多轮学习对话：

```powershell
python -m hw9_agent exercise `
  --exercise-dir "exercises\follow_user" `
  --mode hint
```

进入后粘贴包含 `/*@ ... @*/` 注释的完整 Java 接口，以 `/submit` 提交。支持
`/template`、`/requirement`、`/mode hint|review` 和 `/quit`。`hint` 只指出一个优先问题；
`review` 可指出涉及的填空位置和抽象反例形状，但两者均不提供完整答案，也不改变判定结果。

## NL–JML–Java 双一致性检测

教师演示无需拼接路径或准备提交文件。在仓库根目录运行：

```powershell
python demo.py
```

浏览器会打开内置的三个案例：全部正确、规格方向错误但代码满足该错误规格、规格正确但
Java 漏更新反向关系。点击“运行双检测”即可展示两个 Judge 和综合结论，不需要配置
DeepSeek API Key。

课程组审核 `requirement_ir.json` 后，可同时检查“学生 JML 是否表达题意”和“学生 Java
是否满足其本人 JML”：

```powershell
python -m hw9_agent consistency `
  --requirement-ir "exercises\follow_user\requirement_ir.json" `
  --student-jml "学生提交\NetworkInterface.java" `
  --student-java "学生提交\Network.java" `
  --openjml "wsl:/home/ranye/.local/openjml-21.0.27/openjml" `
  --openjml-arg=--method=followUser
```

结果分别位于 `nl_jml` 和 `jml_java`，不会因为 Java 满足一份错误或过弱的学生规格
而给出整体通过。OpenJML 不可用、超时或需求 IR 未批准时返回 `UNKNOWN`。

`--openjml` 接受原生 Windows 可执行文件，也接受 `wsl:/absolute/linux/path`
形式的 WSL 安装。Agent 会自动把学生 Java 的 Windows 路径转换为
`/mnt/<drive>/...`。

教师 rubric 位于 `staff/rubrics/`，正确填写样例也只保留在 `staff/`。学生练习服务不会
读取、返回或发送这些资产；正式评分必须由独立的确定性规格验证器产生。

## Web 学习界面

```powershell
# 可选：需要模型学习建议时设置 DEEPSEEK_API_KEY

python -m hw9_agent web `
  --exercise-dir "exercises\follow_user" `
  --port 8000
```

浏览器访问 `http://127.0.0.1:8000`。页面提供逐空填写、完整 Java 接口预览、确定性规格评测、
提示/讲解模式、多轮提交记录和一键重置。模型只接收公开题面、模板、允许符号、公开反馈契约、
学生提交和已判定的诊断；服务器端参考规格与 rubric 不会发送给浏览器或模型。
从仓库根目录开始的 Windows/macOS/Linux 启动方式和密钥行为，详见[根 README 第 11 节](../README.md#11-学生侧web-界面)。当前页面“提交审查”在无密钥时直接显示确定性评分；有密钥时才追加模型学习建议。`POST /api/check` 仍可供程序单独调用。

## 教师侧规格审计

1. `InterfaceLoader`：定位 `*Interface.java`。
2. `JmlParser`：抽取 model、invariant、requires、assignable、ensures、signals 和方法标记。
3. `SpecificationCritic`：检查 pure/frame、异常条件、正常行为与规格完整性。
4. `TestObligationGenerator`：生成正常、异常、边界和 side-effect 测试义务。

## 教师侧出题辅助流水线

1. `Analyzer`：核对题面与完整官方 JML，标注既有子句的职责和候选挖空。
2. `Planner`：选择应挖空的既有 JML 片段、保留的上下文、训练能力和常见误写。
3. `Template`：只输出“占位符 → 官方 JML 子句”的确定性变换计划，不生成 JML。
4. `Critic`：检查挖空是否可解、是否泄露答案、是否覆盖能力且可以评测。
5. `Assessment Designer`：基于完整 JML、追踪表、错误目录和统一语义评测规则设计规格义务与诊断。

完整嵌入式 JML 始终是唯一的行为权威。每个教师案例须提供已批准的
`blank_plan.json`；它只记录从完整 JML 导出的挖空位置。详细说明见仓库根目录的 [`report.md`](../report.md)。

Web 练习的 `exercise.json` 还应指定 `semantic_suite`，路径相对于 `Agent/`；新建练习时用 `publish-exercise --semantic-suite` 自动配置，已有练习包则可手动添加该字段并重启 Web。Web 只把学生提交交给该 suite，不读取或返回参考 JML 与隐藏测试点。suite 的编写和验证见 [`spec_judge/README.md`](../judge-2027/unit3/spec_judge/README.md)。

## Demo 资产

- `skills/`：JML、HW9 领域、规格模式和 critic 清单。
- `prompts/`：Analyzer、Planner、Template、Critic、Assessment Designer。
- `cases/follow_user/`：题面与经教师批准的挖空计划。
- `outputs/`：由 `prepare` 生成的可投喂模型输入，不保存模型密钥。

## 已知边界

- 这是面向课程 JML Level 0 风格的轻量解析器，不是完整 JML 编译器。
- 当前一致性评测器已支持多个方法、多个类和可扩展 Profile，但仍只解释文档列出的 JML 子集，不是完整 JML 编译器。
- Java 功能正确性仍应由现有 Runner/SPJ 或其后续扩展判断；Agent 不决定正式分数。
