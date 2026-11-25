"""Curated simulated submissions for HW9's firstDuplicateIndex contract."""

from __future__ import annotations

import re

from case import Case


FORMAT = "JML_FORMAT_OR_SYMBOL"

NO_DUPLICATES = (
    r"(\forall int i, j; 0 <= i && i < j && j < ids.length;"
    r" ids[i] != ids[j])"
)
DUPLICATE_AT_RESULT = (
    r"(\exists int i; 0 <= i && i < \result;"
    r" ids[i] == ids[\result])"
)
PREFIX_UNIQUE = (
    r"(\forall int i, j; 0 <= i && i < j && j < \result;"
    r" ids[i] != ids[j])"
)
RESULT_IS_FIRST_DUPLICATE = (
    r"\result != -1 ==> 0 <= \result && \result < ids.length"
    r" && " + DUPLICATE_AT_RESULT + r" && " + PREFIX_UNIQUE
)


def _source(reference: str, ensures: list[str], *, requires: str = "ids != null;",
            assignable: str = r"\nothing;") -> str:
    """Keep the official class/signature and replace only its contract."""
    match = re.search(r"/\*@.*?@\*/", reference, flags=re.DOTALL)
    if match is None:
        raise ValueError("HW9 reference has no block JML contract")
    frame_clause = f"      @ assignable {assignable}\n" if assignable else ""
    clauses = "\n".join(f"      @ ensures {clause};" for clause in ensures)
    contract = (
        "/*@ public normal_behavior\n"
        f"      @ requires {requires}\n"
        f"{frame_clause}"
        f"{clauses}\n"
        "      @*/"
    )
    return reference[:match.start()] + contract + reference[match.end():]


def _base(reference: str) -> str:
    return _source(reference, [
        rf"\result == -1 <==> {NO_DUPLICATES}",
        RESULT_IS_FIRST_DUPLICATE,
    ])


def cases(reference: str) -> list[Case]:
    """Return independently labeled, hand-curated HW9 answer variants."""
    base = _base(reference)
    equivalent = [
        Case("hw9-correct-reference", "PASS", "equivalent",
             "原版规约：无重复返回 -1；否则返回第一个重复位置。", reference),
        Case("hw9-correct-split-iff", "PASS", "equivalent",
             "把等价关系拆成两个方向的蕴含，逻辑等价。", _source(reference, [
                 rf"(\result == -1 ==> {NO_DUPLICATES}) && "
                 rf"({NO_DUPLICATES} ==> \result == -1)",
                 RESULT_IS_FIRST_DUPLICATE,
             ])),
        Case("hw9-correct-count-zero", "PASS", "equivalent",
             "无重复等价于有序下标对中相等值的数量为零。", _source(reference, [
                 r"\result == -1 <==> (\num_of int i, j; "
                 r"0 <= i && i < j && j < ids.length; ids[i] == ids[j]) == 0",
                 RESULT_IS_FIRST_DUPLICATE,
             ])),
        Case("hw9-correct-nested-forward", "PASS", "equivalent",
             "把二元全称量词写成先枚举 i、再枚举其后的 j。", _source(reference, [
                 r"\result == -1 <==> (\forall int i; "
                 r"0 <= i && i < ids.length; (\forall int j; "
                 r"i < j && j < ids.length; ids[i] != ids[j]))",
                 RESULT_IS_FIRST_DUPLICATE,
             ])),
        Case("hw9-correct-nested-reverse", "PASS", "equivalent",
             "先枚举 j，再检查它之前每个 i；检查的仍是所有 i<j。", _source(reference, [
                 r"\result == -1 <==> (\forall int j; "
                 r"0 <= j && j < ids.length; (\forall int i; "
                 r"0 <= i && i < j; ids[i] != ids[j]))",
                 RESULT_IS_FIRST_DUPLICATE,
             ])),
        Case("hw9-correct-redundant-bound", "PASS", "equivalent",
             "增加 0<=j 这个冗余边界；原条件 j<ids.length 且 i<j 已蕴含它。",
             _source(reference, [
                 r"\result == -1 <==> (\forall int i, j; "
                 r"0 <= i && 0 <= j && i < j && j < ids.length; "
                 r"ids[i] != ids[j])",
                 RESULT_IS_FIRST_DUPLICATE,
             ])),
        Case("hw9-correct-reordered-range", "PASS", "equivalent",
             "调整量词范围条件的书写顺序，边界与比较关系未变。", _source(reference, [
                 r"\result == -1 <==> (\forall int i, j; "
                 r"j < ids.length && i < j && 0 <= i && 0 <= j; "
                 r"ids[i] != ids[j])",
                 RESULT_IS_FIRST_DUPLICATE,
             ])),
        Case("hw9-correct-count-prior", "PASS", "equivalent",
             "结果位置是重复项，当且仅当此前相同值的数量大于零。", _source(reference, [
                 rf"\result == -1 <==> {NO_DUPLICATES}",
                 r"\result != -1 ==> 0 <= \result && \result < ids.length "
                 r"&& (\num_of int i; 0 <= i && i < \result; "
                 r"ids[i] == ids[\result]) > 0 && " + PREFIX_UNIQUE,
             ])),
        Case("hw9-correct-count-prefix", "PASS", "equivalent",
             "结果之前不存在重复，等价于之前相等元素对的数量为零。", _source(reference, [
                 rf"\result == -1 <==> {NO_DUPLICATES}",
                 r"\result != -1 ==> 0 <= \result && \result < ids.length "
                 r"&& " + DUPLICATE_AT_RESULT
                 + r" && (\num_of int i, j; 0 <= i && i < j && j < \result;"
                 r" ids[i] == ids[j]) == 0",
             ])),
        Case("hw9-correct-split-ensures", "PASS", "equivalent",
             "把首条 iff 拆成两条 ensures；JML 对 ensures 取合取。", _source(reference, [
                 rf"\result == -1 ==> {NO_DUPLICATES}",
                 rf"{NO_DUPLICATES} ==> \result == -1",
                 RESULT_IS_FIRST_DUPLICATE,
             ])),
        Case("hw9-correct-result-guard-inequality", "PASS", "equivalent",
             "整数结果不等于 -1，等价于小于 -1 或大于 -1 的析取。",
             _source(reference, [
                 rf"\result == -1 <==> {NO_DUPLICATES}",
                 r"(\result < -1 || \result > -1) ==> 0 <= \result && \result < ids.length "
                 r"&& " + DUPLICATE_AT_RESULT + r" && " + PREFIX_UNIQUE,
             ])),
        Case("hw9-correct-result-bound-minus-one", "PASS", "equivalent",
             "非负数组长度下，result<length 等价于 result<=length-1。", _source(reference, [
                 rf"\result == -1 <==> {NO_DUPLICATES}",
                 r"\result != -1 ==> 0 <= \result && \result <= ids.length - 1 "
                 r"&& " + DUPLICATE_AT_RESULT + r" && " + PREFIX_UNIQUE,
             ])),
    ]

    semantic = [
        Case("hw9-wrong-sentinel-zero", "FAIL", "semantic",
             "反例 ids=[9]：正确结果是 -1；该规约却要求无重复时结果为 0。",
             _source(reference, [r"\result == 0 <==> " + NO_DUPLICATES,
                                 RESULT_IS_FIRST_DUPLICATE])),
        Case("hw9-wrong-sentinel-minus-two", "FAIL", "semantic",
             "反例 ids=[9]：正确结果是 -1；该规约把无重复哨兵改成 -2。",
             _source(reference, [r"\result == -2 <==> " + NO_DUPLICATES,
                                 RESULT_IS_FIRST_DUPLICATE])),
        Case("hw9-wrong-sentinel-requires-duplicate", "FAIL", "semantic",
             "反例 ids=[6]：正确结果 -1 表示无重复；该反向条件却要求数组有重复。",
             _source(reference, [rf"\result == -1 ==> !{NO_DUPLICATES}",
                                 RESULT_IS_FIRST_DUPLICATE])),
        Case("hw9-wrong-self-counted", "FAIL", "semantic",
             "反例 ids=[5,5]：result=0 会把自身当作更早的相同元素，错误地通过。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 r"\result != -1 ==> 0 <= \result && \result < ids.length "
                                 r"&& (\exists int i; 0 <= i && i <= \result; "
                                 r"ids[i] == ids[\result]) && " + PREFIX_UNIQUE])),
        Case("hw9-wrong-adjacent-only", "FAIL", "semantic",
             "反例 ids=[1,2,1]：它只查相邻项，会把非相邻重复漏掉并错误返回 -1。",
             _source(reference, [r"\result == -1 <==> (\forall int i, j; "
                                 r"0 <= i && i < ids.length && 0 <= j "
                                 r"&& j < ids.length && j == i + 1; "
                                 r"ids[i] != ids[j])",
                                 RESULT_IS_FIRST_DUPLICATE])),
        Case("hw9-wrong-skip-first-index", "FAIL", "semantic",
             "反例 ids=[4,9,4]：只从 i=1 开始比较会漏掉位置 0 与 2 的重复。",
             _source(reference, [r"\result == -1 <==> (\forall int i, j; "
                                 r"1 <= i && i < j && j < ids.length; ids[i] != ids[j])",
                                 RESULT_IS_FIRST_DUPLICATE])),
        Case("hw9-wrong-skip-last-index", "FAIL", "semantic",
             "反例 ids=[1,2,2]：把 j<length 改成 j<length-1 后，最后一项不参与比较。",
             _source(reference, [r"\result == -1 <==> (\forall int i, j; "
                                 r"0 <= i && i < j && j < ids.length - 1; "
                                 r"ids[i] != ids[j])", RESULT_IS_FIRST_DUPLICATE])),
        Case("hw9-wrong-diagonal-pairs", "FAIL", "semantic",
             "反例 ids=[7]：允许 i=j 会比较元素与自身，正确的 -1 也无法通过无重复判断。",
             _source(reference, [r"\result == -1 <==> (\forall int i, j; "
                                 r"0 <= i && i <= j && j < ids.length; ids[i] != ids[j])",
                                 RESULT_IS_FIRST_DUPLICATE])),
        Case("hw9-wrong-equal-pairs-as-unique", "FAIL", "semantic",
             "反例 ids=[1,2]：把不等改成相等后，全称式为假，反而不允许正确结果 -1。",
             _source(reference, [r"\result == -1 <==> (\forall int i, j; "
                                 r"0 <= i && i < j && j < ids.length; ids[i] == ids[j])",
                                 RESULT_IS_FIRST_DUPLICATE])),
        Case("hw9-wrong-exists-unequal-pair", "FAIL", "semantic",
             "反例 ids=[1,2,1]：存在不等元素对会成立，错误地允许把含重复数组判为无重复。",
             _source(reference, [r"\result == -1 <==> (\exists int i, j; "
                                 r"0 <= i && i < j && j < ids.length; ids[i] != ids[j])",
                                 RESULT_IS_FIRST_DUPLICATE])),
        Case("hw9-wrong-count-positive", "FAIL", "semantic",
             "反例 ids=[1]：相等元素对数量为 0，却被规约当成 result 不等于 -1。",
             _source(reference, [r"\result == -1 <==> (\num_of int i, j; "
                                 r"0 <= i && i < j && j < ids.length; "
                                 r"ids[i] == ids[j]) > 0", RESULT_IS_FIRST_DUPLICATE])),
        Case("hw9-wrong-repeat-first-value-only", "FAIL", "semantic",
             "反例 ids=[1,2,2]：只与 ids[0] 比较，会漏掉后两项之间的重复。",
             _source(reference, [r"\result == -1 <==> (\forall int j; "
                                 r"1 <= j && j < ids.length; ids[0] != ids[j])",
                                 RESULT_IS_FIRST_DUPLICATE])),
        Case("hw9-wrong-omit-prefix-uniqueness", "FAIL", "semantic",
             "反例 ids=[0,1,0,1]：该规约接受 result=3，虽有更早的重复下标 2。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 r"\result != -1 ==> 0 <= \result && \result < ids.length "
                                 r"&& " + DUPLICATE_AT_RESULT])),
        Case("hw9-wrong-prefix-adjacent-only", "FAIL", "semantic",
             "反例 ids=[1,2,1,3,2]：result=4 有更早重复 2，但前缀相邻项都不同，故被误收。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 r"\result != -1 ==> 0 <= \result && \result < ids.length "
                                 r"&& " + DUPLICATE_AT_RESULT
                                 + r" && (\forall int i, j; 0 <= i && i < \result "
                                 r"&& 0 <= j && j < \result && j == i + 1; "
                                 r"ids[i] != ids[j])"])),
        Case("hw9-wrong-prefix-includes-result", "FAIL", "semantic",
             "反例 ids=[1,1]：把前缀上界改成 j<=result，会把首次重复对自身纳入唯一性检查。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 r"\result != -1 ==> 0 <= \result && \result < ids.length "
                                 r"&& " + DUPLICATE_AT_RESULT
                                 + r" && (\forall int i, j; 0 <= i && i < j "
                                 r"&& j <= \result; ids[i] != ids[j])"])),
        Case("hw9-wrong-prefix-checks-after-result", "FAIL", "semantic",
             "反例 ids=[5,5,6,6]：正确结果 1；检查到整个数组会因后面的重复对而拒绝它。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 r"\result != -1 ==> 0 <= \result && \result < ids.length "
                                 r"&& " + DUPLICATE_AT_RESULT
                                 + r" && (\forall int i, j; 0 <= i && i < j "
                                 r"&& j < ids.length; ids[i] != ids[j])"])),
        Case("hw9-wrong-result-must-be-after-one", "FAIL", "semantic",
             "反例 ids=[8,8]：正确重复下标是 1；附加 result>1 会排除这个合法答案。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 r"\result != -1 ==> 1 < \result && \result < ids.length "
                                 r"&& " + DUPLICATE_AT_RESULT + r" && " + PREFIX_UNIQUE])),
        Case("hw9-wrong-equality-with-result-reversed", "FAIL", "semantic",
             "反例 ids=[1,1]：正确 result=1；改成查找更早的不等值会找不到，拒绝合法答案。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 r"\result != -1 ==> 0 <= \result && \result < ids.length "
                                 r"&& (\exists int i; 0 <= i && i < \result; "
                                 r"ids[i] != ids[\result]) && " + PREFIX_UNIQUE])),
        Case("hw9-wrong-compare-to-zero-index", "FAIL", "semantic",
             "反例 ids=[1,2,3,1]：正确 result=3；该规约却接受 result=1，因为它只检查 ids[i]==ids[0]。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 r"\result != -1 ==> 0 <= \result && \result < ids.length "
                                 r"&& (\exists int i; 0 <= i && i < \result; "
                                 r"ids[i] == ids[0]) && " + PREFIX_UNIQUE])),
        Case("hw9-wrong-prefix-must-all-match", "FAIL", "semantic",
             "反例 ids=[1,2,1]：正确 result=2；要求此前每项都等于重复值，错误地排除了它。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 r"\result != -1 ==> 0 <= \result && \result < ids.length "
                                 r"&& " + DUPLICATE_AT_RESULT
                                 + r" && (\forall int i; 0 <= i && i < \result; "
                                 r"ids[i] == ids[\result])"])),
        Case("hw9-wrong-miss-previous-position", "FAIL", "semantic",
             "反例 ids=[1,1]：把 i<result 改成 i<result-1，漏掉紧邻的前一次出现。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 r"\result != -1 ==> 0 <= \result && \result < ids.length "
                                 r"&& (\exists int i; 0 <= i && i < \result - 1; "
                                 r"ids[i] == ids[\result]) && " + PREFIX_UNIQUE])),
        Case("hw9-wrong-duplicate-index-is-length", "FAIL", "semantic",
             "反例 ids=[1,1]：该规约还接受越界结果 result=length=2，官方要求 result=1。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 r"\result != -1 ==> (\result == ids.length || "
                                 r"(0 <= \result && \result < ids.length && "
                                 + DUPLICATE_AT_RESULT + r" && " + PREFIX_UNIQUE + "))"])),
        Case("hw9-wrong-requires-nonempty", "FAIL", "semantic",
             "反例 ids=[]：官方合同接受空数组并返回 -1；额外要求 length>0 会拒绝输入。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 RESULT_IS_FIRST_DUPLICATE],
                     requires="ids != null && ids.length > 0;")),
        Case("hw9-wrong-requires-length-two", "FAIL", "semantic",
             "反例 ids=[7]：官方合同接受单元素数组并返回 -1；length>=2 过度限制输入。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 RESULT_IS_FIRST_DUPLICATE],
                     requires="ids != null && ids.length >= 2;")),
        Case("hw9-wrong-requires-unique", "FAIL", "semantic",
             "反例 ids=[7,7]：前置条件误要求输入已无重复，使合法重复输入不再适用。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 RESULT_IS_FIRST_DUPLICATE],
                     requires=rf"ids != null && {NO_DUPLICATES};")),
        Case("hw9-wrong-frame-array-writable", "FAIL", "semantic",
             "反例：assignable ids[*] 允许把 ids[0] 改写；官方 assignable \\nothing 禁止任何写入。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 RESULT_IS_FIRST_DUPLICATE],
                     assignable="ids[*];")),
        Case("hw9-wrong-frame-everything", "FAIL", "semantic",
             "反例：assignable \\everything 允许修改输入数组及其他状态，强于官方的只读保证。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 RESULT_IS_FIRST_DUPLICATE],
                     assignable=r"\everything;")),
        Case("hw9-wrong-frame-omitted", "FAIL", "semantic",
             "反例：删除 assignable 会失去只读保证，默认可写范围不等于官方的 \\nothing。",
             _source(reference, [rf"\result == -1 <==> {NO_DUPLICATES}",
                                 RESULT_IS_FIRST_DUPLICATE], assignable="")),
    ]

    malformed = [
        Case("hw9-syntax-unsupported-sum", "FAIL", "syntax",
             "使用当前 JML 子集不支持的 \\sum 量词，应报告格式或符号错误。",
             _source(reference, [r"\result == -1 <==> (\sum int i; "
                                 r"0 <= i && i < ids.length; ids[i]) == 0",
                                 RESULT_IS_FIRST_DUPLICATE]), FORMAT),
        Case("hw9-syntax-unbounded-quantifier", "FAIL", "syntax",
             "量词变量没有有限边界，无法安全枚举，属于不受支持的输入。",
             _source(reference, [r"\result == -1 <==> (\forall int i; true; "
                                 r"i >= 0)", RESULT_IS_FIRST_DUPLICATE]), FORMAT),
        Case("hw9-syntax-wrong-quantifier-type", "FAIL", "syntax",
             "量词绑定变量写成 boolean；当前子集仅支持 int 绑定变量。",
             _source(reference, [r"\result == -1 <==> (\forall boolean i; "
                                 r"true; true)", RESULT_IS_FIRST_DUPLICATE]), FORMAT),
    ]

    return equivalent + semantic + malformed
