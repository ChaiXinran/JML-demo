"""Simulated student JML submissions for HW11 longestFreeBlock."""

from case import Case


FORMAT = "JML_FORMAT_OR_SYMBOL"

NONNULL = "occupied != null"
ALL_OCCUPIED = r"(\forall int i; 0 <= i && i < occupied.length; occupied[i])"
HAS_FREE = r"(\exists int i; 0 <= i && i < occupied.length; !occupied[i])"
FREE_COUNT = r"(\num_of int i; 0 <= i && i < occupied.length; !occupied[i])"
OCCUPIED_COUNT = r"(\num_of int i; 0 <= i && i < occupied.length; occupied[i])"

SELECTED_FREE = (
    r"(\forall int offset; 0 <= offset && offset < \result[1]; "
    r"!occupied[\result[0] + offset])"
)
SELECTED_NOT_OCCUPIED = (
    r"!(\exists int offset; 0 <= offset && offset < \result[1]; "
    r"occupied[\result[0] + offset])"
)
SELECTED_FREE_COUNT = (
    r"(\num_of int offset; 0 <= offset && offset < \result[1]; "
    r"!occupied[\result[0] + offset]) == \result[1]"
)
RESULT_SHAPE = (
    r"\result != null && \result.length == 2"
    r" && 0 <= \result[0] && \result[0] < occupied.length"
    r" && 0 < \result[1] && \result[1] <= occupied.length - \result[0]"
)
CANDIDATE_RANGE = (
    "0 <= start && start < occupied.length && 0 < length "
    "&& length <= occupied.length - start"
)
CANDIDATE_FREE = (
    r"(\forall int offset; 0 <= offset && offset < length; "
    r"!occupied[start + offset])"
)
CANDIDATE_NOT_OCCUPIED = (
    r"!(\exists int offset; 0 <= offset && offset < length; "
    r"occupied[start + offset])"
)
BEST = r"length < \result[1] || (length == \result[1] && \result[0] <= start)"
BEST_IMPLICATION = (
    r"length <= \result[1] && "
    r"(length == \result[1] ==> \result[0] <= start)"
)
NOT_DOMINATED = (
    r"!(length > \result[1] || "
    r"(length == \result[1] && start < \result[0]))"
)
MAXIMUM = (
    r"(\forall int start, length; " + CANDIDATE_RANGE + " && "
    + CANDIDATE_FREE + "; " + BEST + ")"
)


def _jml(reference: str, clauses: list[str]) -> str:
    """Replace the one contract comment while preserving the reference signature."""
    block = "/*@\n" + "\n".join(f"      @ {line}" for line in clauses) + "\n      @*/"
    start = reference.find("/*@")
    end = reference.find("@*/", start)
    if start < 0 or end < 0 or reference.find("/*@", start + 3) >= 0:
        raise ValueError("longestFreeBlock reference must contain exactly one JML block")
    return reference[:start] + block + reference[end + 3:]


def _two_behavior(
    reference: str,
    *,
    full_condition: str = ALL_OCCUPIED,
    free_condition: str = HAS_FREE,
    full_ensures: tuple[str, ...] = (r"\result != null && \result.length == 0",),
    free_ensures: tuple[str, ...] | None = None,
    frame: str = r"\nothing",
    full_requires: tuple[str, ...] | None = None,
    free_requires: tuple[str, ...] | None = None,
) -> str:
    if free_ensures is None:
        free_ensures = (RESULT_SHAPE + " && " + SELECTED_FREE + " && " + MAXIMUM,)
    if full_requires is None:
        full_requires = (NONNULL, full_condition)
    if free_requires is None:
        free_requires = (NONNULL, free_condition)
    clauses = ["public normal_behavior"]
    clauses.extend(f"requires {item};" for item in full_requires)
    clauses.append(f"assignable {frame};")
    clauses.extend(f"ensures {item};" for item in full_ensures)
    clauses.extend(("also", "public normal_behavior"))
    clauses.extend(f"requires {item};" for item in free_requires)
    clauses.append(f"assignable {frame};")
    clauses.extend(f"ensures {item};" for item in free_ensures)
    return _jml(reference, clauses)


def _single_behavior(reference: str, clauses: list[str]) -> str:
    return _jml(reference, ["public normal_behavior", *clauses])


def _case(
    case_id: str,
    expectation: str,
    category: str,
    reason: str,
    source: str,
    diagnostic: str | None = None,
) -> Case:
    return Case(case_id, expectation, category, reason, source, diagnostic)


def cases(reference: str) -> list[Case]:
    """Return independent correct, incorrect, boundary, syntax, and budget probes."""
    items: list[Case] = []

    # Correct specifications: mathematically equivalent descriptions, including
    # alternative quantifier formulations and a single guarded behavior.
    items.append(_case(
        "hw11-correct-reference", "PASS", "equivalent",
        "标准合同：无空座返回空数组；有空座时选最长区间，并列选最早起点。", reference,
    ))
    items.append(_case(
        "hw11-correct-max-implication", "PASS", "equivalent",
        "把最长与并列规则写成长度不超过结果、等长时结果起点不晚于候选起点。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_FREE
            + r" && (\forall int start, length; " + CANDIDATE_RANGE + " && "
            + CANDIDATE_FREE + "; " + BEST_IMPLICATION + ")",
        )),
    ))
    items.append(_case(
        "hw11-correct-no-dominating-run", "PASS", "equivalent",
        "逐个排除比结果更长、或等长但起点更早的空闲区间。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_FREE
            + r" && (\forall int start, length; " + CANDIDATE_RANGE + " && "
            + CANDIDATE_FREE + "; " + NOT_DOMINATED + ")",
        )),
    ))
    items.append(_case(
        "hw11-correct-selected-no-occupied-seat", "PASS", "equivalent",
        "用“不存在被占用的所选座位”替代所选区间的全称空闲条件。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_NOT_OCCUPIED + " && " + MAXIMUM,
        )),
    ))
    items.append(_case(
        "hw11-correct-selected-free-count", "PASS", "equivalent",
        "所选区间长度为正且有界；其中空闲座位数等于区间长度，故全部空闲。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_FREE_COUNT + " && " + MAXIMUM,
        )),
    ))
    items.append(_case(
        "hw11-correct-no-occupied-candidate-seat", "PASS", "equivalent",
        "用“不存在被占用的候选座位”表达候选区间全空闲。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_FREE
            + r" && (\forall int start, length; " + CANDIDATE_RANGE + " && "
            + CANDIDATE_NOT_OCCUPIED + "; " + BEST + ")",
        )),
    ))
    guarded = (
        "requires occupied != null;",
        r"assignable \nothing;",
        r"ensures \result != null;",
        "ensures " + ALL_OCCUPIED + r" ==> \result.length == 0;",
        "ensures " + HAS_FREE + " ==> (" + RESULT_SHAPE + " && "
        + SELECTED_FREE + " && " + MAXIMUM + ");",
    )
    items.append(_case(
        "hw11-correct-one-guarded-behavior", "PASS", "equivalent",
        "把两个互斥情形合并成一个行为，并用全占满/存在空座分别约束结果。",
        _single_behavior(reference, list(guarded)),
    ))
    count_full = OCCUPIED_COUNT + " == occupied.length"
    count_has_free = FREE_COUNT + " > 0"
    items.append(_case(
        "hw11-correct-count-branching", "PASS", "equivalent",
        "用空闲座位数为零或大于零划分两种输入情形，包含空数组。",
        _two_behavior(reference, full_condition=count_full, free_condition=count_has_free),
    ))
    sub_bound = (
        r"\result != null && \result.length == 2 && 0 <= \result[0]"
        r" && 0 < \result[1] && \result[1] <= occupied.length"
        r" && \result[0] <= occupied.length - \result[1]"
    )
    items.append(_case(
        "hw11-correct-subtraction-bound", "PASS", "equivalent",
        "用起点不超过数组长度减区间长度表达右边界，不改变合法区间集合。",
        _two_behavior(reference, free_ensures=(
            sub_bound + " && " + SELECTED_FREE + " && " + MAXIMUM,
        )),
    ))
    items.append(_case(
        "hw11-correct-split-postconditions", "PASS", "equivalent",
        "将结果形状、所选区间空闲、最长及并列规则拆成多个 ensures 同时约束。",
        _two_behavior(reference, free_ensures=(
            r"\result != null && \result.length == 2",
            r"0 <= \result[0] && \result[0] < occupied.length",
            r"0 < \result[1] && \result[1] <= occupied.length - \result[0]",
            SELECTED_FREE,
            MAXIMUM,
        )),
    ))

    # Realistic semantic errors and off-by-one variants. Each reason names a
    # concrete legal input/result that contradicts the intended contract.
    items.append(_case(
        "hw11-wrong-accepts-null", "FAIL", "semantic",
        "额外声明 occupied == null 时也可正常调用；例如 null 不满足题目要求的非 null 前置条件。",
        _jml(reference, [
            "public normal_behavior", "requires occupied == null;", r"assignable \nothing;",
            r"ensures \result == null || \result != null;", "also",
            "public normal_behavior", f"requires {NONNULL};", f"requires {ALL_OCCUPIED};",
            r"assignable \nothing;", r"ensures \result != null && \result.length == 0;", "also",
            "public normal_behavior", f"requires {NONNULL};", f"requires {HAS_FREE};",
            r"assignable \nothing;", f"ensures {RESULT_SHAPE} && {SELECTED_FREE} && {MAXIMUM};",
        ]),
    ))
    too_strong = NONNULL + " && occupied.length > 0"
    items.append(_case(
        "hw11-wrong-reject-empty-input", "FAIL", "semantic",
        "前置条件排除了合法空数组；空数组应正常返回长度为 0 的结果。",
        _two_behavior(reference, full_requires=(too_strong, ALL_OCCUPIED),
                      free_requires=(too_strong, HAS_FREE)),
    ))
    items.append(_case(
        "hw11-wrong-full-case-exists-occupied", "FAIL", "semantic",
        "把全占满写成“存在一个占用座位”；输入 [true,false] 同时触发空结果与长度 2 的要求。",
        _two_behavior(reference, full_condition=(
            r"(\exists int i; 0 <= i && i < occupied.length; occupied[i])"
        )),
    ))
    items.append(_case(
        "hw11-wrong-empty-result-length-one", "FAIL", "semantic",
        "全占满时要求长度 1；输入 [true] 按题意应返回长度 0 的数组。",
        _two_behavior(reference, full_ensures=(r"\result != null && \result.length == 1",)),
    ))
    items.append(_case(
        "hw11-wrong-null-result-allowed", "FAIL", "semantic",
        "全占满时允许 null；例如 [true] 的结果必须是非 null 空数组。",
        _two_behavior(reference, full_ensures=(
            r"\result == null || (\result != null && \result.length == 0)",
        )),
    ))
    items.append(_case(
        "hw11-wrong-empty-result-allowed-with-free-seat", "FAIL", "semantic",
        "有空座时允许空结果；输入 [false] 必须返回 [0,1]，不能返回 []。",
        _two_behavior(reference, free_ensures=(
            r"\result != null && (\result.length == 0 || (" + RESULT_SHAPE
            + " && " + SELECTED_FREE + " && " + MAXIMUM + "))",
        )),
    ))
    items.append(_case(
        "hw11-wrong-result-length-one", "FAIL", "semantic",
        "有空座时要求结果数组长度为 1；输入 [false] 应返回含起点和长度的 [0,1]。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE.replace(r"\result.length == 2", r"\result.length == 1")
            + " && " + SELECTED_FREE + " && " + MAXIMUM,
        )),
    ))
    items.append(_case(
        "hw11-wrong-result-allows-extra-field", "FAIL", "semantic",
        "只要求结果数组至少两个元素；[false] 时长度 3 的结果也会被接受，题目要求恰好 2。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE.replace(r"\result.length == 2", r"\result.length >= 2")
            + " && " + SELECTED_FREE + " && " + MAXIMUM,
        )),
    ))
    endpoint_post = (
        r"\result != null && \result.length == 2 && 0 <= \result[0]"
        r" && \result[0] < \result[1] && \result[1] <= occupied.length"
        r" && (\forall int offset; 0 <= offset && offset < \result[1] - \result[0];"
        r" !occupied[\result[0] + offset])"
        r" && (\forall int start, length; " + CANDIDATE_RANGE + " && " + CANDIDATE_FREE
        + r"; length < \result[1] - \result[0] || "
        r"(length == \result[1] - \result[0] && \result[0] <= start))"
    )
    items.append(_case(
        "hw11-wrong-second-value-is-end-index", "FAIL", "semantic",
        "把第二项当区间终点而非长度；输入 [true,false,false] 应给 [1,2]，该写法会要求 [1,3]。",
        _two_behavior(reference, free_ensures=(endpoint_post,)),
    ))
    items.append(_case(
        "hw11-wrong-start-must-be-positive", "FAIL", "semantic",
        "起点要求大于 0；输入 [false] 的唯一最长空闲段从下标 0 开始。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE.replace(r"0 <= \result[0]", r"0 < \result[0]")
            + " && " + SELECTED_FREE + " && " + MAXIMUM,
        )),
    ))
    items.append(_case(
        "hw11-wrong-selected-seat-occupied", "FAIL", "semantic",
        "把所选区间中的空闲条件反写为已占用；输入 [true,false] 会错误允许选择 [0,1]。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + r" && (\forall int offset; 0 <= offset && offset < \result[1]; "
            + r"occupied[\result[0] + offset]) && " + MAXIMUM,
        )),
    ))
    items.append(_case(
        "hw11-wrong-only-check-first-selected-seat", "FAIL", "semantic",
        "只检查起点空闲；[false,true,false] 中会允许跨过被占用的座位返回 [0,2]。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + r" && !occupied[\result[0]] && " + MAXIMUM,
        )),
    ))
    items.append(_case(
        "hw11-wrong-no-maximality", "FAIL", "semantic",
        "没有最长性约束；输入 [false,false,true] 的 [0,1] 不是最长连续空座段。",
        _two_behavior(reference, free_ensures=(RESULT_SHAPE + " && " + SELECTED_FREE,)),
    ))
    items.append(_case(
        "hw11-wrong-tie-later", "FAIL", "semantic",
        "并列时允许选更晚区间；[false,false,true,false,false] 应选 [0,2] 而非 [3,2]。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_FREE
            + r" && (\forall int start, length; " + CANDIDATE_RANGE + " && "
            + CANDIDATE_FREE + r"; length < \result[1] || "
            + r"(length == \result[1] && \result[0] >= start))",
        )),
    ))
    items.append(_case(
        "hw11-wrong-tie-unconstrained", "FAIL", "semantic",
        "只比较长度，不规定并列时取最早；[false,false,true,false,false] 可错误选 [3,2]。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_FREE
            + r" && (\forall int start, length; " + CANDIDATE_RANGE + " && "
            + CANDIDATE_FREE + r"; length <= \result[1])",
        )),
    ))
    items.append(_case(
        "hw11-wrong-only-compare-later-starts", "FAIL", "semantic",
        "只比较结果起点及之后的候选段；[false,false,true,false] 可错误选 [3,1]，漏掉更早的 [0,2]。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_FREE
            + r" && (\forall int start, length; " + CANDIDATE_RANGE
            + r" && \result[0] <= start && " + CANDIDATE_FREE + "; " + BEST + ")",
        )),
    ))
    items.append(_case(
        "hw11-wrong-max-prefers-shorter", "FAIL", "semantic",
        "要求结果长度不大于每个候选长度；[false,false,true] 的正确 [0,2] 会被长度 1 的候选否定。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_FREE
            + r" && (\forall int start, length; " + CANDIDATE_RANGE + " && "
            + CANDIDATE_FREE + r"; \result[1] <= length)",
        )),
    ))
    items.append(_case(
        "hw11-wrong-candidate-offset-inclusive", "FAIL", "semantic",
        "候选区间把 offset <= length 当作范围；[false,false,true] 的长度 2 段会被误排除，允许只返回 [0,1]。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_FREE
            + r" && (\forall int start, length; " + CANDIDATE_RANGE
            + r" && (\forall int offset; 0 <= offset && offset <= length; "
            + r"!occupied[start + offset]); " + BEST + ")",
        )),
    ))
    items.append(_case(
        "hw11-wrong-selected-offset-inclusive", "FAIL", "semantic",
        "所选区间也把结束下标算入；[false,false,true] 的正确结果 [0,2] 会额外检查占用的下标 2。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + r" && (\forall int offset; 0 <= offset && offset <= \result[1]; "
            + r"!occupied[\result[0] + offset]) && " + MAXIMUM,
        )),
    ))
    items.append(_case(
        "hw11-wrong-ignore-block-ending-at-array-end", "FAIL", "semantic",
        "候选长度要求严格小于剩余长度；[true,false,false] 的长度 2 最大段恰好到数组末尾，会被漏掉。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_FREE
            + r" && (\forall int start, length; 0 <= start && start < occupied.length "
            + "&& 0 < length && length < occupied.length - start && " + CANDIDATE_FREE
            + "; " + BEST + ")",
        )),
    ))
    items.append(_case(
        "hw11-wrong-ignore-block-at-index-zero", "FAIL", "semantic",
        "候选起点要求大于 0；[false,false,true] 可漏掉从 0 开始的长度 2 段并选 [2,1]。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_FREE
            + r" && (\forall int start, length; 0 < start && start < occupied.length "
            + "&& 0 < length && length <= occupied.length - start && " + CANDIDATE_FREE
            + "; " + BEST + ")",
        )),
    ))
    items.append(_case(
        "hw11-wrong-require-room-after-result", "FAIL", "semantic",
        "把结果右边界写成严格小于；[true,false] 的合法最长段 [1,1] 正好到数组末尾，会被拒绝。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE.replace(
                r"\result[1] <= occupied.length - \result[0]",
                r"\result[1] < occupied.length - \result[0]",
            ) + " && " + SELECTED_FREE + " && " + MAXIMUM,
        )),
    ))
    items.append(_case(
        "hw11-wrong-full-case-only-empty-array", "FAIL", "semantic",
        "把无空座误写成数组长度为 0；输入 [true] 没有空座但不满足任何行为前置条件。",
        _two_behavior(reference, full_condition="occupied.length == 0"),
    ))
    items.append(_case(
        "hw11-wrong-free-candidate-only-first-seat", "FAIL", "semantic",
        "候选段只检查起点空闲；[false,true,false] 会把起点 0 的长度 2 当作空段，错误拒绝正确结果 [0,1]。",
        _two_behavior(reference, free_ensures=(
            RESULT_SHAPE + " && " + SELECTED_FREE
            + r" && (\forall int start, length; " + CANDIDATE_RANGE
            + r" && !occupied[start]; " + BEST + ")",
        )),
    ))
    items.append(_case(
        "hw11-wrong-frame-allows-array-mutation", "FAIL", "semantic",
        "assignable occupied[*] 允许改写输入元素；题意要求 [false] 调用后仍保持原数组不变。",
        _two_behavior(reference, frame="occupied[*]"),
    ))

    # Correct-but-outside-subset and deliberately malformed submissions.
    unsupported = _two_behavior(reference, free_ensures=(
        r"\result instanceof int[] && \result.length == 2"
        + " && 0 <= " + r"\result[0] && \result[0] < occupied.length"
        + " && 0 < " + r"\result[1] && \result[1] <= occupied.length - \result[0]"
        + " && " + SELECTED_FREE + " && " + MAXIMUM,
    ))
    items.append(_case(
        "hw11-unsupported-instanceof-result", "FAIL", "unsupported",
        "instanceof int[] 在方法返回类型固定为 int[] 时可替代非 null 检查，但不属于评测器支持的表达式子集。",
        unsupported, FORMAT,
    ))
    unknown = _two_behavior(reference, full_requires=(
        NONNULL,
        r"(\forall int i; 0 <= i && i < occupied.length; vacant[i])",
    ))
    items.append(_case(
        "hw11-syntax-unknown-array-name", "FAIL", "syntax",
        "量词引用了未声明的 vacant；数组参数名必须是 occupied。",
        unknown, FORMAT,
    ))
    non_int_quantifier = _two_behavior(reference, full_requires=(
        NONNULL,
        r"(\forall boolean i; 0 <= i && i < occupied.length; occupied[i])",
    ))
    items.append(_case(
        "hw11-syntax-non-int-quantifier", "FAIL", "syntax",
        "量词绑定变量写成 boolean；当前题目支持的数组下标量词必须绑定 int。",
        non_int_quantifier, FORMAT,
    ))
    missing_semicolon = _jml(reference, [
        "public normal_behavior", f"requires {NONNULL}", f"requires {ALL_OCCUPIED};",
        r"assignable \nothing;", r"ensures \result != null && \result.length == 0;",
        "also", "public normal_behavior", f"requires {NONNULL};", f"requires {HAS_FREE};",
        r"assignable \nothing;", f"ensures {RESULT_SHAPE} && {SELECTED_FREE} && {MAXIMUM};",
    ])
    items.append(_case(
        "hw11-syntax-missing-requires-semicolon", "FAIL", "syntax",
        "第一条 requires 缺少分号，无法与下一条 JML 子句分开。",
        missing_semicolon, FORMAT,
    ))
    unbalanced = _two_behavior(reference, free_ensures=(
        RESULT_SHAPE + " && (" + SELECTED_FREE + " && " + MAXIMUM,
    ))
    items.append(_case(
        "hw11-syntax-unbalanced-parenthesis", "FAIL", "syntax",
        "后置条件少一个右括号，表达式无法完整解析。", unbalanced, FORMAT,
    ))
    items.append(_case(
        "hw11-resource-unbounded-work", "FAIL", "resource",
        "额外的恒真有界量词遍历约 2^31 个整数；应由规格求值预算安全终止。",
        _two_behavior(reference, full_requires=(
            NONNULL,
            ALL_OCCUPIED + r" && (\forall int q; 0 <= q && q < 2147483647; q >= 0)",
        )),
        FORMAT,
    ))

    return items
