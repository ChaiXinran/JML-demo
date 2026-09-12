# 通用 JML 一致性评测改造计划

当前状态：固定测试点的 JML–JML 一致性评测、可复用 Profile、多个方法/类的 suite、Web 服务端接入及[手把手加点说明](judge-2027/unit3/spec_judge/USAGE.md)均已具备。**本计划尚未全部完成**：随机生成与不可满足点检查仍未实现；更省事的新 suite 创建流程只是待确认的优化建议。当前正式入口和能力边界见[评测器 README](judge-2027/unit3/spec_judge/README.md)。

## 0. 目标与不可变约束

- [x] 只评测参考 JML 与学生 JML 的语义一致性；JML–Java 验证继续交给 OpenJML。
- [x] 完整参考 JML 是测试 oracle。领域配置和测试点只描述解释环境与抽象状态，不重复正确合同。
- [x] 不要求文本、子句顺序或表达式写法相同；最终比较归一化后的合同行为。
- [x] 结论必须注明保证范围：固定测试点、有限域穷举或求解器支持的逻辑范围。
- [x] 按单人维护设计：同一领域新增方法主要增加参考 JML、suite 和 points 文件，不复制评测核心。
- [x] 保持 `semantic_check.py` CLI、Web JSON 和 `followUser` 诊断兼容。

## 1. 目标目录

```text
spec_judge/
  core/                       # 领域无关的解析、模型、suite 和 judge
  profiles/network_v1/        # 网络状态及调用语义
  suites/NetworkInterface/<method>/  # 每个方法的 suite.yaml、points.yaml 等
  semantic_judge.py            # 兼容导出层
  semantic_check.py            # 稳定 CLI
```

配置文件扩展名采用 `.yaml`，当前加载器实际只接受标准库可读的 JSON 语法 YAML 子集。复杂语义保留统一 Python 扩展口，不为每个方法复制评测器。

## 2. 分阶段实施

### 阶段 A：冻结基线并抽取 Profile 边界

- [x] 记录基线：Agent 22 项通过；spec judge 在 macOS 上除 WSL 路径用例外通过。
- [x] 新增领域无关的 `EvaluationContext`、`Scenario` 和 `EvaluationProfile` 协议。
- [x] 将网络状态、引用、允许调用、调用解释和场景移入 `profiles/network_v1/`。
- [x] `semantic_judge.py` 通过 Profile 求值和获取场景，不再访问网络字段。
- [x] 保持现有统一语义测试的结果、分数和诊断完全一致。

验收：核心求值器不出现 `users`、`following`、`followers` 等领域字段。

### 阶段 B：抽取通用表达式与合同解析

- [x] 将 AST、表达式解析和通用布尔/比较/`\old` 求值移入 `core/expressions.py`。
- [x] 将 JML 块、子句和合同抽取移入 `core/contracts.py`。
- [x] 用 Profile 符号表检查调用、参数和返回类型。
- [x] 将固定子句数量等 `followUser` 限制从解析器移到 suite。
- [x] 增加多 `ensures`、不同异常数和不同方法名测试。

验收：解析器不包含 `followUser` 或网络专有判断；不支持语法不会被误判为语义错误。

### 阶段 C：Suite 与通用事实测试点

- [x] 定义 suite schema：支持 profile、参考、方法、参数、形状、权重、诊断、手写 points 和有限域展开。
- [x] 定义通用状态信封（fixture、`use`、`copy`）并将具体字段/补丁交给 Profile；已验证标量 `set` 和网络关系 `add/remove`，集合或映射无需改 core。
- [x] 测试点只含参数、前态和可选后态；期望由参考 JML 求值。
- [x] 支持 fixture、继承、去重、标签、权重及 public/hidden。
- [x] 给 `semantic_check.py` 增加 `--suite`，保留旧参数。

验收：`followUser` 场景从 suite 加载；新增测试点不修改 Python。

### 阶段 D：合同语义归一化

- [x] 归一化正常适用性、异常结果、正常转换关系及受支持 store-ref 子集的 frame 约束；自定义输出指令仍为锁定文本。
- [x] 正确处理 `also`、多个行为、合并/拆分后的 `ensures`，消除通过判定的位置依赖。
- [x] 在 Observation 上比较整体行为，而不是按文本序号配对。
- [x] 按 applicability、exception、postcondition、frame 等区域和测试点加权。
- [x] 保留学生源码行，并由 suite 可选配置练习空位/义务标签和诊断文案。

验收：合并、拆分或交换等价子句不扣分；过强、过弱和异常重叠仍可区分。

### 阶段 E：自动生成和测试集质量

- [x] 从 suite 声明的有限参数域和状态列表确定性展开笛卡尔积；状态合法性由 Profile 校验。
- [x] 由 Profile 的确定性规则生成正常后态、遗漏正/反向更新、反向关系、无关修改和错误删除等候选；参考 JML 负责接受/拒绝分类。
- [x] 支持手写点、确定性 `exhaustive` 与 Profile 驱动的 `mutations`，均可重复验证。
- [ ] 若确有需要，再增加随机生成、显式种子与可冻结生成点；当前尚未实现，且不是固定点评测的前置条件。
- [x] 增加确定性参考 JML 变异器：结构化删除顶层合取条件、交换简单参数、翻转比较/布尔/逻辑连接、删除 `!`/`\old`、放宽 frame。
- [x] `validate_suite.py` 已检查配置、参考合同自检、数量/权重、生成后态的参考分类、存活变异、变异得分和最低质量门槛。
- [ ] 区分真正漏测与等价变异；当前 `unfollowUser` 的 `delete_conjunct.2` 在 `network_v1` 合法状态内等价，原始变异识别率为 6/7，不能直接解释成测试点缺口。
- [ ] 增加无法实现/不合法观察点的专项检查；目前只对已实现的状态 schema、参数类型、重复观察等做校验，不能把预检通过当作领域语义完整性的证明。

验收：能重复识别已覆盖的典型错误；存活变异须先人工确认是否等价，不能单凭百分比判断测试集质量。

### 阶段 F：扩展性验证

- [x] 用 `containsBoth` 验证已有网络词汇的新方法只需参考 JML 和 suite。
- [x] 用 `canInteract/isBlocked` 验证新状态关系只扩展 domain/profile，不改 judge。
- [x] 用 `CounterInterface.checkNonNegative` 验证不同类、无参数方法和独立 Profile。
- [x] `NetworkInterface.unfollowUser` 作为第五个 Suite 已通过独立预检，并接入 Web 练习包。
- [x] 早期扩展示例包含正确、过强、过弱和非法符号回归；参数边界可识别额外的 `id1 != id2` 限制。
- [ ] 把 `unfollowUser` 的正确/错误样例和预检纳入自动回归；当前“全部 Suite”测试仍只枚举早期四个。

验收：核心 judge 已对五个 Suite 通用，新增同领域方法不复制求值或计分代码；第五个 Suite 的自动回归仍待补齐。

### 阶段 G：可选 SMT 后端

- [x] 定义 AST 到求解器的隔离后端，Z3 类型不进入 core AST 或 Profile 状态。
- [x] 对 applicability/postcondition/exceptions 求解 `LegalState && (Reference XOR Student)`；Profile 用领域无关的 JML 表达式声明合法状态公理。
- [x] 区分 `SAT`、`UNSAT`、`UNKNOWN`、`UNAVAILABLE`；维护者可将内部模型转换为候选 point，普通评测 JSON 不暴露模型。
- [x] 保留无 SMT 依赖的固定点/有限枚举模式，并区分只报告的 `audit` 与强制判定的 `required`。

验收：支持子集内可主动找反例；超时或不支持不会误报通过。

### 阶段 H：接入、文档和清理

- [x] Web 按练习配置选择 suite，不再硬编码 `followUser` 参考文件。
- [x] `publish-exercise --semantic-suite` 自动校验方法名并绑定新练习的 Web Suite；`USAGE.md` 补全从新方法到 Web 页面的操作步骤。
- [x] 现有 Suite 按 `suites/<类名>/<方法名>/` 分目录存放，并同步更新测试、文档和 Web 路径。
- [x] Web 的“提交审查”在未配置 DeepSeek 密钥时直接返回并显示确定性评分；有密钥时继续生成模型学习建议。
- [x] 更新根 README、Agent README、spec judge README 和 `report.md`。
- [x] 增加 `spec_judge/USAGE.md`，逐步说明加点、新方法/新类、Profile、验证、Web 接入和排错；根 README 提供入口。
- [x] 前端和 LLM 只接收学生提交及脱敏诊断，不接收参考 JML、隐藏点或求解器模型。
- [x] 标记旧 `spec_judge.py` 为 legacy；确认仅旧回归测试导入，暂不移除。
- [x] 补充 `.gitignore` 并统一无缓存测试命令。
- [ ] 从 Git 索引移除仍被跟踪的 `__pycache__`／`.pyc`；`.gitignore` 不会自动取消既有跟踪，清理前需确认工作区状态。

## 3. 每阶段共同质量门槛

- [x] 现有兼容测试不得回退。
- [x] 新功能至少有正确、过强、过弱和非法输入测试。
- [x] 配置错误（CLI 退出 2）、学生语法/符号错误和语义不一致使用不同类别。
- [x] 当前手写点、有限域展开和变异检测均确定且可复现；未来随机模式必须记录种子并可冻结。
- [x] “通过”结果携带 profile、suite 版本和保证范围。

## 4. 后续简化建议（待确认，尚未实现）

- [ ] 为单人维护增加 `new_suite` 脚手架：选择现有 Profile、类名、方法名和参数后生成参考 Java 占位、suite 与空 Points 骨架；生成后仍须人工审核参考 JML 和测试情形。
- [ ] 让维护者模式的 `validate_suite.py` 输出逐点的参考判定摘要和覆盖提示，帮助发现“所有后态都被接受/拒绝”等弱测试集；不得把摘要暴露给学生。
- [ ] 面向全班上线前明确部署与安全方案：HTTPS、身份认证、限流、服务器端密钥/参考资产隔离，以及是否保存正式提交/成绩；当前 `127.0.0.1` 启动仅供本机试用，不能直接公网发放。
- [ ] 决定学生页面是否移除旧“双一致性案例工作台”或将其 OpenJML 路径配置化；当前该演示绑定特定 WSL 路径，不属于 JML–JML 正式评分。
- [ ] 如果一个站点需要多道题，设计练习选择与服务端路由；当前一个 Web 进程只加载一个 `--exercise-dir`。

以上优化不应改变“完整参考 JML 是唯一 oracle、Points 不保存答案、学生看不到隐藏点”的边界。是否实施及优先级由下一轮确认。
