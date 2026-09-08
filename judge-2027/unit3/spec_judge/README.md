# Unit 3 JML 统一语义评测原型

本目录包含两个工具：

- `semantic_check.py`：当前的统一语义评测入口。它比较学生填写后的 JML 与服务器端完整参考 JML，不调用 LLM，也不执行学生 Java。
- `spec_judge.py`：早期 weak/mid 原型，仅保留用于回归和对比，不是正式评分入口。
- `consistency_judge.py`：双一致性入口，分别检查课程需求–学生 JML 和学生 JML–Java。

## 双一致性检测

课程组先把自然语言需求审核为 `teacher_approved` 的 Requirement IR（示例见
`Agent/exercises/follow_user/requirement_ir.json`）。学生 Java 文件应包含其本人编写的
JML，或由 OpenJML 的规格路径配置关联到该 JML。执行：

```powershell
python consistency_judge.py `
  --requirement-ir "..\..\..\Agent\exercises\follow_user\requirement_ir.json" `
  --student-jml "学生提交\NetworkInterface.java" `
  --student-java "学生提交\Network.java" `
  --openjml "wsl:/home/ranye/.local/openjml-21.0.27/openjml" `
  --openjml-arg=--method=followUser
```

输出始终保留两个独立结果：`nl_jml`、`jml_java`，以及由二者组合得到的
`overall`。若 Requirement IR 未批准、OpenJML 不可用或验证超时，对应链返回
`UNKNOWN`，不会把“没有完成验证”误报成通过或失败。现有 Gold JML 比较器仍可作为
课程组回归检查，但不再充当自然语言需求的唯一参照。

## 统一评测

从本目录运行：

```powershell
python semantic_check.py `
  "学生提交\NetworkInterface.java" `
  --reference "教师资产\follow_user_complete.java" `
  --method followUser `
  --json
```

`--reference` 只能在服务器端或教师环境中提供，不能发给学生。评测器一次覆盖全部已实现的语义义务，不存在 weak/mid/strong 参数。

当前 `followUser` Demo 支持：

- 一个正常行为 `requires`；
- 两个关系后置条件 `ensures`；
- 四个 `signals` 条件及异常优先级；
- `containsUser`、`getUser`、`isFollowing`、`containsFollower`；
- 布尔逻辑、比较和 `\old`；
- 锁定的 `assignable` 与输出子句完整性检查。

结果是确定性 JSON：`score`、`passed` 与 `diagnostics`。每个诊断包含错误代码、空位位置、错误类别、抽象观察和不含答案的改正方向。例如：

```json
{
  "code": "EXCEPTION_PARTITION_MISMATCH",
  "location": "SECOND_USER_MISSING",
  "category": "异常分支与优先级"
}
```

语义结论只在当前有限抽象状态模型内成立。新增题目或新 JML 构造时，必须先扩展语义模型、解析器和回归测试；不要把该原型误称为完整 OpenJML 或任意 JML 等价判定器。

## JML 评测原理

评测器判定的是**学生填写的规格是否在本题定义的抽象状态范围内，与教师参考规格表达相同的行为**；它不运行学生的 Java 实现，也不要求 JML 文本与参考答案逐字一致。

整个过程如下：

1. **先做结构拦截。** Web 服务先检查 Java 接口的锁定框架和占位符。仍有 `{{...}}` 空位时，直接返回“请先填写空位”的确定性反馈，不启动语义评测，也不调用 LLM。
2. **抽取并解析嵌入式 JML。** 对通过结构检查的提交，评测器从目标 Java 方法前的 `/*@ ... @*/` 注释中抽取 `requires`、`ensures`、`signals` 和 `assignable`。受限解析器把允许的 JML 表达式转成内部语法树；不支持的字符、接口外方法、缺少子句或空位都会被报告为 `JML_FORMAT_OR_SYMBOL`。
3. **建立课程定义的抽象状态。** 当前不是自动枚举任意规模的网络，而是为 `followUser` 手工给出有限的区分性场景。每个状态只保留 `users`（已存在用户 id）、`following`（用户关注的 id 集合）和 `followers`（用户的粉丝 id 集合）；参数固定为 `id1`、`id2`。解释规则也固定：`containsUser(id)` 查询 `users`，`getUser(id)` 产生抽象用户引用，`isFollowing` 查询 `following`，`containsFollower` 查询 `followers`，而 `\old(expr)` 改为在前态计算 `expr`。前态共 9 个，覆盖正常关注、第一用户缺失、第二用户缺失、自关注、已关注，以及“用户缺失且 id 相同”等重叠边界。成功后的场景共 4 个：双向关系均正确更新、只更新关注关系、只更新粉丝关系、关系方向颠倒。后三者可以是实际程序不应产生的不一致状态；它们的用途是分别检验两个后置条件，而不是模拟 Java 执行。
4. **逐义务比较真值。** 对每个义务和其适用的全部抽象场景，评测器分别计算教师子句与学生子句；只要存在一个场景使二者真值不同，该义务即失败。`requires` 在 9 个前态上比较；两个 `ensures` 分别在 4 个前后态对上比较；四个 `signals` 分别在 9 个前态上同时比较异常类型和条件。这里的“异常优先级”不是运行 Java 后选择异常，而是要求后一个 `signals` 条件在所有重叠前态上也与教师条件一致：例如第二个“用户不存在”分支若未排除“第一用户不存在”，就会在该前态多匹配一次而失败。`assignable` 与输出子句是锁定内容，不执行表达式，而是与参考文本作完整性比较。
5. **生成可解释结果。** 当前 demo 共 8 个义务：1 个 `requires`、2 个 `ensures`、4 个 `signals` 和 1 组锁定子句。得分是已满足义务的比例；每个未满足义务返回固定的诊断代码、对应空位、错误类别、抽象观察和修复方向。诊断不会给出参考 JML，也不会暴露具体隐藏状态。

因此，学生可以写出与教师文本不同、但在该题受支持语法和已覆盖抽象状态上等价的表达式；反之，常见的“看起来合理但漏掉边界”的规格会在区分类别的状态上产生不同真值而被检出。

这一方法的保证范围必须如实理解：它证明的是“在 `followUser` 明确列出的有限状态集上无差异”，不是对任意规模网络、任意 JML 构造或任意等价变形的数学证明。当前受限解析器实际支持布尔逻辑、比较、已列出的接口调用和 `\old`，**尚不支持**量词、`union`、`singleton` 等构造。`examples/NetworkInterface_correct.java` 与 `examples/NetworkInterface_incomplete.java` 是早期 `spec_judge.py` 原型的回归样例，其中的量词和集合表达式不能作为 `semantic_check.py` 的输入；当前统一评测的参考规格是服务器端的 `Agent/staff/fixtures/follow_user_complete.java`。题目扩展时，应由课程组先补充状态类别与反例，再扩展解析器和测试，而不是把未知语法交给 LLM 猜测。

## LLM 的边界

Web 学习界面会先调用 `semantic_check.py`，再把其结构化诊断连同学生可见的题面交给 LLM。LLM 只负责简短解释并提供不泄题的修复方向；它不决定分数、不能覆盖评测结果，也拿不到参考 JML。

## 回归测试

```powershell
python -m unittest -v
```
