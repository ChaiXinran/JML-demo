# TODO


1. 设计通用评测 Profile。新增题目背景或新增可评测接口语义时，实现或扩充对应 Profile，包括：
   1. 可观察的抽象状态及其合法性约束；
   2. JML 中允许调用的方法，以及这些方法在抽象状态中的语义；
   3. 可区分正常、异常、边界和状态变化错误的前态/后态生成规则；
   4. 可评测的 JML 语法范围，以及新增语法时对通用解析器的扩充；
   5. 每项评测义务的检测规则、诊断位置、错误类别和不泄题的修正方向；
   6. 正确 JML 与每类典型错误 JML 的回归测试。

   Profile 以 Python 代码实现，不以助教手写 JSON/YAML 实现。课程组批准的 Requirement IR 是 NL–JML 检测的行为权威；完整官方 JML 是辅助回归 oracle，用于在发布前发现 Gold JML 与 Requirement IR 的偏差。Profile 只定义有限评测范围内“状态和接口调用如何解释”。普通助教维护完整 JML、`requirement.md`、经审批的 `requirement_ir.json` 和 `blank_plan.json`；Profile 由工具开发者在出现新题目背景、新接口语义或新 JML 构造时实现或扩充。

   建议目录结构：

   ```text
   spec_judge/
     core/                 # 通用 JML 解析、子句映射、真值比较和诊断
     profiles/
       network_v1/
         profile.py        # 网络状态、调用语义、前态/后态生成
         README.md          # Profile 的人工说明和支持边界
         test_profile.py    # 正确/典型错误 JML 的回归测试
   ```

   `profile.py` 的最小职责：

   ```python
   class NetworkV1Profile:
       allowed_calls = {"containsUser", "getUser", "isFollowing", "containsFollower"}

       def evaluate_call(self, name, args, context):
           # 在抽象状态中解释 JML 方法调用。
           ...

       def pre_scenarios(self, method_name):
           # 返回正常、异常、边界和重叠异常的代表性前态。
           ...

       def post_scenarios(self, method_name):
           # 返回正确后态和可区分典型后置条件错误的前后态对。
           ...
   ```

   通用评测器负责从 `blank_plan.json` 定位学生填写的子句，调用 Profile 取得场景并解释 JML 函数，然后比较教师与学生子句在所有场景中的真值；Profile 不记录参考答案，也不决定学生应填写哪一个子句。
