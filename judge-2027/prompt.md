
# 任务：扩展 judge-2027，支持 2027 OO 第三单元“自然语言写 JML”三道题

## 0. 你的角色与目标

你是负责 judge-2027 脚本开发的 Agent。目标：在现有 JML–JML 一致性评测器上，增加课程背景的表达式子集、测试点 schema、course_v1 Profile 和三道题的 suite，使课程组能对学生的 JML 书写题做确定性评分。

不要改课程仓库的指导书/官方包；只改 judge 仓库。需要 JML.java 模板时，放在 judge 的 examples/ 下供课程组复制，不要直接写进课程仓库。

## 1. 先读什么

- judge 仓库：README.md、USAGE.md、INTEGRATION.md、TODO.md。
- core/expressions.py、contracts.py、profile.py、suite.py、judge.py、mutations.py。
- semantic_judge.py、semantic_check.py、validate_suite.py、build_release.py。
- profiles/network_v1/profile.py、profiles/counter_v1/profile.py、profiles/registry.py。
- suites/NetworkInterface/followUser/{suite.yaml,points.yaml,reference.java}，以及 containsBoth/canInteract；CounterInterface/checkNonNegative。
- 课程官方包（只读）：2027_OfficialPackage/hw9|hw10|hw11 的 SemesterInterface.java/Values.java/Transcript.java；revised_guidebooks/2027_u3_hw9|hw10|hw11_guidebook.md。

先跑现有测试和 validate_suite，确认基线，再动手。

## 2. 已确定的评测模型（不要改）

- 官方 JML 是 oracle，学生 JML 与 reference.java 在 suite 的每个测试点上比较；学生评分按 applicability/postcondition/exceptions/locked 四个区域加权。学生评分不是变异体。
- 出题预检用 core/mutations.py 变异官方 JML，validate_suite.py 的 quality.min_mutation_score 要求点集把变异判出来；这是点集区分力的门槛，不是学生分数。
- points.yaml 的 mode: "mutations" 生成错误后态/错误结果，作为负测试点；官方 JML 拒绝它们，写弱了的学生会接受，比较时暴露。
- 官方 JML 写最强、最严格且正确；不要为了让学生样例通过而弱化 reference；等价写法靠 points/contract_shape 公平处理，不靠放宽 reference。
- 学生可以省略 signals_only；现有解析器已经忽略它，保持。学生不写 //@；只写一个 /*@ ... @*/ 块；一个方法。

## 3. 三道题（内容已定；题面自然语言由课程组放进指导书，你只做 reference/points/suite/模板）

### 3.1 hw9：countEligibleStudents

方法：public int countEligibleStudents(int courseId)

自然语言：给定一门已存在的课程，统计当前学期中满足以下条件的学生人数：该课程的所有先修课（包括通过先修关系间接到达的课程）都出现在该学生的已修课程中；若该课程没有先修课，则所有学生都满足。方法只读。

Reference JML（示意，名字按官方包调整）：

```java
/*@ public normal_behavior
  @ requires containsCourse(courseId);
  @ assignable \nothing;
  @ ensures \result == (\num_of int sid; containsStudent(sid);
  @     (\forall int pid; containsCourse(pid) && isPrerequisiteOf(pid, courseId);
  @         hasCompleted(sid, pid)));
  @*/
public /*@ pure @*/ int countEligibleStudents(int courseId);
```

Fixture（字段名以官方 hw9 为准）：

- 课程 A(1) 无先修；B(2) 先修 A；C(3) 先修 B；D(4) 先修 A、B。
- 学生 s1 完成 A,B；s2 完成 B；s3 完成 A；s4 完成 A,B,C；s5 选了 A,B 但未完成；s6 什么都没完成；s7 完成 A,B。
- C 的正确结果 3（s1,s4,s7）。

测试点/错误写法（必须覆盖；每行至少一个点）：

| 错误写法                             | 测试点                     | 正确 vs 错误       |
| ------------------------------------ | -------------------------- | ------------------ |
| 只看直接先修                         | C，s2 只完成 B             | 3 vs 4             |
| `\exists` 代替 `\forall`         | C，s3 只完成 A             | 3 vs 4             |
| 统计所有学生                         | C                          | 3 vs 7             |
| 统计完成课程本身                     | C，s4 完成 C               | 3 vs 1             |
| 按“学生-先修”对计数                | C，s1/s2/s3/s4/s7 的完成对 | 3 vs 8             |
| `hasStudied` 代替 `hasCompleted` | C，s5 选了未完成           | 3 vs 4             |
| 空先修课返回 0                       | A，无先修                  | 7 vs 0             |
| 自反闭包（课程自身也算先修）         | A                          | 7 vs 4             |
| 先修方向写反                         | C                          | 3 vs 7             |
| off-by-one                           | C/A                        | 3 vs 2/4；7 vs 6/8 |
| 缺 `requires containsCourse`       | 不存在的课程               | 正常不适用 vs 适用 |
| 只写状态谓词、不绑定 `\result`     | C，错误 result             | 官方拒绝，学生接受 |

额外点：

- 空学生 fixture → 0；错误 result 1/-1。
- 不存在课程 courseId=99 → 只测 requires 适用性。
- 错误 result 变体用手写 post 点，带 result 字段；reference 拒绝，weak student 接受。
- contract_shape 用 min（requires/ensures 至少 1，signals 0）；assignable 预填 \nothing；grading 20/70/0/10；quality.min_mutation_score=100；solver.mode="off"。
- containsStudent/containsCourse 过滤可能产生等价变异（如果 hasCompleted/isPrerequisiteOf 对非学生/非课程恒假）；用 equivalent_mutations 审核，不要为凑分放宽状态域。

### 3.2 hw10：removeFromWaitlist

方法：public void removeFromWaitlist(int studentId, int courseId)

自然语言：将学生从课程的等待队列中移除。学生和课程必须存在，且学生当前在队列中；否则按异常规则处理。移除后，队列中其他学生的相对顺序不变；正式选课名单、剩余名额、成绩、其他课程都不变。

Reference JML（示意；异常类名以官方 hw10 为准；如果官方没有“不在队列”异常，先报告课程组，不要发明到官方包）：

```java
/*@ public normal_behavior
  @ requires containsStudent(studentId) && containsCourse(courseId)
  @     && isWaitlisted(studentId, courseId);
  @ assignable getCourse(courseId).waitlist;
  @ ensures !isWaitlisted(studentId, courseId);
  @ ensures waitlistLength(courseId) == \old(waitlistLength(courseId)) - 1;
  @ ensures (\forall int sid; containsStudent(sid)
  @     && \old(isWaitlisted(sid, courseId)) && sid != studentId;
  @     isWaitlisted(sid, courseId)
  @     && (\old(waitlistPosition(sid, courseId)) > \old(waitlistPosition(studentId, courseId))
  @         ==> waitlistPosition(sid, courseId) == \old(waitlistPosition(sid, courseId)) - 1)
  @     && (\old(waitlistPosition(sid, courseId)) < \old(waitlistPosition(studentId, courseId))
  @         ==> waitlistPosition(sid, courseId) == \old(waitlistPosition(sid, courseId))));
  @ ensures (\forall int sid; containsStudent(sid);
  @     (\forall int cid; containsCourse(cid);
  @         isEnrolled(sid, cid) <==> \old(isEnrolled(sid, cid))));
  @ ensures (\forall int sid; containsStudent(sid);
  @     (\forall int cid; containsCourse(cid);
  @         hasCompleted(sid, cid) <==> \old(hasCompleted(sid, cid))));
  @ ensures (\forall int sid; containsStudent(sid);
  @     (\forall int cid; containsCourse(cid);
  @         gradeOf(sid, cid) == \old(gradeOf(sid, cid))));
  @ ensures (\forall int cid; containsCourse(cid);
  @     capacity(cid) == \old(capacity(cid)));
  @ ensures (\forall int cid; containsCourse(cid) && cid != courseId;
  @     (\forall int sid; containsStudent(sid);
  @         isWaitlisted(sid, cid) <==> \old(isWaitlisted(sid, cid))));
  @ also
  @ public exceptional_behavior
  @ requires containsStudent(studentId) && containsCourse(courseId)
  @     && !isWaitlisted(studentId, courseId);
  @ assignable \nothing;
  @ signals (NotWaitlistedException e) true;
  @*/
public void removeFromWaitlist(int studentId, int courseId);
```

要求：

- 用 Profile 谓词 isWaitlisted/waitlistPosition/waitlistLength/isEnrolled/hasCompleted/capacity/gradeOf 表达，不要求数组/下标语法；assignable 里的 getCourse(courseId).waitlist 只作为 frame 文本。
- 参考 JML 必须显式写未受影响字段的 preservation。judge 的后置条件比较只看 ensures；assignable 只在 locked 区做 frame 文本比较。至少覆盖：courseId 的 enrolled 名单、capacity、成绩；其他课程的 waitlist；学生的 enrolled/completed 字段。
- 如果 <==> 实现成本高，用两条 ==> 表达双向保持；reference 和学生子集保持一致。

Fixture：

- course 1 waitlist [11,12,13], enrolled [21], capacity 2；course 2 waitlist [31,32], enrolled [], capacity 2；course 3 waitlist [41], enrolled [], capacity 1。
- 学生 11/12/13/21/31/32/41；21 已选 1，有成绩；其他字段按需要。
- 删 12 的正确后态：course 1 waitlist [11,13]；11 pos 1，13 pos 2；其余不变。

Pre 点：

- 删中(12)/首(11)/尾(13)/唯一(41, course 3)。
- 不在队列的 21（已选 1，不在 waitlist）→ 异常。
- 学生 99 / 课程 99 缺失 → 官方 normal/exceptional 都不适用；学生多写异常会暴露。
- 11 不在 course 2 的 waitlist → 异常。

Post 点：

- 上述四个正确后态 + course 2/3、学生 21、capacity、成绩不变。
- 错误变体（每个都是负测试点，reference 拒绝；weak student 接受即被抓）：
  1) 删错人（删 11，保留 12）；
  2) 删全部；
  3) 保留 12（no-op）；
  4) 顺序变成 [13,11]；
  5) 顺带把 11 晋升到 enrolled；
  6) 改 capacity；
  7) 改 course 2 waitlist；
  8) 改学生 21 的 completed/grade；
  9) 改其他无关字段。
- post_variants(rule="remove_waitlist") 返回 correct 和各错误变体；points.yaml 用 mode: "mutations"；correct 必须被 reference 接受，其他被拒绝；min_mutation_score=100.
- contract_shape 用 min；grading 建议 20/55/15/10；signals 至少 1；assignable 预填；solver off。

### 3.3 hw11：countTeachersOfCategory

方法：public int countTeachersOfCategory(String type)

自然语言：统计在课程类别 type 下至少开设了一门课程的教师人数。同一教师在同一类别下开设多门课程只计一次。type 必须是合法类别；方法只读。

Reference JML：

```java
/*@ public normal_behavior
  @ requires validType(type);
  @ assignable \nothing;
  @ ensures \result == (\num_of int tid; hasTeacher(tid);
  @     (\exists int cid; containsCourse(cid) && teacherOf(cid, tid) && typeOf(cid, type)));
  @*/
public /*@ pure @ */ int countTeachersOfCategory(String type);
```

要求：

- 教师 ID 用官方 hw11 的整数表示（recommendTeacher 返回 int[]，通常 teacher 是 int）。如果官方模型里教师是字符串，先停下报告，不要自行改为字符串量词或发明实体。
- 类别字符串用官方 hw11 Values/指导书的七种类别；fixture 里的 "A"/"B" 只是占位，最终换成官方类别名。JML 里不写字符串字面量，用 validType(type)/typeOf(cid,type) 谓词。
- 需要参数类型 "string" 的支持：parameter_types / Expressions.infer_type / EvaluationContext 参数传递 / Profile 的 validType、typeOf。如果实现成本过高，先停下报告；课程组可能换 countUnstudiedCoursesOfTeacher，不要自行换题。

Fixture：

- teachers 1,2,3,4；c1 A t1；c2 A t1；c3 A t2；c4 B t3；c5 A t3；c6 B t4。
- type A 正确结果 3（t1,t2,t3）；按课程数错 4；按所有教师错 4；用 \forall 错 2（t3 同时有 A/B）；off-by-one 2/4。
- type B 正确 2；type C 空 0；invalid type 的 pre 点只测 requires（validType false）。
- 结果错误变体作为负测试点；参考为 oracle。
- contract_shape 用 min；grading 20/70/0/10；quality 100；solver off。
- 注意：hasTeacher(tid) 这个 range 可能对“没有课程的教师”是冗余的（\exists 本来为 false）；由此产生的等价变异走 equivalent_mutations 审核。

## 4. judge 需要实现的能力

### 4.1 表达式子集（学生和 reference 同一子集）

必须：

- \result（至少 int；bool 可顺带支持）；
- \forall / \exists / \num_of；
- \old；
- ==>；
- && / || / ! / == / != / < / <= / > / >=；
- + / -（至少 -，支持 +/* 更好）；
- 负整数字面量；
- 正确的括号和优先级（==> 低于 &&/||，<==> 更低）。
  可选：
- <==>（preservation 方便；不做就用两条 ==>）；
- \sum（非必做；学生子集可只要求 \num_of）。
  不做：
- 数组/下标/length（hw10 用 Profile 谓词）；
- 字符串字面量/equals（hw11 用 typeOf/validType）；
- \let / \fresh / \datagroup / invariant / model；
- //@；
- signals_only 继续忽略。

量词要求：

- 语法：(\forall int i; range; body) / (\exists ...) / (\num_of ...)。
- range/body 作用域、类型检查；range 必须 bool，forall/exists 的 body 必须 bool，num_of 的 body 必须 bool。
- 域由 Profile 提供有限 ID 集合（学生、课程、教师），用 containsStudent/containsCourse/hasTeacher 过滤；禁止无界迭代；加迭代上限。
- \old 可包住调用/量词；量词内 \old 用 pre 状态；绑定变量作用域正确（嵌套/遮蔽）。
- \result 只在 ensures 可用；requires/signals 里出现要报错；\old(\result) 也要报错。
- 参数类型 string（hw11）；type 变量在 validType/typeOf 中传递；不需要字符串比较。
- 现有 network_v1/counter_v1 行为不变；新能力对旧 suite 不产生回归。

### 4.2 测试点 schema

- Scenario / EvaluationContext 增加 result（可选）；\result 在 post 上下文绑定；pre 点可无 result。
- points.yaml 的 post 点加 result；查询题手写正确/错误 result；变更题继续用 post + mode: "mutations"。
- validate_suite.py 的 reference 自检、mutation score、generated_post 统计要覆盖 result 点；错误 result 点要计入 min_mutation_score。
- compare_contracts 的 postcondition 用 accepts_normal_transition 带 \result；normal_applicable/exceptions/frame 不变。
- 不要引入“期望通过/失败”的字段；结果仍由 reference 判定。
- 查询题的 pre 点不需要 result；post 点带 result；post 状态用 {"copy": "pre"}。
- 错误 result 点是负样本：reference 的 ensures 为 false，weak student 为 true；postcondition 区域会暴露。

### 4.3 course_v1 Profile

- 新建 profiles/course_v1/，注册到 registry；state 用 JSON 友好结构，字段名尽量按官方 hw9/hw10/hw11；至少覆盖三个题需要的学生/课程/教师/先修/选课/已修/等待队列/容量/成绩/教师/类别。
- 谓词：
  - containsStudent, containsCourse
  - hasCompleted, hasStudied
  - isPrerequisiteOf（传递、正长度）, isDirectPrerequisiteOf（可选）
  - isEnrolled, isWaitlisted
  - waitlistPosition（1-based）, waitlistLength, capacity
  - gradeOf（可选，hw10 preservation 需要）
  - teacherOf, hasTeacher
  - typeOf, validType
- quantifier_domain/universe 返回有限 ID 集合（学生、课程、教师）；\forall/\exists/\num_of 使用；旧 profile 默认空/不变。
- parameter_types 由 SuiteProfile 覆盖；支持 int/string；infer_type/evaluate 支持 string 参数。
- post_variants("remove_waitlist", pre, args) 返回 correct/remove_wrong_student/remove_all/keep_student/reorder/promote/change_capacity/change_other_course/change_grade 等；不修改入参；规则前提是学生已在等待队列；非法状态报 ProfileError。
- 诊断/guidance 可选；不影响正确答案。

### 4.4 变异算子（core/mutations.py）

现有：delete_conjunct（顶层）、and_to_or/or_to_and、flip_comparison、remove_not、flip_boolean、widen_frame、swap_arguments、remove_old。

新增（AST 遍历，不要只靠正则）：

- forall_to_exists / exists_to_forall；
- \num_of/\exists/\forall 的 range/body 合取删除/否定；结构变异（按学生-先修对计数）可手写；
- imply_to_and、<==> 拆分（如支持）；
- integer_literal_delta（0/1/-1）；result_delta（\result ± 1）、result_constant；
- 算术 +/-；
- add_not（布尔调用/谓词）；bool_call_to_constant（true/false）；
- replace_call：hasCompleted↔hasStudied、isPrerequisiteOf↔isDirectPrerequisiteOf、isWaitlisted↔isEnrolled（按题目）、validType→true；通过 Profile 的 confusable_calls 或 suite 配置提供，保持旧 profile 兼容；
- swap_arguments 要类型安全（typeOf(cid,type) 这类 int/string 不交换，或跳过不可解析变异）；
- delete_conjunct 递归到量词体/range（注意等价变异，走 review）；
- 保留 \old 去除、frame 放宽。

每个新算子加单元测试；validate_suite 能报告 survivors/effective_score；equivalent_mutations 的 SHA-256 审核记录；不要把 min_mutation_score 降到 100 以下来掩盖问题。

### 4.5 公平性/评分

- contract_shape 用 min/max，不用精确条数；学生多写冗余 => 不判错。
- assignable 预填/锁定；signals_only 不要求；不要用 output 注释；locked 权重 10。
- 等价写法：\num_of range+true vs range+body；\forall vs !\exists；两条 ==> vs <==>；Profile 谓词别名（如果语义等价）；都要通过。
- 学生评分是逐点比较；passed = 无诊断，score = 区域加权；错误 result/后态点暴露弱规格；正确点暴露过强规格。
- 文档写清“测试点是有限点，不是完全等价证明”；不要把 mutation score 当学生分数。

## 5. 交付物

1. 扩展后的 parser/evaluator/contracts/profile/suite/judge；旧测试通过。
2. profiles/course_v1/（state/predicates/quantifier_domain/post_variants/registry）。
3. suites/CourseInterface/countEligibleStudents/{suite.yaml,points.yaml,reference.java}；removeFromWaitlist/；countTeachersOfCategory/。
4. examples/ 或 student_submissions/ 下的课程样例：每题 correct、equivalent（至少 1）、wrong（覆盖表中的主要错误，至少 5 个）；semantic_check.py --json 输出。
5. JML.java 模板（每题一个；签名+JML 块+assignable 预填；自然语言不写进 Java；由课程组放进 JML 文件夹）。
6. 新测试：parser 量词/\result/==>/负数/string；point result；mutation 新算子；course_v1 谓词/post_variants；suite 端到端。
7. USAGE.md/README.md 增补：新子集、course_v1、三道 suite、如何跑 validate_suite/semantic_check、学生允许的关键字、等价写法、有限点说明。
8. build_release.py/student_submissions/check_submissions.py 如涉及清单，更新。
9. 一份工作区报告：基线测试、每套 validate_suite 的 JSON 摘要、样例评分、已知等价变异/审核、未决问题、未改课程仓库的确认。

## 6. 验收标准

- 三套 suite 的 validate_suite.py 均 valid: true；mutations.effective_score 100；unexpected_survivors []；reviewed_equivalent 有记录且 SHA 绑定。
- reference JML 在每个点自检通过；correct 样例 semantic_check 100/passed；equivalent 样例 100/passed；每个 wrong 样例 <100 且诊断指向预期区域。
- 现有 network_v1/counter_v1 suite 和全部单元测试通过；run_tests.py 通过。
- course_v1 的 quantifier_domain 覆盖学生/课程/教师；量词迭代有上限；无随机/无网络；solver off 可跑。
- JML.java 模板与 reference 签名/方法名/JML 块一致；assignable 预填；signals_only 可省略；hw9/hw10/hw11 不出现后续迭代概念。
- 课程仓库（2027_OfficialPackage、revised_guidebooks）零改动；如需要课程仓库文件，只在 examples/ 提供并由课程组复制。
- 交付报告包含 validate_suite 和 semantic_check 的实际输出，不要只说“已完成”。

## 7. 约束/不要做

- 不要改指导书/官方包；不要 commit/push（除非课程组明确要求）。
- 不要弱化 reference 或点集来让样例通过；reference 是 oracle；如果样例正确但失败，先查点和 reference，再报告。
- 不要为了 min_mutation_score 加非法状态；等价变异走 equivalent_mutations 审核。
- 不要引入学生子集外的语法（数组/字符串字面量/\let/\fresh/无界量词）；reference 必须和学生子集一致。
- 不要在前面的题里出现后续题的概念（hw9 不出现 hw10/hw11 的等待队列/教师；hw10 不出现 hw11 的类别推荐）。
- 不要发明官方包没有的教师实体/异常类；遇到与官方模型冲突（hw10 异常名、hw11 类别字符串/教师表示、官方字段名）先报告，等课程组确认。
- 不要用 /tmp/jml-demo-inspect 当工作区；使用正式 judge 仓库/独立工作区；不运行不可信下载的脚本；用 venv；运行时无网络。
- 不要一次把三题全做完：先 hw9 端到端（suite+样例+validate），报告后再 hw10/hw11。

## 8. 建议顺序

1) 读代码/文档/官方包；跑基线测试。
2) 扩展表达式 + result schema + 测试。
3) course_v1 + 谓词 + 量词域 + 测试。
4) 变异算子 + 测试。
5) hw9 suite + points + reference + 样例 + validate；报告。
6) hw10；报告。
7) hw11；报告。
8) 文档/发布/总验收。

## 9. 开工前需要确认的项（先报告，不要自行决定）

- hw10 “不在等待队列” 的官方异常类名/构造参数；官方包没有就等课程组定义。
- hw11 官方类别字符串、教师是 int 还是字符串、官方字段名；如果教师是字符串，countTeachersOfCategory 的 \num_of int tid 需要调整，先报告。
- hw11 是否接受 String 参数/validType/typeOf 的 Profile 谓词方案；如果实现成本过高，课程组会决定是否换 countUnstudiedCoursesOfTeacher。
- JML.java 的 package/import/extends SemesterInterface 写法；assignable 是否预填；contract_shape 的 min 配置；grading 权重。
- hw9/hw10/hw11 的自然语言最终文本由课程组指导书给出；你按本提示的草案写 reference，如发现歧义先报告。

## 10. JML.java 模板示例（hw9）

```java
// 由课程组复制到 JML/JML.java；不要放进 src/test；不实现、不调用
public interface JML extends SemesterInterface {
    /*@ public normal_behavior
      @ requires /* 学生补全 */;
      @ assignable \nothing;
      @ ensures /* 学生补全 */;
      @*/
    public int countEligibleStudents(int courseId);
}
```

hw10/hw11 模板同构：固定签名，assignable 预填，requires/ensures/signals 留给学生；自然语言只在指导书里，不写进 Java 文件。
