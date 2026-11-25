"""Deterministic source format, size, and workload probes for all three methods."""

import re

from case import Case

FORMAT = "JML_FORMAT_OR_SYMBOL"
MIB = 1024 * 1024


def with_first_requires(reference: str, expression: str) -> str:
    return re.sub(r"(?m)^(\s*@ requires )", lambda match: (
        match.group(1) + expression + ";\n      @ requires "
    ), reference, count=1)


def many_requires(reference: str, count: int) -> str:
    first = reference.index("@ requires ")
    return reference[:first] + ("@ requires true;\n      " * count) + reference[first:]


def padded(reference: str, size: int) -> str:
    return "/*" + "x" * (size - len(reference.encode("utf-8")) - 5) + "*/\n" + reference


def cases(reference: str, method: str) -> list[Case]:
    target = re.search(rf"public abstract [\w\[\]]+ {method}\([^;]+;", reference).group()
    probes = [
        Case("stress-flat-valid", "PASS", "resource", "在 token 限额内的 1000 项平坦合取仍等价",
             with_first_requires(reference, " && ".join(["true"] * 1000))),
        Case("stress-token-limit", "FAIL", "resource", "2200 项合取超过单表达式 token 预算",
             with_first_requires(reference, " && ".join(["true"] * 2200)), FORMAT),
        Case("stress-many-clauses", "PASS", "resource", "8000 条恒真 requires，全文件和单条表达式均在限额内",
             many_requires(reference, 8000)),
        Case("stress-depth-limit", "FAIL", "resource", "90 层括号超过语法深度限制",
             with_first_requires(reference, "(" * 90 + "true" + ")" * 90), FORMAT),
        Case("stress-quantifier-budget", "FAIL", "resource", "合法有界量词需要遍历超大范围，应由运算预算终止",
             with_first_requires(reference, r"(\forall int q; 0 <= q && q < 2147483647; q >= 0)"), FORMAT),
        Case("stress-maximum-file", "PASS", "resource", "恰好 1 MiB 的合法提交，额外体积来自普通注释",
             padded(reference, MIB)),
        Case("stress-file-too-large", "FAIL", "resource", "只超过 1 MiB 一字节，应返回明确定义的学生失败",
             padded(reference, MIB + 1), FORMAT),
        Case("syntax-missing-contract", "FAIL", "syntax", "方法签名存在但没有 JML 作答",
             f"public abstract class JML {{\n    {target}\n}}\n", FORMAT),
        Case("syntax-duplicate-method", "FAIL", "syntax", "同一目标签名出现两次，不能合并或随意选择",
             reference.rstrip().removesuffix("}") + f"\n    {target}\n}}\n", FORMAT),
        Case("syntax-different-method", "FAIL", "syntax", "保留合同但把模板方法名改错",
             reference.replace(f" {method}(", f" {method}Copy(", 1), FORMAT),
        Case("syntax-unclosed-jml-clause", "FAIL", "syntax", "删掉第一条 requires 的分号，下一条被吞入",
             re.sub(r"(\brequires\b[^;]+);", r"\1", reference, count=1), FORMAT),
    ]
    if method == "firstDuplicateIndex":
        probes.extend([
            Case("coverage-truncates-long-input", "FAIL", "semantic",
                 "额外限制数组长度至 7。反例为 [0,1,2,3,4,5,6,7]，应可调用且返回 -1。",
                 with_first_requires(reference, "ids == null || ids.length < 8")),
            Case("coverage-illegal-negative-on-duplicate", "FAIL", "semantic",
                 "把非 -1 的守卫写成大于 -1。反例为 [7,7] 和返回 -2，该规约错误允许 -2。",
                 reference.replace(r"\result != -1 ==>", r"\result > -1 ==>", 1)),
            Case("equivalent-integer-bound-addition", "PASS", "equivalent",
                 "量词范围内整数 i < j 等价于 i+1 <= j。",
                 reference.replace("i < j && j < ids.length", "i + 1 <= j && j < ids.length", 1)),
        ])
    elif method == "reserveSeats":
        probes.append(Case(
            "coverage-limits-success-to-two-seats", "FAIL", "semantic",
            "把成功预订限制为每次最多两座。反例为 [false,false,false] 上 start=0,count=3，应成功。",
            reference.replace(
                r"ensures \result && occupied == \old(occupied);",
                r"ensures \result && occupied == \old(occupied) && count <= 2;",
                1,
            ),
        ))
    else:
        probes.extend([
            Case("coverage-limits-all-occupied", "FAIL", "semantic",
                 "把全占用分支限制在长度小于 9。反例为 9 个 true，仍应返回空数组。",
                 with_first_requires(reference, "occupied == null || occupied.length < 9")),
            Case("equivalent-bound-by-end", "PASS", "equivalent",
                 "候选空座区间用 start+length <= occupied.length 代替等价的减法边界。",
                 reference.replace("length <= occupied.length - start",
                                   "start + length <= occupied.length", 1)),
        ])
    return probes
