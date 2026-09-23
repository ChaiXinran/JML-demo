# unfollowUser：解除双向关注关系

在两个用户都存在且 `id1` 已关注 `id2` 时执行 `unfollowUser(id1, id2)`。

调用后必须同时满足：

1. `id1` 不再关注 `id2`；
2. `id2` 的粉丝列表不再包含 `id1`。
