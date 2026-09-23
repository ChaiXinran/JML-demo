# 可上传案例库

这里集中放置组会演示和本地测试需要的案例。文件都是普通文本源码，可以直接在 Web 页面中选择上传。

`manifest.json` 是案例的版本化清单，记录题目、方法、Suite、故意缺陷和每条检查链的预期结果。新增或修改案例时应同步更新清单并运行回归测试。

## 目录说明

| 目录 | 内容 | 页面操作 |
|---|---|---|
| `NL/` | 自然语言需求 | 讲解需求，不上传 |
| `JML/` | 可导入的 JML/Java 合同源码 | JML 规格 → 导入文件 |
| `Java/` | 可上传的单文件 Java 实现 | Java 实现 → 上传 Java 文件 |
| `complete/` | 成套案例；每个目录都同时包含 `NL.md`、`JML.java`、`Java.java` | 按同一目录配对上传 |

## 推荐演示顺序

### followUser

1. 打开 `follow_user` 练习。
2. 使用 `complete/follow_user/A_correct/JML.java` 和 `Java.java`，预期规格与实现均通过。
3. 保持同一份 `JML.java`，改上传 `complete/follow_user/C_wrong_code/Java.java`，预期规格通过、Java 静态验证失败。
4. 使用 `complete/follow_user/B_wrong_spec/`，展示自然语言需求与错误方向规格之间的差异。

### unfollowUser

1. 打开 `unfollow_user` 练习。
2. 使用 `complete/unfollow_user/A_correct/`，预期运行检查通过。
3. 使用 `complete/unfollow_user/C_wrong_code/`，预期能够定位为只更新了一侧关系。

## 文件约定

- `JML.java` 是包含 `NetworkInterface` 方法合同的源码，虽然扩展名是 `.java`，可以直接放入“导入 JML / Java 源文件”。
- `Java.java` 是不带 `package` 的单文件实现，适合直接上传。
- 同一成套目录中的 `JML.java` 与 `Java.java` 参数名和方法名已经配套，不要跨目录混用。
- 案例 C 的 Java 文件故意保留缺陷，用于展示 OpenJML 如何指出实现不满足规格。
