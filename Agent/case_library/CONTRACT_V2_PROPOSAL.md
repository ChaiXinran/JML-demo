# HW9 可执行合同 v2 决策稿

状态：**待课程组确认，尚未替换现有 v1 评分合同。**

目标是在不改变题意的前提下，建立一份可以由 OpenJML ESC/RAC 解释的版本化合同。现有 `network_v1`、旧 Suite 和学生材料继续保留；确认后新增 v2，不静默覆盖旧资产。

## followUser

### 1. 正常行为

保持现有适用条件：两个用户存在、ID 不同、正向关注关系尚不存在。

保持两个后置状态：

- `id1` 的 `following` 包含 `id2`；
- `id2` 的 `followers` 包含 `id1`。

### 2. 异常行为

v1 在一个 `exceptional_behavior` 中放置四条带条件的 `signals`，课程 Profile 把这些条件当作分支选择器；标准 JML 的 `signals` 含义不同，不能直接把它当作顺序 `if/else`。

v2 建议拆成四个明确行为：

1. `requires !containsUser(id1)`，只允许 `UserIdNotFoundException`；
2. `requires containsUser(id1) && !containsUser(id2)`，只允许 `UserIdNotFoundException`；
3. `requires containsUser(id1) && containsUser(id2) && id1 == id2`，只允许 `SelfSubscriptionException`；
4. `requires containsUser(id1) && containsUser(id2) && id1 != id2 && getUser(id1).isFollowing(getUser(id2))`，只允许 `DuplicateSubscriptionException`。

每个异常行为使用 `assignable \nothing`。实现层继续按上述优先级检查；重叠输入以行为适用条件而不是源码执行顺序解释。

### 3. Frame

v1 的 `assignable users[*]` 只直接描述用户数组槽位，不能自然表达修改用户内部关系数组。

v2 建议正常行为改为与当前数组式实现一致的精确位置：

```java
assignable getUser(id1).following[id2],
           getUser(id2).followers[id1];
```

如果课程接口不公开这些表示字段，则需要引入经过验证的 model field / represents 关系；在此之前，不把前后快照比较宣传为完整 frame 验证。

### 4. 输出约定

`ensures (* output-> "follow_user succeeded" *)` 继续保留在 v1 文本评分中，避免改变现有分数；v2 能力清单明确标为“运行时未检查”。只有增加真实输出捕获和断言后，页面才能声称验证了输出。

## unfollowUser

题意仍只覆盖正常调用，不新增用户缺失等异常要求。

适用条件保持：两个用户存在，且 `id1` 已关注 `id2`。后置状态保持双向删除。

v2 建议将 frame 精确到：

```java
assignable getUser(id1).following[id2],
           getUser(id2).followers[id1];
```

不满足前置条件的交互输入显示为 `NOT_APPLICABLE`，不能计作通过或实现错误。

## 确认后实施项

1. 新增版本化 v2 参考合同、Suite 和能力清单；v1 原文件不覆盖。
2. 用本机 OpenJML 对两个正确实现和两个漏更新实现建立 ESC/RAC 基线。
3. 共享网络执行适配器支持 follow/unfollow，并记录正常返回、预期异常、错误异常和 RAC 违反。
4. 正式提交、反例重跑和输入编辑都记录实际使用的合同版本。

## 需要确认的决定

- 是否采用“四个独立异常行为”表达 followUser 的异常分支；
- 是否允许 v2 合同直接引用数组式实现的 `following` / `followers` 字段；
- 输出文本本轮是否仅保留评分、不进入运行验证。
