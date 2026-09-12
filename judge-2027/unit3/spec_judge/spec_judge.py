"""LEGACY regression prototype; do not use this module for course grading.

The supported entrypoint is ``semantic_check.py --suite ...``.  This older
checker remains temporarily because ``test_spec_judge.py`` preserves its pilot
behavior.  It evaluates JML fragments only and never invokes student code.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class SpecError(Exception):
    """Raised when a submitted contract is outside the supported subset."""


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    offset: int


TOKEN_PATTERN = re.compile(
    r"\s*(?:(?P<JML>\\(?:old|forall|exists))|"
    r"(?P<OP>&&|\|\||==|!=|<=|>=)|"
    r"(?P<PUNC>[()!,;<>])|"
    r"(?P<INT>\d+)|"
    r"(?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)|"
    r"(?P<BAD>.))"
)


def tokenize(text: str) -> list[Token]:
    result: list[Token] = []
    position = 0
    while position < len(text):
        match = TOKEN_PATTERN.match(text, position)
        if match is None:  # Defensive: the pattern always matches one char.
            raise SpecError(f"无法识别的位置：{position}")
        position = match.end()
        kind = match.lastgroup
        assert kind is not None
        value = match.group(kind)
        if kind == "BAD":
            raise SpecError(f"不支持的字符 {value!r}（位置 {match.start(kind)}）")
        if kind == "OP" or kind == "PUNC":
            result.append(Token(value, value, match.start(kind)))
        elif kind == "JML":
            result.append(Token(value, value, match.start(kind)))
        else:
            result.append(Token(kind, value, match.start(kind)))
    result.append(Token("EOF", "", len(text)))
    return result


class Expr:
    pass


@dataclasses.dataclass(frozen=True)
class Literal(Expr):
    value: Any


@dataclasses.dataclass(frozen=True)
class Variable(Expr):
    name: str


@dataclasses.dataclass(frozen=True)
class Call(Expr):
    name: str
    args: tuple[Expr, ...]


@dataclasses.dataclass(frozen=True)
class Unary(Expr):
    operator: str
    operand: Expr


@dataclasses.dataclass(frozen=True)
class Binary(Expr):
    operator: str
    left: Expr
    right: Expr


@dataclasses.dataclass(frozen=True)
class Old(Expr):
    expression: Expr


@dataclasses.dataclass(frozen=True)
class Quantifier(Expr):
    kind: str
    variable: str
    range_expression: Expr
    predicate: Expr


class Parser:
    """Recursive-descent parser for the pilot's expression language."""

    def __init__(self, text: str):
        self.tokens = tokenize(text)
        self.index = 0

    def current(self) -> Token:
        return self.tokens[self.index]

    def accept(self, *kinds: str) -> Token | None:
        if self.current().kind in kinds:
            token = self.current()
            self.index += 1
            return token
        return None

    def expect(self, *kinds: str) -> Token:
        token = self.accept(*kinds)
        if token is None:
            wanted = " 或 ".join(kinds)
            current = self.current()
            raise SpecError(
                f"期望 {wanted}，但在位置 {current.offset} 得到 {current.text!r}"
            )
        return token

    def parse(self) -> Expr:
        expression = self.parse_or()
        self.expect("EOF")
        return expression

    def parse_or(self) -> Expr:
        expression = self.parse_and()
        while self.accept("||"):
            expression = Binary("||", expression, self.parse_and())
        return expression

    def parse_and(self) -> Expr:
        expression = self.parse_equality()
        while self.accept("&&"):
            expression = Binary("&&", expression, self.parse_equality())
        return expression

    def parse_equality(self) -> Expr:
        expression = self.parse_relational()
        while self.current().kind in {"==", "!="}:
            operator = self.current().kind
            self.index += 1
            expression = Binary(operator, expression, self.parse_relational())
        return expression

    def parse_relational(self) -> Expr:
        expression = self.parse_unary()
        while self.current().kind in {"<", "<=", ">", ">="}:
            operator = self.current().kind
            self.index += 1
            expression = Binary(operator, expression, self.parse_unary())
        return expression

    def parse_unary(self) -> Expr:
        if self.accept("!"):
            return Unary("!", self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        token = self.current()
        if self.accept("INT"):
            return Literal(int(token.text))
        if self.accept("IDENT"):
            if token.text == "true":
                return Literal(True)
            if token.text == "false":
                return Literal(False)
            if self.accept("("):
                args: list[Expr] = []
                if not self.accept(")"):
                    while True:
                        args.append(self.parse_or())
                        if self.accept(")"):
                            break
                        self.expect(",")
                return Call(token.text, tuple(args))
            return Variable(token.text)
        if self.accept("("):
            expression = self.parse_or()
            self.expect(")")
            return expression
        if self.accept("\\old"):
            self.expect("(")
            expression = self.parse_or()
            self.expect(")")
            return Old(expression)
        if token.kind in {"\\forall", "\\exists"}:
            self.index += 1
            self.expect("IDENT")  # The pilot accepts only the spelling "int".
            type_token = self.tokens[self.index - 1]
            if type_token.text != "int":
                raise SpecError("量词变量类型仅支持 int")
            variable = self.expect("IDENT").text
            self.expect(";")
            range_expression = self.parse_or()
            self.expect(";")
            predicate = self.parse_or()
            return Quantifier(token.kind, variable, range_expression, predicate)
        raise SpecError(f"无法在位置 {token.offset} 解析 {token.text!r}")


@dataclasses.dataclass
class State:
    users: set[int]
    following: dict[int, set[int]]
    followers: dict[int, set[int]]
    received_videos: dict[int, set[int]]

    def copy(self) -> "State":
        return copy.deepcopy(self)

    def relation(self, name: str, user_id: int) -> set[int]:
        if user_id not in self.users:
            return set()
        table = {
            "following": self.following,
            "followers": self.followers,
            "receivedVideos": self.received_videos,
        }[name]
        return set(table.get(user_id, set()))


@dataclasses.dataclass(frozen=True)
class Context:
    pre: State
    post: State
    arguments: dict[str, int]
    current_state: State

    def using_pre_state(self) -> "Context":
        return dataclasses.replace(self, current_state=self.pre)


ALLOWED_FUNCTIONS = {
    "userIds",
    "following",
    "followers",
    "receivedVideos",
    "contains",
    "singleton",
    "union",
}


def evaluate(expression: Expr, context: Context, variables: dict[str, Any] | None = None) -> Any:
    variables = {} if variables is None else variables
    if isinstance(expression, Literal):
        return expression.value
    if isinstance(expression, Variable):
        if expression.name in variables:
            return variables[expression.name]
        if expression.name in context.arguments:
            return context.arguments[expression.name]
        raise SpecError(f"未定义的变量：{expression.name}")
    if isinstance(expression, Old):
        return evaluate(expression.expression, context.using_pre_state(), variables)
    if isinstance(expression, Unary):
        value = evaluate(expression.operand, context, variables)
        if expression.operator == "!":
            return not bool(value)
        raise SpecError(f"不支持的一元运算：{expression.operator}")
    if isinstance(expression, Binary):
        if expression.operator == "&&":
            return bool(evaluate(expression.left, context, variables)) and bool(
                evaluate(expression.right, context, variables)
            )
        if expression.operator == "||":
            return bool(evaluate(expression.left, context, variables)) or bool(
                evaluate(expression.right, context, variables)
            )
        left = evaluate(expression.left, context, variables)
        right = evaluate(expression.right, context, variables)
        operators = {
            "==": lambda: left == right,
            "!=": lambda: left != right,
            "<": lambda: left < right,
            "<=": lambda: left <= right,
            ">": lambda: left > right,
            ">=": lambda: left >= right,
        }
        return operators[expression.operator]()
    if isinstance(expression, Quantifier):
        # Quantification is deliberately finite.  Its range still determines
        # truth, but the candidate values are all user ids observable here.
        domain = sorted(context.pre.users | context.post.users | set(context.arguments.values()))
        results: list[bool] = []
        for value in domain:
            scoped = dict(variables)
            scoped[expression.variable] = value
            if bool(evaluate(expression.range_expression, context, scoped)):
                results.append(bool(evaluate(expression.predicate, context, scoped)))
        return all(results) if expression.kind == "\\forall" else any(results)
    if isinstance(expression, Call):
        if expression.name not in ALLOWED_FUNCTIONS:
            raise SpecError(f"不允许调用函数：{expression.name}")
        args = [evaluate(argument, context, variables) for argument in expression.args]
        state = context.current_state
        if expression.name == "userIds" and not args:
            return set(state.users)
        if expression.name in {"following", "followers", "receivedVideos"} and len(args) == 1:
            return state.relation(expression.name, int(args[0]))
        if expression.name == "contains" and len(args) == 2:
            return args[1] in args[0]
        if expression.name == "singleton" and len(args) == 1:
            return {args[0]}
        if expression.name == "union" and len(args) == 2:
            return set(args[0]) | set(args[1])
        raise SpecError(f"函数 {expression.name} 的参数数量不正确")
    raise SpecError(f"未知 AST 节点：{type(expression).__name__}")


@dataclasses.dataclass(frozen=True)
class Location:
    relation: str
    user_id: int

    def label(self) -> str:
        return f"{self.relation}({self.user_id})"


@dataclasses.dataclass
class Contract:
    ensures: list[Expr]
    assignable: list[Call]

    @classmethod
    def parse(cls, source: str) -> "Contract":
        ensures: list[Expr] = []
        assignable: list[Call] = []
        for line_number, clause, body in extract_student_clauses(source):
            try:
                if clause == "ensures":
                    ensures.append(Parser(body).parse())
                else:
                    assignable.extend(parse_assignable(body))
            except SpecError as error:
                raise SpecError(f"第 {line_number} 行：{error}") from error
        if not ensures:
            raise SpecError("至少需要一个 ensures 子句")
        if not assignable:
            raise SpecError("至少需要一个 assignable 子句")
        return cls(ensures=ensures, assignable=assignable)

    def ensures_hold(self, context: Context) -> bool:
        return all(bool(evaluate(expression, context)) for expression in self.ensures)

    def allowed_locations(self, context: Context) -> set[Location]:
        result: set[Location] = set()
        for call in self.assignable:
            if call.name not in {"following", "followers", "receivedVideos"} or len(call.args) != 1:
                raise SpecError("assignable 仅支持 following(id)、followers(id)、receivedVideos(id)")
            user_id = evaluate(call.args[0], context)
            if not isinstance(user_id, int):
                raise SpecError("assignable 的下标必须是 int")
            result.add(Location(call.name, user_id))
        return result

    def assignable_holds(self, context: Context) -> bool:
        return changed_locations(context.pre, context.post) <= self.allowed_locations(context)


def parse_assignable(body: str) -> list[Call]:
    pieces: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(body):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            pieces.append(body[start:index].strip())
            start = index + 1
    pieces.append(body[start:].strip())
    calls: list[Call] = []
    for piece in pieces:
        expression = Parser(piece).parse()
        if not isinstance(expression, Call):
            raise SpecError("assignable 中每一项必须是逻辑状态位置")
        calls.append(expression)
    return calls


def extract_student_clauses(source: str) -> list[tuple[int, str, str]]:
    """Read clauses from the body of a standard ``/*@ ... @*/`` JML comment.

    A clause may span multiple JML-comment lines.  The prototype intentionally
    reads only the two student-owned clause kinds; normal/exceptional behavior
    headers and course-locked ``requires`` lines are left for the official
    template checker added in a later iteration.
    """

    clauses: list[tuple[int, str, str]] = []
    pending_kind: str | None = None
    pending_line = 0
    pending_parts: list[str] = []
    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        line = raw_line.strip()
        if line.startswith("@"):
            line = line[1:].lstrip()
        if not line or line.startswith("//"):
            continue
        header = re.match(r"^(ensures|assignable)\b\s*(.*)$", line)
        if header is not None:
            if pending_kind is not None:
                raise SpecError(f"第 {line_number} 行开始了新子句，但第 {pending_line} 行子句尚未结束")
            pending_kind = header.group(1)
            pending_line = line_number
            pending_parts = [header.group(2)]
        elif pending_kind is not None:
            pending_parts.append(line)
        else:
            # JML behavior headers and locked requires clauses are not student
            # input in this first pilot, so the contract evaluator ignores them.
            continue
        if pending_kind is not None and line.endswith(";"):
            body = " ".join(pending_parts).strip()[:-1].strip()
            if not body:
                raise SpecError(f"第 {pending_line} 行的 {pending_kind} 子句为空")
            clauses.append((pending_line, pending_kind, body))
            pending_kind = None
            pending_parts = []
    if pending_kind is not None:
        raise SpecError(f"第 {pending_line} 行的 {pending_kind} 子句缺少结尾分号")
    return clauses


def extract_jml_block(java_source: str, method_name: str) -> str:
    """Return the JML annotation immediately preceding ``method_name``.

    This is deliberately a source extractor, not a Java parser.  HW9's public
    template keeps its method-level JML comment directly before the method
    declaration, which makes that convention sufficient and transparent.
    """

    blocks = list(re.finditer(r"/\*@(?P<body>.*?)@\*/", java_source, re.DOTALL))
    method_pattern = re.compile(r"\b" + re.escape(method_name) + r"\s*\(")
    for index, block in enumerate(blocks):
        next_start = blocks[index + 1].start() if index + 1 < len(blocks) else len(java_source)
        declaration = java_source[block.end():next_start]
        if method_pattern.search(declaration):
            return block.group("body")
    raise SpecError(f"未找到紧邻方法 {method_name} 的 JML 注释块")


def changed_locations(pre: State, post: State) -> set[Location]:
    changed: set[Location] = set()
    all_users = pre.users | post.users
    for user_id in all_users:
        for relation in ("following", "followers", "receivedVideos"):
            if pre.relation(relation, user_id) != post.relation(relation, user_id):
                changed.add(Location(relation, user_id))
    return changed


@dataclasses.dataclass(frozen=True)
class Case:
    name: str
    category: str
    pre: State
    post: State
    expected_ensures: bool
    expected_assignable: bool


def base_state() -> State:
    return State(
        users={1, 2, 3},
        following={1: set(), 2: set(), 3: {1}},
        followers={1: {3}, 2: set(), 3: set()},
        received_videos={1: {101}, 2: {101}, 3: set()},
    )


def follow_user_cases() -> list[Case]:
    """Compatibility aggregate of the two public suites."""
    return weak_follow_user_cases() + mid_follow_user_cases()


def _follow_user_case_pool() -> dict[str, Case]:
    """One-fault state transitions used by the public diagnostic suites.

    Cases are deliberately organised by *diagnostic strength*, not by grading
    weight.  ``weak`` establishes the basic two-sided transition; ``mid``
    checks precision and frame reasoning.  A production judge adds a separate
    hidden strong suite and must never use this public pool as its sole oracle.
    """
    pre = base_state()

    correct = pre.copy()
    correct.following[1].add(2)
    correct.followers[2].add(1)

    only_following = pre.copy()
    only_following.following[1].add(2)

    only_followers = pre.copy()
    only_followers.followers[2].add(1)

    extra_follow = correct.copy()
    extra_follow.following[1].add(3)

    unrelated_user = correct.copy()
    unrelated_user.following[3].add(2)

    unrelated_video_state = correct.copy()
    unrelated_video_state.received_videos[3].add(101)

    return {
        "correct": Case("正确状态转移", "正常转移", pre, correct, True, True),
        "missing_followers": Case(
            "遗漏 followers 更新", "双向关注关系", pre, only_following, False, True
        ),
        "missing_following": Case(
            "遗漏 following 更新", "双向关注关系", pre, only_followers, False, True
        ),
        "extra_follow": Case("额外关注关系", "精确状态更新", pre, extra_follow, False, True),
        "unrelated_user": Case(
            "修改无关用户", "无关用户状态保持", pre, unrelated_user, False, False
        ),
        "unrelated_video": Case(
            "修改无关视频状态", "修改范围", pre, unrelated_video_state, False, False
        ),
    }


def weak_follow_user_cases() -> list[Case]:
    """Public baseline: success transition and both observable directions."""
    pool = _follow_user_case_pool()
    return [pool["correct"], pool["missing_followers"], pool["missing_following"]]


def mid_follow_user_cases() -> list[Case]:
    """Public composition: exact update plus unrelated-state/frame checks."""
    pool = _follow_user_case_pool()
    return [pool["extra_follow"], pool["unrelated_user"], pool["unrelated_video"]]


@dataclasses.dataclass(frozen=True)
class CaseResult:
    case: Case
    ensures_actual: bool
    assignable_actual: bool
    passed: bool


def check_contract(contract: Contract, cases: Iterable[Case]) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        context = Context(
            pre=case.pre,
            post=case.post,
            arguments={"id1": 1, "id2": 2},
            current_state=case.post,
        )
        ensures_actual = contract.ensures_hold(context)
        assignable_actual = contract.assignable_holds(context)
        passed = (
            ensures_actual == case.expected_ensures
            and assignable_actual == case.expected_assignable
        )
        results.append(CaseResult(case, ensures_actual, assignable_actual, passed))
    return results


def report(results: list[CaseResult]) -> str:
    failed_categories: dict[str, list[str]] = {}
    for result in results:
        if not result.passed:
            failed_categories.setdefault(result.case.category, []).append(result.case.name)
    if not failed_categories:
        return "规格自测通过：所有公开案例均符合预期。"
    lines = ["规格自测未通过："]
    for category, names in failed_categories.items():
        lines.append(f"- {category}：{len(names)} 个公开案例未通过")
    return "\n".join(lines)


def main() -> int:
    # The course judge consumes UTF-8.  This also prevents Windows consoles
    # configured to a legacy code page from producing mojibake in feedback.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Unit 3 HW9 受限 JML 规格自测原型")
    parser.add_argument("java_source", type=Path, help="包含 JML 方法注释的 Java 接口文件")
    parser.add_argument("--method", default="followUser", help="要检查的 Java 方法名，默认 followUser")
    parser.add_argument(
        "--suite",
        choices=("weak", "mid", "all"),
        default="weak",
        help="公开诊断套件；默认 weak。正式评分另用不公开的 strong 套件。",
    )
    parser.add_argument("--verbose", action="store_true", help="展示公开案例名称，不展示状态快照")
    args = parser.parse_args()
    try:
        source = args.java_source.read_text(encoding="utf-8")
        contract = Contract.parse(extract_jml_block(source, args.method))
        suites = {
            "weak": weak_follow_user_cases(),
            "mid": mid_follow_user_cases(),
            "all": follow_user_cases(),
        }
        results = check_contract(contract, suites[args.suite])
    except (OSError, SpecError) as error:
        print(f"规格格式错误：{error}", file=sys.stderr)
        return 2
    print(report(results))
    if args.verbose:
        for result in results:
            state = "通过" if result.passed else "未通过"
            print(f"  {state}：{result.case.name}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
