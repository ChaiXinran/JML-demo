"""Domain-independent AST, parser, validation, and concrete evaluation."""

from __future__ import annotations

import dataclasses
import re
from typing import Any, Mapping

from .errors import SpecError
from .profile import EvaluationContext, EvaluationProfile, ProfileError


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    offset: int


TOKEN_RE = re.compile(
    r"\s*(?:(?P<JML>\\old)|(?P<OP>&&|\|\||==|!=|<=|>=)|"
    r"(?P<PUNC>[().,;!<>])|(?P<INT>\d+)|"
    r"(?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)|(?P<BAD>.))"
)


def tokenize(source: str) -> list[Token]:
    result: list[Token] = []
    position = 0
    while position < len(source):
        match = TOKEN_RE.match(source, position)
        if match is None:
            raise SpecError(f"无法识别的位置：{position}")
        position = match.end()
        kind = match.lastgroup
        assert kind is not None
        text = match.group(kind)
        if kind == "BAD":
            raise SpecError(f"不支持的字符 {text!r}（位置 {match.start(kind)}）")
        result.append(Token(kind if kind not in {"OP", "PUNC", "JML"} else text, text, match.start(kind)))
    result.append(Token("EOF", "", len(source)))
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


class ExpressionParser:
    def __init__(self, source: str):
        self.tokens = tokenize(source)
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
            current = self.current()
            raise SpecError(f"期望 {' 或 '.join(kinds)}，但在位置 {current.offset} 得到 {current.text!r}")
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
        if self.accept("\\old"):
            self.expect("(")
            expression = self.parse_or()
            self.expect(")")
            return Old(expression)
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        if self.accept("INT"):
            return Literal(int(self.tokens[self.index - 1].text))
        if self.accept("("):
            expression = self.parse_or()
            self.expect(")")
            return expression
        identifier = self.accept("IDENT")
        if identifier is None:
            token = self.current()
            raise SpecError(f"无法在位置 {token.offset} 解析 {token.text!r}")
        if identifier.text == "true":
            expression: Expr = Literal(True)
        elif identifier.text == "false":
            expression = Literal(False)
        elif self.accept("("):
            expression = Call(identifier.text, self.parse_arguments())
        else:
            expression = Variable(identifier.text)
        while self.accept("."):
            member = self.expect("IDENT")
            self.expect("(")
            expression = Call(member.text, (expression, *self.parse_arguments()))
        return expression

    def parse_arguments(self) -> tuple[Expr, ...]:
        arguments: list[Expr] = []
        if self.accept(")"):
            return tuple(arguments)
        while True:
            arguments.append(self.parse_or())
            if self.accept(")"):
                return tuple(arguments)
            self.expect(",")


def validate_calls(expression: Expr, profile: EvaluationProfile) -> None:
    if isinstance(expression, Call):
        if expression.name not in profile.allowed_calls:
            raise SpecError(f"不允许调用接口外函数：{expression.name}")
        for argument in expression.args:
            validate_calls(argument, profile)
    elif isinstance(expression, (Unary, Old)):
        validate_calls(expression.operand if isinstance(expression, Unary) else expression.expression, profile)
    elif isinstance(expression, Binary):
        validate_calls(expression.left, profile)
        validate_calls(expression.right, profile)


def infer_type(
    expression: Expr,
    profile: EvaluationProfile,
    variables: Mapping[str, str],
) -> str:
    """Statically type-check the supported expression subset."""
    if isinstance(expression, Literal):
        return "bool" if isinstance(expression.value, bool) else "int"
    if isinstance(expression, Variable):
        if expression.name not in variables:
            raise SpecError(f"未定义的变量：{expression.name}")
        return variables[expression.name]
    if isinstance(expression, Old):
        return infer_type(expression.expression, profile, variables)
    if isinstance(expression, Unary):
        operand = infer_type(expression.operand, profile, variables)
        if expression.operator != "!" or operand != "bool":
            raise SpecError(f"一元运算 {expression.operator} 不能用于 {operand}")
        return "bool"
    if isinstance(expression, Binary):
        left = infer_type(expression.left, profile, variables)
        right = infer_type(expression.right, profile, variables)
        if expression.operator in {"&&", "||"}:
            if left != "bool" or right != "bool":
                raise SpecError(f"逻辑运算 {expression.operator} 两侧必须是 bool")
            return "bool"
        if expression.operator in {"<", "<=", ">", ">="}:
            if left != "int" or right != "int":
                raise SpecError(f"比较运算 {expression.operator} 两侧必须是 int")
            return "bool"
        if expression.operator in {"==", "!="}:
            if left != right:
                raise SpecError(f"相等比较两侧类型不同：{left} 与 {right}")
            return "bool"
        raise SpecError(f"不支持的二元运算：{expression.operator}")
    if isinstance(expression, Call):
        argument_types = tuple(infer_type(item, profile, variables) for item in expression.args)
        for signature in profile.symbols.get(expression.name, ()):
            if signature.parameters == argument_types:
                return signature.returns
        rendered = ", ".join(argument_types)
        raise SpecError(f"函数 {expression.name} 不接受参数类型 ({rendered})")
    raise SpecError(f"未知表达式节点：{type(expression).__name__}")


def evaluate(expression: Expr, context: EvaluationContext, profile: EvaluationProfile) -> Any:
    if isinstance(expression, Literal):
        return expression.value
    if isinstance(expression, Variable):
        if expression.name in context.arguments:
            return context.arguments[expression.name]
        raise SpecError(f"未定义的变量：{expression.name}")
    if isinstance(expression, Old):
        return evaluate(expression.expression, context.pre_state(), profile)
    if isinstance(expression, Unary):
        return not bool(evaluate(expression.operand, context, profile))
    if isinstance(expression, Binary):
        if expression.operator == "&&":
            return bool(evaluate(expression.left, context, profile)) and bool(evaluate(expression.right, context, profile))
        if expression.operator == "||":
            return bool(evaluate(expression.left, context, profile)) or bool(evaluate(expression.right, context, profile))
        left = evaluate(expression.left, context, profile)
        right = evaluate(expression.right, context, profile)
        return {
            "==": lambda: left == right, "!=": lambda: left != right,
            "<": lambda: left < right, "<=": lambda: left <= right,
            ">": lambda: left > right, ">=": lambda: left >= right,
        }[expression.operator]()
    if isinstance(expression, Call):
        values = [evaluate(argument, context, profile) for argument in expression.args]
        try:
            return profile.evaluate_call(expression.name, values, context)
        except ProfileError as error:
            raise SpecError(str(error)) from error
    raise SpecError(f"未知表达式节点：{type(expression).__name__}")
