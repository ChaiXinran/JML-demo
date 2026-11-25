"""Curated HW10 reserveSeats student specifications."""

from case import Case


VALID = "0 <= start && start <= occupied.length\n      @     && 0 < count && count <= occupied.length - start"
INVALID = "start < 0 || start > occupied.length\n      @     || count <= 0 || count > occupied.length - start"
RANGE = "start <= i && i < start + count"
FREE = rf"(\forall int i; {RANGE}; !occupied[i])"
TAKEN = rf"(\exists int i; {RANGE}; occupied[i])"
DONE = rf"(\forall int i; {RANGE}; occupied[i])"
RESULT = r"\result && occupied == \old(occupied)"
FRAME = "occupied[start .. start + count - 1]"


def cases(reference: str) -> list[Case]:
    values = []

    def variant(name, expected, before, after, reason, count=1):
        assert before in reference, before
        source = reference.replace(before, after, count)
        values.append(Case(name, expected, "equivalent" if expected == "PASS" else "semantic",
                           reason, source))

    variant("hw10-ok-shift-range", "PASS", FRAME, "occupied[start .. count + start - 1]",
            "加法可交换，允许写入的槽位不变。")
    variant("hw10-ok-frame-end", "PASS", FRAME, "occupied[start .. start + (count - 1)]",
            "重加括号不改变最后一个可写槽位。")
    variant("hw10-ok-negated-exists", "PASS", FREE, "!" + TAKEN,
            "范围内全部空闲等价于不存在已占用。")
    variant("hw10-ok-negated-forall", "PASS", TAKEN, "!" + FREE,
            "存在占用等价于并非全部空闲。")
    variant("hw10-ok-old-conflict", "PASS", TAKEN, rf"\old({TAKEN})",
            "前置条件本来在调用前检查。")
    variant("hw10-ok-boolean-false", "PASS", r"ensures !\result;", r"ensures \result == false;",
            "正常冲突返回布尔 false 的等价写法。")
    variant("hw10-ok-redundant-array-identity", "PASS", RESULT, r"\result",
            "区间 frame 已禁止重新绑定字段，显式身份判断重复。")
    variant("hw10-ok-negated-invalid", "PASS", INVALID, "!(" + VALID.replace("\n      @     ", " ") + ")",
            "非法条件写成合法条件的否定。")
    variant("hw10-ok-quantified-count", "PASS", TAKEN,
            rf"(\num_of int i; {RANGE}; occupied[i]) > 0", "存在占用等价于占用总数大于零。")
    variant("hw10-ok-valid-addition", "PASS", VALID,
            "0 <= start && 0 < count && start + count <= occupied.length",
            "合法参数用数学加法约束末尾，与原减法约束等价。", count=2)

    mistakes = [
        ("different-exception", "signals_only IllegalArgumentException;", "signals_only NullPointerException;",
         "start=-1 时应抛 IllegalArgumentException。"),
        ("exception-absent", "signals_only IllegalArgumentException;", "signals_only \\nothing;",
         "非法参数也不允许抛异常。"),
        ("exception-wider", "signals_only IllegalArgumentException;",
         "signals_only IllegalArgumentException, RuntimeException;",
         "额外允许 RuntimeException 类型。"),
        ("throws-on-valid", INVALID, "true",
         "任何输入都触发异常分支，含合法的 start=0,count=1。"),
        ("start-zero-forbidden", VALID, VALID.replace("0 <= start", "0 < start"),
         "[false]、start=0,count=1 合法。", 2),
        ("count-one-forbidden", VALID, VALID.replace("0 < count", "1 < count"),
         "[false]、start=0,count=1 合法。", 2),
        ("count-zero-missed", INVALID, INVALID.replace("count <= 0", "count < 0"),
         "count=0 应当抛异常。"),
        ("too-short-end", VALID, VALID.replace("count <= occupied.length - start", "count < occupied.length - start"),
         "区间末端可以恰好到数组最后一格。", 2),
        ("too-long-end", INVALID, INVALID.replace("count > occupied.length - start", "count > occupied.length"),
         "长度为 3 时 start=2,count=2 越界。"),
        ("conflict-requires-all", TAKEN, rf"(\forall int i; {RANGE}; occupied[i])",
         "范围内有一座被占用就冲突，不能要求每座都被占用。"),
        ("free-requires-some", FREE, rf"(\exists int i; {RANGE}; !occupied[i])",
         "[false,true] 全范围不能成功。"),
        ("omits-conflict-result", r"ensures !\result;", "ensures true;",
         "预订冲突且无状态变化时仍不能返回 true。"),
        ("conflict-result-true", r"ensures !\result;", r"ensures \result;",
         "冲突应返回 false。"),
        ("success-result-false", RESULT, r"!\result && occupied == \old(occupied)",
         "空闲区间成功分配时应返回 true。"),
        ("permits-success-false", RESULT, r"occupied == \old(occupied)",
         "座位都改对但返回 false 仍然错误。"),
        ("omits-success-update", DONE, "true",
         "成功返回 true 时，也必须修改每个相关座位。"),
        ("only-updates-some", DONE, rf"(\exists int i; {RANGE}; occupied[i])",
         "请求两座时只把其中一座置为 true 仍不够。"),
        ("updates-outside", FRAME, "occupied[*]",
         "不能修改目标区间外的元素。"),
        ("replaces-array", FRAME, r"occupied, occupied[*]",
         "新分配数组替换原字段违反可写范围。"),
        ("does-not-allow-write", FRAME, r"\nothing",
         "合法成功操作需要写入目标槽位。"),
        ("end-off-by-one", FRAME, "occupied[start .. start + count]",
         "可写端点多出了一格。"),
        ("frame-omits-first", FRAME, "occupied[start + 1 .. start + count - 1]",
         "目标区间首位也应该允许写入。"),
        ("success-updates-pre-not-post", DONE, rf"(\forall int i; {RANGE}; \old(occupied[i]))",
         "成功路径中的座位调用前是空闲的，所需更新发生在调用后。"),
        ("success-stays-free", DONE, FREE,
         "将成功后置条件错写为座位仍然空闲。"),
        ("bad-frame-on-exception", r"assignable \nothing;", "assignable occupied[*];",
         "非法操作不能改任何座位。"),
    ]
    for name, before, after, reason, *count in mistakes:
        variant("hw10-wrong-" + name, "FAIL", before, after, reason, *(count or [1]))
    return values
