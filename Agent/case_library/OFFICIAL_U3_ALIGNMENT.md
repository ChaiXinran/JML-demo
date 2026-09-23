# U3 HW9 官方定义对齐说明

本案例库以课程官方包中的 `NetworkInterface` 与 `UserInterface` 为语义来源，当前对齐范围为 `followUser` 与 `unfollowUser`。

## 已确认的官方定义

- `users`、`following`、`followers` 是课程 JML 中的抽象模型字段。
- `containsUser`、`getUser`、`isFollowing`、`containsFollower` 是无副作用查询。
- `followUser` 正常执行时同时建立正向关注与反向粉丝关系。
- `unfollowUser` 正常执行时同时删除正向关注与反向粉丝关系。
- `followUser` 包含用户不存在、自关注、重复关注异常分支。
- `unfollowUser` 包含用户不存在、关注关系不存在异常分支；当前学生练习的语义 Suite 仍只评测正常行为，未宣称异常分支已覆盖。
- `(* output-> ... *)` 是课程输出约定，当前不把它解释成 OpenJML RAC 已验证控制台文本。

## OpenJML 执行适配

官方合同中的 `assignable users[*]` 描述课程抽象模型内用户状态的变化；标准 OpenJML 对具体 Java 数组的同名表达只允许修改数组元素引用。静态与运行适配器因此在临时绑定产物中进行显式、可记录的映射：

- `users[*]` 映射为本次操作涉及的 `following` 与 `followers` 单元；
- 抽象查询映射为执行适配器中的可观察数组状态；
- 同一 `exceptional_behavior` 下的课程条件式 `signals` 被拆分为标准 JML 的互斥行为分支。

原始提交 JML、数据点评测和下载材料不会被改写。所有适配记录在验证结果的 `binding.contract_adaptations` 中，避免把适配后的合同冒充学生原始合同。

## 当前真实基线

- `followUser / A_correct`：ESC `PASS`。
- `followUser / C_wrong_code`：ESC `FAIL`，定位到遗漏的反向粉丝后置条件。
- `unfollowUser / A_correct`：ESC `PASS`。
- `unfollowUser / C_wrong_code`：ESC `FAIL`，定位到遗漏的反向粉丝后置条件。

动态反例搜索仍按各题运行适配器的实际能力单独报告；静态通过不等于已经完成运行复现。
