# 第三单元 JML 评测器

本目录由 JML 评测器开发者维护，提供评测机使用的 **JML–JML 一致性评测**。评测依据是评测端审核过的参考 JML、领域 Profile 与测试点，输入是学生提交的 JML 源码。

学生练习 Web 的二进制分发、Java 上传和 JML–Java / OpenJML 验证由协作者维护。学生的 Java 与 JML 可作为独立材料提交；评测机将 JML 文件交给本组件，将 Java 实现交给相应的实现评测链，分别记录结果。

- [评测器能力与命令](unit3/spec_judge/README.md)
- [逐步添加测试点、方法、类和 Profile](unit3/spec_judge/USAGE.md)
- [评测机输入、JSON 输出和发布包协议](unit3/spec_judge/INTEGRATION.md)
- [当前开发计划](unit3/spec_judge/TODO.md)

从仓库根目录做一次参考自评：

```bash
python3 judge-2027/unit3/spec_judge/semantic_check.py \
  judge-2027/unit3/spec_judge/suites/NetworkInterface/followUser/reference.java \
  --suite judge-2027/unit3/spec_judge/suites/NetworkInterface/followUser/suite.yaml \
  --json
```

预期退出码为 `0`，结果包含 `status: "PASS"`、`score: 100`、`passed: true`。正式测试命令为 `python3 judge-2027/unit3/spec_judge/run_tests.py`。

现有 OpenJML 绑定与运行反例历史文件暂留原路径以兼容协作者调用；它们不属于 JML–JML 正式发布包和测试入口。
