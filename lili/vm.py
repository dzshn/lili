"""Python bytecode emulation."""

from __future__ import annotations

import types
from collections.abc import Callable
from typing import Any, Optional, Protocol, cast

import opcode


class Handler(Protocol):
    __washing_mashing__: str

    @staticmethod
    def __call__(self: _WashingMashing, arg: int, unsafe: bool) -> None:
        pass


def _handles(op: str) -> Callable[[Callable[..., None]], Handler]:
    def decorator(fn: Callable[..., None]) -> Handler:
        fn = cast(Handler, fn)
        fn.__washing_mashing__ = op
        return fn

    return decorator


def _unsafe(fn: Callable[..., None]) -> Callable[..., None]:
    def wrapper(self, arg: int, unsafe: bool) -> None:
        if not unsafe:
            raise UnsafeOperation
        fn(self, arg, unsafe)

    return wrapper


class UnresolvableOperation(RuntimeError):
    pass


class UnsafeOperation(UnresolvableOperation):
    pass


class _WashingMashing:
    _handlers: dict[str, Handler] = {}

    def __init_subclass__(cls) -> None:
        handlers: dict[str, Handler] = {}
        for base in reversed(cls.mro()):
            for attr, value in base.__dict__.items():
                if hasattr(value, "__washing_mashing__"):
                    handlers[value.__washing_mashing__] = value

        cls._handlers = handlers

    def __init__(
        self,
        code: types.CodeType,
        locals: Optional[dict[str, Any]] = None,
        globals: Optional[dict[str, Any]] = None,
        builtins: Optional[dict[str, Any]] = None,
        parent: Optional[_WashingMashing] = None,
    ) -> None:
        self.code = code
        self.counter = 0
        self.stack: list[Any] = []
        self.locals = locals or {}
        self.globals = globals or {}
        self.builtins = builtins or {}
        self.parent = parent

    def step(self, unsafe: bool = False) -> Optional[UnresolvableOperation]:
        op, arg = self.current_opcode()
        handler = self._handlers.get(opcode.opname[op])
        if not handler:
            return UnresolvableOperation("unknown opcode")
        try:
            handler(self, arg, unsafe)
        except UnresolvableOperation as e:
            return e
        except Exception as e:
            return UnresolvableOperation(e)
        self.counter += 2
        return None

    def call(self, argc: int) -> _WashingMashing:
        if not isinstance(self.stack[-argc - 1], types.FunctionType):
            raise TypeError
        arguments = self.stack[-argc:]
        if argc:
            del self.stack[-argc:]
        fn = self.stack.pop()
        assert isinstance(fn, types.FunctionType)
        code = fn.__code__
        defaults = fn.__defaults__ or ()
        arguments.extend(defaults[-code.co_argcount - len(arguments):])
        locals = dict(zip(code.co_varnames, arguments))
        return type(self)(
            code,
            locals,
            self.locals | self.globals,
            self.builtins,
            self,
        )

    def return_call(self) -> _WashingMashing:
        if self.parent is None:
            return self
        self.parent.stack.append(self.stack.pop())
        return self.parent

    def current_opcode(self) -> tuple[int, int]:
        co = self.code.co_code
        return co[self.counter], co[self.counter + 1]


class CrossVM(_WashingMashing):
    @_handles("POP_TOP")
    def pop_top(self, arg: int, unsafe: bool) -> None:
        self.stack.pop()

    @_handles("ROT_TWO")
    def rot_two(self, arg: int, unsafe: bool) -> None:
        self.stack[-2:] = self.stack[-1], self.stack[-2]

    @_handles("ROT_THREE")
    def rot_three(self, arg: int, unsafe: bool) -> None:
        self.stack[-3:] = [self.stack[-1], *self.stack[-3:-1]]

    @_handles("ROT_FOUR")
    def rot_four(self, arg: int, unsafe: bool) -> None:
        self.stack[-4:] = [self.stack[-1], *self.stack[-4:-1]]

    @_handles("DUP_TOP")
    def dup_top(self, arg: int, unsafe: bool) -> None:
        self.stack.append(self.stack[-1])

    @_handles("DUP_TOP_TWO")
    def dup_top_two(self, arg: int, unsafe: bool) -> None:
        self.stack.extend(self.stack[-2:])

    @_handles("NOP")
    def nop(self, arg: int, unsafe: bool) -> None:
        pass

    @_handles("UNARY_POSITIVE")
    @_unsafe
    def unary_positive(self, arg: int, unsafe: bool) -> None:
        self.stack.append(+self.stack.pop())

    @_handles("UNARY_NEGATIVE")
    @_unsafe
    def unary_negative(self, arg: int, unsafe: bool) -> None:
        self.stack.append(-self.stack.pop())

    @_handles("UNARY_NOT")
    @_unsafe
    def unary_not(self, arg: int, unsafe: bool) -> None:
        self.stack.append(not self.stack.pop())

    @_handles("UNARY_INVERT")
    @_unsafe
    def unary_invert(self, arg: int, unsafe: bool) -> None:
        self.stack.append(~self.stack.pop())

    @_handles("BINARY_MATRIX_MULTIPLY")
    @_unsafe
    def binary_matrix_multiply(self, arg: int, unsafe: bool) -> None:
        self.stack.append(self.stack.pop(-2) @ self.stack.pop())

    @_handles("INPLACE_MATRIX_MULTIPLY")
    @_unsafe
    def inplace_matrix_multiply(self, arg: int, unsafe: bool) -> None:
        self.stack[-2] @= self.stack[-1]
        self.stack.pop()

    @_handles("BINARY_POWER")
    @_unsafe
    def binary_power(self, arg: int, unsafe: bool) -> None:
        self.stack.append(self.stack.pop(-2) ** self.stack.pop())

    @_handles("INPLACE_POWER")
    @_unsafe
    def inplace_power(self, arg: int, unsafe: bool) -> None:
        self.stack[-2] **= self.stack[-1]
        self.stack.pop()

    @_handles("BINARY_MULTIPLY")
    @_unsafe
    def binary_multiply(self, arg: int, unsafe: bool) -> None:
        self.stack.append(self.stack.pop(-2) * self.stack.pop())

    @_handles("INPLACE_MULTIPLY")
    @_unsafe
    def inplace_multiply(self, arg: int, unsafe: bool) -> None:
        self.stack[-2] **= self.stack[-1]
        self.stack.pop()

    @_handles("BINARY_MODULO")
    @_unsafe
    def binary_modulo(self, arg: int, unsafe: bool) -> None:
        self.stack.append(self.stack.pop(-2) % self.stack.pop())

    @_handles("INPLACE_MODULO")
    @_unsafe
    def inplace_modulo(self, arg: int, unsafe: bool) -> None:
        self.stack[-2] %= self.stack[-1]
        self.stack.pop()

    @_handles("BINARY_ADD")
    @_unsafe
    def binary_add(self, arg: int, unsafe: bool) -> None:
        self.stack.append(self.stack.pop(-2) + self.stack.pop())

    @_handles("INPLACE_ADD")
    @_unsafe
    def inplace_add(self, arg: int, unsafe: bool) -> None:
        self.stack[-2] += self.stack[-1]
        self.stack.pop()

    @_handles("BINARY_SUBTRACT")
    @_unsafe
    def binary_subtract(self, arg: int, unsafe: bool) -> None:
        self.stack.append(self.stack.pop(-2) - self.stack.pop())

    @_handles("INPLACE_SUBTRACT")
    @_unsafe
    def inplace_subtract(self, arg: int, unsafe: bool) -> None:
        self.stack[-2] -= self.stack[-1]
        self.stack.pop()

    @_handles("BINARY_FLOOR_DIVIDE")
    @_unsafe
    def binary_floor_divide(self, arg: int, unsafe: bool) -> None:
        self.stack.append(self.stack.pop(-2) // self.stack.pop())

    @_handles("INPLACE_FLOOR_DIVIDE")
    @_unsafe
    def inplace_floor_divide(self, arg: int, unsafe: bool) -> None:
        self.stack[-2] //= self.stack[-1]
        self.stack.pop()

    @_handles("BINARY_TRUE_DIVIDE")
    @_unsafe
    def binary_true_divide(self, arg: int, unsafe: bool) -> None:
        self.stack.append(self.stack.pop(-2) / self.stack.pop())

    @_handles("INPLACE_TRUE_DIVIDE")
    @_unsafe
    def inplace_true_divide(self, arg: int, unsafe: bool) -> None:
        self.stack[-2] /= self.stack[-1]
        self.stack.pop()

    @_handles("BINARY_SUBSCR")
    @_unsafe
    def binary_subscr(self, arg: int, unsafe: bool) -> None:
        self.stack.append(self.stack.pop(-2)[self.stack.pop()])

    @_handles("LOAD_CONST")
    def load_const(self, arg: int, unsafe: bool) -> None:
        self.stack.append(self.code.co_consts[arg])

    @_handles("LOAD_NAME")
    def load_name(self, arg: int, unsafe: bool) -> None:
        name = self.code.co_names[arg]
        for scope in (self.locals, self.globals, self.builtins):
            if name in scope:
                self.stack.append(scope[name])
                return

        raise NameError(f"{name} is not defined")

    @_handles("STORE_NAME")
    def store_name(self, arg: int, unsafe: bool) -> None:
        name = self.code.co_names[arg]
        self.locals[name] = self.stack.pop()

    @_handles("LOAD_FAST")
    def load_fast(self, arg: int, unsafe: bool) -> None:
        name = self.code.co_varnames[arg]
        if name in self.locals:
            self.stack.append(self.locals[name])
        else:
            raise NameError(f"local {name} is not defined")

    @_handles("STORE_FAST")
    def store_fast(self, arg: int, unsafe: bool) -> None:
        name = self.code.co_varnames[arg]
        self.locals[name] = self.stack.pop()

    @_handles("LOAD_GLOBAL")
    def load_global(self, arg: int, unsafe: bool) -> None:
        name = self.code.co_names[arg]
        if name in self.globals:
            self.stack.append(self.globals[name])
        else:
            raise NameError(f"local {name} is not defined")

    @_handles("STORE_GLOBAL")
    def store_global(self, arg: int, unsafe: bool) -> None:
        name = self.code.co_names[arg]
        self.globals[name] = self.stack.pop()

    @_handles("BUILD_TUPLE")
    def build_tuple(self, arg: int, unsafe: bool) -> None:
        self.stack.append(tuple(self.stack[-arg:]))
        del self.stack[-arg-1:-1]

    @_handles("MAKE_FUNCTION")
    def make_function(self, arg: int, unsafe: bool) -> None:
        name = self.stack.pop()
        func_code = self.stack.pop()
        cells = annotations = kwarg_defaults = arg_defaults = None
        if arg & 0b1000:
            cells = self.stack.pop()
        if arg & 0b0100:
            annotations = self.stack.pop()
        if arg & 0b0010:
            kwarg_defaults = self.stack.pop()
        if arg & 0b0001:
            arg_defaults = self.stack.pop()

        fn = types.FunctionType(func_code, self.globals, name, arg_defaults, cells)
        if annotations:
            fn.__annotations__ = dict(zip(annotations[::2], annotations[1::2]))
        if kwarg_defaults:
            fn.__kwdefaults__ = kwarg_defaults

        self.stack.append(fn)

    @_handles("CALL_FUNCTION")
    @_unsafe
    def call_function(self, arg: int, unsafe: bool) -> None:
        arguments = self.stack[-arg:]
        del self.stack[-arg:]

        fn = self.stack.pop()
        self.stack.append(fn(*arguments))
