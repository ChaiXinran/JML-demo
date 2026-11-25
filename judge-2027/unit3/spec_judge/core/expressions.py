"""Domain-independent expression AST, parser, validation, and evaluation.

The default parser understands the expression subset used by the unit 3 JML
questions.  Callers that feed expressions to the legacy SMT translator can set
``extended=False`` to retain the original AST-only grammar.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any, Mapping

from .errors import SpecError
from .profile import (
    NO_RESULT,
    ArrayValue,
    EvaluationContext,
    EvaluationProfile,
    ProfileError,
)


MAX_EXPRESSION_TOKENS = 4096
MAX_SYNTAX_NESTING = 32
MAX_AST_DEPTH = 128
MAX_INTEGER_LITERAL_DIGITS = 4096
MAX_QUANTIFIER_BINDINGS = 32
MAX_BOUND_PROPAGATION_ROUNDS = 128


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    offset: int


TOKEN_RE = re.compile(
    r"\s*(?:(?P<JML>\\(?:old|result|forall|exists|num_of))|"
    r"(?P<OP><==>|==>|&&|\|\||==|!=|<=|>=)|"
    r"(?P<PUNC>[().,;!<>\[\]+\-])|(?P<INT>\d+)|"
    r"(?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)|(?P<BAD>.))"
)


_EXTENDED_ONLY_TOKENS = frozenset({
    "\\result", "\\forall", "\\exists", "\\num_of", "==>", "<==>",
    "+", "-", "[", "]", "null",
})


def tokenize(source: str, *, max_tokens: int = MAX_EXPRESSION_TOKENS) -> list[Token]:
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
        if len(result) >= max_tokens:
            raise SpecError(f"表达式 token 数超过上限 {max_tokens}")
        result.append(Token(kind if kind not in {"OP", "PUNC", "JML"} else text, text, match.start(kind)))
    result.append(Token("EOF", "", len(source)))
    return result


class Expr:
    pass


@dataclasses.dataclass(frozen=True)
class Literal(Expr):
    value: Any


@dataclasses.dataclass(frozen=True)
class NullLiteral(Expr):
    """The JML ``null`` literal, kept distinct from boolean and integer values."""


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
class ArrayAccess(Expr):
    array: Expr
    index: Expr


@dataclasses.dataclass(frozen=True)
class ArrayLength(Expr):
    array: Expr


@dataclasses.dataclass(frozen=True)
class Quantifier(Expr):
    """A bounded JML quantifier.

    ``kind`` is one of ``forall``, ``exists`` or ``num_of``. ``bindings``
    contains the integer variable names in declaration order.
    """

    kind: str
    bindings: tuple[str, ...]
    range_expression: Expr
    predicate: Expr


def _expression_children(expression: Expr) -> tuple[Expr, ...]:
    if isinstance(expression, Call):
        return expression.args
    if isinstance(expression, Unary):
        return (expression.operand,)
    if isinstance(expression, Binary):
        return (expression.left, expression.right)
    if isinstance(expression, Old):
        return (expression.expression,)
    if isinstance(expression, ArrayAccess):
        return (expression.array, expression.index)
    if isinstance(expression, ArrayLength):
        return (expression.array,)
    if isinstance(expression, Quantifier):
        return (expression.range_expression, expression.predicate)
    return ()


def _check_syntax_nesting(tokens: list[Token]) -> None:
    """Bound recursive grammar nesting before recursive descent starts."""
    nesting = 0
    unary_run = 0
    for token in tokens:
        if token.kind in {"(", "["}:
            nesting += 1
            if nesting > MAX_SYNTAX_NESTING:
                raise SpecError(f"表达式语法嵌套超过上限 {MAX_SYNTAX_NESTING}")
        elif token.kind in {")", "]"}:
            nesting = max(0, nesting - 1)

        if token.kind == "!":
            unary_run += 1
            if unary_run > MAX_SYNTAX_NESTING:
                raise SpecError(f"连续一元否定超过上限 {MAX_SYNTAX_NESTING}")
        else:
            unary_run = 0


def _check_ast_depth(expression: Expr) -> None:
    """Check AST depth iteratively so a hostile tree cannot overflow checks."""
    stack = [(expression, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_AST_DEPTH:
            raise SpecError(f"表达式 AST 深度超过上限 {MAX_AST_DEPTH}")
        stack.extend((child, depth + 1) for child in _expression_children(node))


def _balanced_binary(operator: str, expressions: list[Expr]) -> Expr:
    """Build an order-preserving balanced tree for associative boolean chains."""
    while len(expressions) > 1:
        combined: list[Expr] = []
        for index in range(0, len(expressions), 2):
            if index + 1 == len(expressions):
                combined.append(expressions[index])
            else:
                combined.append(Binary(operator, expressions[index], expressions[index + 1]))
        expressions = combined
    return expressions[0]


class ExpressionParser:
    def __init__(self, source: str, *, extended: bool = True):
        self.tokens = tokenize(source)
        if not extended:
            unsupported = next(
                (token for token in self.tokens if token.text in _EXTENDED_ONLY_TOKENS),
                None,
            )
            if unsupported is not None:
                raise SpecError(
                    f"旧版表达式模式不支持 {unsupported.text!r}（位置 {unsupported.offset}）"
                )
        self.extended = extended
        _check_syntax_nesting(self.tokens)
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
        expression = self.parse_equivalence()
        self.expect("EOF")
        _check_ast_depth(expression)
        return expression

    def parse_equivalence(self) -> Expr:
        expression = self.parse_implication()
        while self.accept("<==>"):
            expression = Binary("<==>", expression, self.parse_implication())
        return expression

    def parse_implication(self) -> Expr:
        expression = self.parse_or()
        if self.accept("==>"):
            return Binary("==>", expression, self.parse_implication())
        return expression

    def parse_or(self) -> Expr:
        expressions = [self.parse_and()]
        while self.accept("||"):
            expressions.append(self.parse_and())
        return _balanced_binary("||", expressions)

    def parse_and(self) -> Expr:
        expressions = [self.parse_equality()]
        while self.accept("&&"):
            expressions.append(self.parse_equality())
        return _balanced_binary("&&", expressions)

    def parse_equality(self) -> Expr:
        expression = self.parse_relational()
        while self.current().kind in {"==", "!="}:
            operator = self.current().kind
            self.index += 1
            expression = Binary(operator, expression, self.parse_relational())
        return expression

    def parse_relational(self) -> Expr:
        expression = self.parse_additive()
        while self.current().kind in {"<", "<=", ">", ">="}:
            operator = self.current().kind
            self.index += 1
            expression = Binary(operator, expression, self.parse_additive())
        return expression

    def parse_additive(self) -> Expr:
        expression = self.parse_unary()
        while self.current().kind in {"+", "-"}:
            operator = self.current().kind
            self.index += 1
            expression = Binary(operator, expression, self.parse_unary())
        return expression

    def parse_unary(self) -> Expr:
        prefixes: list[str] = []
        while self.current().kind in {"!", "+", "-"}:
            prefixes.append(self.current().kind)
            self.index += 1
        if self.accept("\\old"):
            self.expect("(")
            expression: Expr = Old(self.parse_equivalence())
            self.expect(")")
            expression = self.parse_postfix(expression)
        else:
            expression = self.parse_primary()
        for operator in reversed(prefixes):
            expression = Unary(operator, expression)
        return expression

    def parse_primary(self) -> Expr:
        if self.accept("INT"):
            literal = self.tokens[self.index - 1].text
            if len(literal) > MAX_INTEGER_LITERAL_DIGITS:
                raise SpecError(f"整数字面量长度超过上限 {MAX_INTEGER_LITERAL_DIGITS} 位")
            try:
                expression: Expr = Literal(int(literal))
            except ValueError as error:
                raise SpecError("整数字面量无效或超出解释器转换限制") from error
            return self.parse_postfix(expression)
        if self.accept("\\result"):
            return self.parse_postfix(Variable("\\result"))
        if self.accept("("):
            if self.current().kind in {"\\forall", "\\exists", "\\num_of"}:
                return self.parse_quantifier()
            expression = self.parse_equivalence()
            self.expect(")")
            return self.parse_postfix(expression)

        identifier = self.accept("IDENT")
        if identifier is None:
            token = self.current()
            raise SpecError(f"无法在位置 {token.offset} 解析 {token.text!r}")
        if identifier.text == "true":
            expression = Literal(True)
        elif identifier.text == "false":
            expression = Literal(False)
        elif identifier.text == "null":
            expression = NullLiteral()
        elif self.accept("("):
            expression = Call(identifier.text, self.parse_arguments())
        else:
            expression = Variable(identifier.text)
        return self.parse_postfix(expression)

    def parse_postfix(self, expression: Expr) -> Expr:
        while True:
            if self.accept("["):
                index = self.parse_equivalence()
                self.expect("]")
                expression = ArrayAccess(expression, index)
                continue
            if self.accept("."):
                member = self.expect("IDENT")
                if member.text == "length" and self.current().kind != "(":
                    expression = ArrayLength(expression)
                    continue
                if self.accept("("):
                    expression = Call(member.text, (expression, *self.parse_arguments()))
                    continue
                if isinstance(expression, Variable) and expression.name == "this":
                    # The target profiles model a small number of fields directly.
                    expression = Variable(member.text)
                    continue
                raise SpecError(f"不支持字段访问：{member.text}")
            return expression

    def parse_quantifier(self) -> Expr:
        keyword = self.expect("\\forall", "\\exists", "\\num_of")
        if not self.extended:
            raise SpecError(f"旧版表达式模式不支持 {keyword.text}")
        kind = keyword.text.removeprefix("\\")
        bindings: list[str] = []
        self.expect("IDENT")
        if self.tokens[self.index - 1].text != "int":
            raise SpecError("量词目前只支持 int 绑定变量")
        while True:
            name = self.expect("IDENT").text
            if name in bindings:
                raise SpecError(f"量词绑定变量重复：{name}")
            bindings.append(name)
            if len(bindings) > MAX_QUANTIFIER_BINDINGS:
                raise SpecError(f"量词绑定变量超过上限 {MAX_QUANTIFIER_BINDINGS}")
            if not self.accept(","):
                break
        self.expect(";")
        range_expression = self.parse_equivalence()
        self.expect(";")
        predicate = self.parse_equivalence()
        self.expect(")")
        return Quantifier(kind, tuple(bindings), range_expression, predicate)

    def parse_arguments(self) -> tuple[Expr, ...]:
        arguments: list[Expr] = []
        if self.accept(")"):
            return tuple(arguments)
        while True:
            arguments.append(self.parse_equivalence())
            if self.accept(")"):
                return tuple(arguments)
            self.expect(",")


def _walk(expression: Expr):
    stack = [expression]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(_expression_children(node))


def _contains_result(expression: Expr) -> bool:
    return any(isinstance(node, Variable) and node.name == "\\result" for node in _walk(expression))


def validate_calls(expression: Expr, profile: EvaluationProfile) -> None:
    if isinstance(expression, Call):
        if expression.name not in profile.allowed_calls:
            raise SpecError(f"不允许调用接口外函数：{expression.name}")
    for child in _expression_children(expression):
        validate_calls(child, profile)


def _normalized_type(type_name: str) -> str:
    return re.sub(r"\bboolean\b", "bool", type_name)


def _array_component_type(type_name: str) -> str | None:
    type_name = _normalized_type(type_name)
    if type_name.endswith("[]"):
        return type_name[:-2]
    return None


def _is_array_type(type_name: str) -> bool:
    return _array_component_type(type_name) is not None


def _lookup_variable_type(name: str, profile: EvaluationProfile, variables: Mapping[str, str]) -> str | None:
    if name in variables:
        return _normalized_type(variables[name])
    state_variables = getattr(profile, "state_variables", {})
    if name in state_variables:
        value = state_variables[name]
        if isinstance(value, str):
            return _normalized_type(value)
    return None


def infer_type(
    expression: Expr,
    profile: EvaluationProfile,
    variables: Mapping[str, str],
) -> str:
    """Statically type-check the supported expression subset."""
    if isinstance(expression, Literal):
        return "bool" if isinstance(expression.value, bool) else "int"
    if isinstance(expression, NullLiteral):
        return "null"
    if isinstance(expression, Variable):
        variable_type = _lookup_variable_type(expression.name, profile, variables)
        if variable_type is None:
            raise SpecError(f"未定义的变量：{expression.name}")
        return variable_type
    if isinstance(expression, Old):
        if _contains_result(expression.expression):
            raise SpecError("不支持在 \\old 中引用 \\result")
        return infer_type(expression.expression, profile, variables)
    if isinstance(expression, Unary):
        operand = infer_type(expression.operand, profile, variables)
        if expression.operator == "!" and operand == "bool":
            return "bool"
        if expression.operator in {"+", "-"} and operand == "int":
            return "int"
        raise SpecError(f"一元运算 {expression.operator} 不能用于 {operand}")
    if isinstance(expression, ArrayLength):
        array_type = infer_type(expression.array, profile, variables)
        if not _is_array_type(array_type):
            raise SpecError(f".length 左侧必须是数组，实际为 {array_type}")
        return "int"
    if isinstance(expression, ArrayAccess):
        array_type = infer_type(expression.array, profile, variables)
        if not _is_array_type(array_type):
            raise SpecError(f"下标访问左侧必须是数组，实际为 {array_type}")
        index_type = infer_type(expression.index, profile, variables)
        if index_type != "int":
            raise SpecError(f"数组下标必须是 int，实际为 {index_type}")
        component_type = _array_component_type(array_type)
        assert component_type is not None
        return component_type
    if isinstance(expression, Quantifier):
        scoped = dict(variables)
        scoped.update({name: "int" for name in expression.bindings})
        range_type = infer_type(expression.range_expression, profile, scoped)
        predicate_type = infer_type(expression.predicate, profile, scoped)
        if range_type != "bool" or predicate_type != "bool":
            raise SpecError("量词的范围和条件都必须是 bool")
        return "int" if expression.kind == "num_of" else "bool"
    if isinstance(expression, Binary):
        left = infer_type(expression.left, profile, variables)
        right = infer_type(expression.right, profile, variables)
        if expression.operator in {"&&", "||", "==>", "<==>"}:
            if left != "bool" or right != "bool":
                raise SpecError(f"逻辑运算 {expression.operator} 两侧必须是 bool")
            return "bool"
        if expression.operator in {"+", "-"}:
            if left != "int" or right != "int":
                raise SpecError(f"算术运算 {expression.operator} 两侧必须是 int")
            return "int"
        if expression.operator in {"<", "<=", ">", ">="}:
            if left != "int" or right != "int":
                raise SpecError(f"比较运算 {expression.operator} 两侧必须是 int")
            return "bool"
        if expression.operator in {"==", "!="}:
            compatible = left == right or (left == "null" and _is_array_type(right)) or (
                right == "null" and _is_array_type(left)
            )
            if not compatible:
                raise SpecError(f"相等比较两侧类型不同：{left} 与 {right}")
            return "bool"
        raise SpecError(f"不支持的二元运算：{expression.operator}")
    if isinstance(expression, Call):
        argument_types = tuple(infer_type(item, profile, variables) for item in expression.args)
        for signature in profile.symbols.get(expression.name, ()):
            if tuple(_normalized_type(x) for x in signature.parameters) == argument_types:
                return _normalized_type(signature.returns)
        rendered = ", ".join(argument_types)
        raise SpecError(f"函数 {expression.name} 不接受参数类型 ({rendered})")
    raise SpecError(f"未知表达式节点：{type(expression).__name__}")


def _consume(context: EvaluationContext, amount: int = 1) -> None:
    if context.budget is not None:
        context.budget.consume(amount)


def _state_variables(profile: EvaluationProfile) -> Mapping[str, Any]:
    value = getattr(profile, "state_variables", {})
    return value if isinstance(value, Mapping) else {}


def _lookup_state_value(name: str, context: EvaluationContext, profile: EvaluationProfile) -> Any:
    state_variables = _state_variables(profile)
    if name not in state_variables:
        raise SpecError(f"未定义的变量：{name}")
    lookup = getattr(profile, "state_name", None)
    if not callable(lookup):
        raise SpecError(f"Profile 未提供状态变量读取接口：{name}")
    try:
        return lookup(name, context.current)
    except (ProfileError, KeyError, AttributeError, TypeError) as error:
        raise SpecError(f"无法读取状态变量 {name}：{error}") from error


def _lookup_variable(name: str, context: EvaluationContext, profile: EvaluationProfile,
                     bindings: Mapping[str, int]) -> Any:
    if name in bindings:
        return bindings[name]
    if name == "\\result":
        if context.result is NO_RESULT:
            raise SpecError("当前没有可用的 \\result")
        return context.result
    if name in context.arguments:
        return context.arguments[name]
    if name in _state_variables(profile):
        return _lookup_state_value(name, context, profile)
    raise SpecError(f"未定义的变量：{name}")


def _array_view(value: Any, context: EvaluationContext, profile: EvaluationProfile) -> ArrayValue:
    if value is None:
        raise SpecError("不能对 null 数组取长度或下标")
    if not isinstance(value, ArrayValue):
        raise SpecError(f"数组值格式无效：{type(value).__name__}")
    # An old reference retains its identity. If the same array still exists in
    # the current heap, indexed reads observe the current contents. Otherwise
    # the detached old snapshot itself is the only modeled view.
    for name in _state_variables(profile):
        try:
            candidate = _lookup_state_value(name, context, profile)
        except SpecError:
            continue
        if isinstance(candidate, ArrayValue) and candidate.identity == value.identity:
            return candidate
    return value


def _array_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, ArrayValue) and isinstance(right, ArrayValue):
        return left.identity == right.identity
    if isinstance(left, ArrayValue) or isinstance(right, ArrayValue):
        raise SpecError("数组相等比较遇到格式不一致的值")
    return left == right


def _evaluate(expression: Expr, context: EvaluationContext, profile: EvaluationProfile,
              bindings: Mapping[str, int]) -> Any:
    _consume(context)
    if isinstance(expression, Literal):
        return expression.value
    if isinstance(expression, NullLiteral):
        return None
    if isinstance(expression, Variable):
        return _lookup_variable(expression.name, context, profile, bindings)
    if isinstance(expression, Old):
        if _contains_result(expression.expression):
            raise SpecError("不支持在 \\old 中引用 \\result")
        return _evaluate(expression.expression, context.pre_state(), profile, bindings)
    if isinstance(expression, Unary):
        value = _evaluate(expression.operand, context, profile, bindings)
        if expression.operator == "!":
            return not bool(value)
        if not isinstance(value, int) or isinstance(value, bool):
            raise SpecError(f"一元运算 {expression.operator} 需要 int")
        return value if expression.operator == "+" else -value
    if isinstance(expression, ArrayLength):
        value = _evaluate(expression.array, context, profile, bindings)
        return len(_array_view(value, context, profile).values)
    if isinstance(expression, ArrayAccess):
        array_value = _evaluate(expression.array, context, profile, bindings)
        index = _evaluate(expression.index, context, profile, bindings)
        if not isinstance(index, int) or isinstance(index, bool):
            raise SpecError("数组下标必须是整数")
        array_value = _array_view(array_value, context, profile)
        if index < 0 or index >= len(array_value.values):
            raise SpecError("数组下标越界")
        return array_value.values[index]
    if isinstance(expression, Quantifier):
        return _evaluate_quantifier(expression, context, profile, bindings)
    if isinstance(expression, Binary):
        operator = expression.operator
        if operator == "&&":
            return bool(_evaluate(expression.left, context, profile, bindings)) and bool(
                _evaluate(expression.right, context, profile, bindings)
            )
        if operator == "||":
            return bool(_evaluate(expression.left, context, profile, bindings)) or bool(
                _evaluate(expression.right, context, profile, bindings)
            )
        if operator == "==>":
            return (not bool(_evaluate(expression.left, context, profile, bindings))) or bool(
                _evaluate(expression.right, context, profile, bindings)
            )
        left = _evaluate(expression.left, context, profile, bindings)
        right = _evaluate(expression.right, context, profile, bindings)
        if operator == "<==>":
            return bool(left) == bool(right)
        if operator in {"==", "!="}:
            equal = _array_equal(left, right)
            return equal if operator == "==" else not equal
        if operator in {"+", "-"}:
            if not all(isinstance(value, int) and not isinstance(value, bool) for value in (left, right)):
                raise SpecError(f"算术运算 {operator} 需要 int")
            return left + right if operator == "+" else left - right
        if operator in {"<", "<=", ">", ">="}:
            try:
                return {
                    "<": lambda: left < right,
                    "<=": lambda: left <= right,
                    ">": lambda: left > right,
                    ">=": lambda: left >= right,
                }[operator]()
            except TypeError as error:
                raise SpecError(f"比较运算 {operator} 的值类型无效") from error
        raise SpecError(f"不支持的二元运算：{operator}")
    if isinstance(expression, Call):
        values = [_evaluate(argument, context, profile, bindings) for argument in expression.args]
        try:
            return profile.evaluate_call(expression.name, values, context)
        except ProfileError as error:
            raise SpecError(str(error)) from error
    raise SpecError(f"未知表达式节点：{type(expression).__name__}")


def _conjuncts(expression: Expr) -> list[Expr]:
    if isinstance(expression, Binary) and expression.operator == "&&":
        return _conjuncts(expression.left) + _conjuncts(expression.right)
    return [expression]


_Interval = tuple[int | None, int | None]


def _integer_interval(expression: Expr, context: EvaluationContext, profile: EvaluationProfile,
                      outer_bindings: Mapping[str, int],
                      bounds: Mapping[str, _Interval]) -> _Interval | None:
    if isinstance(expression, Literal):
        if isinstance(expression.value, int) and not isinstance(expression.value, bool):
            return expression.value, expression.value
        return None
    if isinstance(expression, Variable):
        if expression.name in bounds:
            return bounds[expression.name]
        if expression.name in outer_bindings:
            value = outer_bindings[expression.name]
        else:
            try:
                value = _lookup_variable(expression.name, context, profile, outer_bindings)
            except SpecError:
                return None
        if isinstance(value, int) and not isinstance(value, bool):
            return value, value
        return None
    if isinstance(expression, Old):
        return _integer_interval(expression.expression, context.pre_state(), profile, outer_bindings, bounds)
    if isinstance(expression, Unary) and expression.operator in {"+", "-"}:
        interval = _integer_interval(expression.operand, context, profile, outer_bindings, bounds)
        if interval is None:
            return None
        lo, hi = interval
        if expression.operator == "+":
            return lo, hi
        return (-hi if hi is not None else None, -lo if lo is not None else None)
    if isinstance(expression, Binary) and expression.operator in {"+", "-"}:
        left = _integer_interval(expression.left, context, profile, outer_bindings, bounds)
        right = _integer_interval(expression.right, context, profile, outer_bindings, bounds)
        if left is None or right is None:
            return None
        llo, lhi = left
        rlo, rhi = right
        if expression.operator == "+":
            return (
                llo + rlo if llo is not None and rlo is not None else None,
                lhi + rhi if lhi is not None and rhi is not None else None,
            )
        return (
            llo - rhi if llo is not None and rhi is not None else None,
            lhi - rlo if lhi is not None and rlo is not None else None,
        )
    if isinstance(expression, ArrayLength):
        try:
            value = _evaluate(expression.array, context, profile, outer_bindings)
            length = len(_array_view(value, context, profile).values)
            return length, length
        except SpecError:
            return None
    if isinstance(expression, ArrayAccess):
        try:
            value = _evaluate(expression.array, context, profile, outer_bindings)
            array = _array_view(value, context, profile)
        except SpecError:
            return None
        index_interval = _integer_interval(
            expression.index, context, profile, outer_bindings, bounds
        )
        if index_interval is None:
            return None
        lo, hi = index_interval
        if lo is None or hi is None or lo < 0 or hi >= len(array.values) or lo > hi:
            return None
        selected = array.values[lo:hi + 1]
        if not selected or any(not isinstance(value, int) or isinstance(value, bool) for value in selected):
            return None
        return min(selected), max(selected)
    return None


def _tighten(current: _Interval, lower: int | None = None,
             upper: int | None = None) -> tuple[_Interval, bool]:
    old_lower, old_upper = current
    new_lower = old_lower if lower is None else (lower if old_lower is None else max(old_lower, lower))
    new_upper = old_upper if upper is None else (upper if old_upper is None else min(old_upper, upper))
    updated = (new_lower, new_upper)
    return updated, updated != current


def _additive_terms(expression: Expr, sign: int):
    """Flatten only integer addition and subtraction into signed terms."""
    if isinstance(expression, Unary) and expression.operator in {"+", "-"}:
        yield from _additive_terms(expression.operand, sign if expression.operator == "+" else -sign)
    elif isinstance(expression, Binary) and expression.operator in {"+", "-"}:
        yield from _additive_terms(expression.left, sign)
        yield from _additive_terms(expression.right, sign if expression.operator == "+" else -sign)
    else:
        yield expression, sign


def _scaled_interval(interval: _Interval, factor: int) -> _Interval:
    lower, upper = interval
    if factor < 0:
        lower, upper = upper, lower
    return (
        lower * factor if lower is not None else None,
        upper * factor if upper is not None else None,
    )


def _add_intervals(left: _Interval, right: _Interval) -> _Interval:
    lo, hi = left
    other_lo, other_hi = right
    return (
        lo + other_lo if lo is not None and other_lo is not None else None,
        hi + other_hi if hi is not None and other_hi is not None else None,
    )


def _apply_bound_constraint(constraint: Expr, context: EvaluationContext, profile: EvaluationProfile,
                            outer_bindings: Mapping[str, int],
                            bounds: dict[str, _Interval]) -> bool:
    if not isinstance(constraint, Binary) or constraint.operator not in {"<", "<=", ">", ">=", "=="}:
        return False

    # Normalize to a sum <= limit (or == 0). Strict integer inequalities
    # use -1 as the limit. Keep non-additive terms as interval-valued atoms.
    sign = -1 if constraint.operator in {">", ">="} else 1
    limit = -1 if constraint.operator in {"<", ">"} else 0
    equality = constraint.operator == "=="
    coefficients: dict[str, int] = {}
    other_terms = []
    for side, factor in ((constraint.left, sign), (constraint.right, -sign)):
        for term, multiplier in _additive_terms(side, factor):
            _consume(context)
            if isinstance(term, Variable) and term.name in bounds:
                coefficients[term.name] = coefficients.get(term.name, 0) + multiplier
            else:
                other_terms.append((term, multiplier))
    coefficients = {name: factor for name, factor in coefficients.items() if factor}
    if not coefficients:
        return False

    remainder = (0, 0)
    for term, multiplier in other_terms:
        interval = _integer_interval(term, context, profile, outer_bindings, bounds)
        if interval is None:
            return False
        remainder = _add_intervals(remainder, _scaled_interval(interval, multiplier))

    changed = False
    for name, factor in coefficients.items():
        # An over-approximation of the other terms gives a necessary bound.
        # The original range expression still filters each enumerated tuple.
        residual = remainder
        for other, other_factor in coefficients.items():
            if other != name:
                _consume(context)
                residual = _add_intervals(residual, _scaled_interval(bounds[other], other_factor))
        lo, hi = residual
        lower = upper = None
        if factor > 0:
            if lo is not None:
                upper = (limit - lo) // factor
            if equality and hi is not None:
                lower = -(hi // factor)
        else:
            if lo is not None:
                lower = -((limit - lo) // -factor)
            if equality and hi is not None:
                upper = hi // -factor
        bounds[name], tightened = _tighten(bounds[name], lower, upper)
        changed |= tightened
    return changed


def _infer_quantifier_bounds(quantifier: Quantifier, context: EvaluationContext,
                             profile: EvaluationProfile,
                             outer_bindings: Mapping[str, int]) -> dict[str, tuple[int, int]]:
    bounds: dict[str, _Interval] = {name: (None, None) for name in quantifier.bindings}
    constraints = _conjuncts(quantifier.range_expression)
    for _ in range(MAX_BOUND_PROPAGATION_ROUNDS):
        changed = False
        for constraint in constraints:
            _consume(context)
            changed |= _apply_bound_constraint(
                constraint, context, profile, outer_bindings, bounds
            )
        if any(lo is not None and hi is not None and lo > hi for lo, hi in bounds.values()):
            return {name: (0, -1) for name in bounds}
        if not changed:
            break
    else:
        raise SpecError("量词范围的边界推导未收敛")
    result: dict[str, tuple[int, int]] = {}
    for name, (lo, hi) in bounds.items():
        if lo is None or hi is None:
            raise SpecError(f"量词变量 {name} 没有可证明的有限上下界")
        result[name] = (max(lo, -(1 << 31)), min(hi, (1 << 31) - 1))
    return result


def _evaluate_quantifier(quantifier: Quantifier, context: EvaluationContext,
                         profile: EvaluationProfile,
                         outer_bindings: Mapping[str, int]) -> bool | int:
    bounds = _infer_quantifier_bounds(quantifier, context, profile, outer_bindings)
    if any(lo > hi for lo, hi in bounds.values()):
        return 0 if quantifier.kind == "num_of" else quantifier.kind == "forall"

    names = quantifier.bindings
    values = [0]
    found = False

    def visit(position: int, scoped: dict[str, int]) -> bool:
        nonlocal found
        if position == len(names):
            _consume(context)
            if not bool(_evaluate(quantifier.range_expression, context, profile, scoped)):
                return False
            predicate_value = bool(_evaluate(quantifier.predicate, context, profile, scoped))
            if quantifier.kind == "forall" and not predicate_value:
                found = True
                return True
            if quantifier.kind == "exists" and predicate_value:
                found = True
                return True
            if quantifier.kind == "num_of" and predicate_value:
                values[0] += 1
            return False
        name = names[position]
        lo, hi = bounds[name]
        for value in range(lo, hi + 1):
            scoped[name] = value
            if visit(position + 1, scoped):
                scoped.pop(name, None)
                return True
        scoped.pop(name, None)
        return False

    stopped = visit(0, dict(outer_bindings))
    if quantifier.kind == "num_of":
        return values[0]
    if quantifier.kind == "forall":
        return not (stopped and found)
    return stopped and found


def evaluate(expression: Expr, context: EvaluationContext, profile: EvaluationProfile) -> Any:
    """Evaluate an already type-checked AST against a concrete scenario."""
    return _evaluate(expression, context, profile, {})
