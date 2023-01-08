from __future__ import annotations

import ast
import dataclasses
import tokenize
from collections import defaultdict
from collections.abc import Callable, Iterator
from types import CodeType
from typing import Any, BinaryIO, Optional, TypeVar, Union

import opcode

from lili.compat import CompilerFlags

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)


class LookAhead(Iterator[T_co]):
    def __init__(self, iterator: Iterator[T_co]) -> None:
        self._it = iterator
        self._cache: list[T_co] = []

    def __next__(self) -> T_co:
        if self._cache:
            return self._cache.pop(0)
        return next(self._it)

    def lookahead(self, n: int = 0, default: Optional[T] = None) -> Union[T_co, T]:
        while len(self._cache) < n + 1:
            try:
                self._cache.append(next(self._it))
            except StopIteration:
                if default is not None:
                    return default
                raise
        return self._cache[n]

    def skip(self, n: int = 1) -> None:
        for _ in range(n):
            next(self, None)


@dataclasses.dataclass
class Code:
    children: list[Union[Directive, Opcode]]
    parent: Optional[Code]


@dataclasses.dataclass
class Directive:
    name: str
    value: str


@dataclasses.dataclass
class Opcode:
    op: int
    arg: Union[int, str, Code]


def pys_parse(readline: Callable[[], bytes]) -> Code:
    tokens = LookAhead(tokenize.tokenize(readline))
    root = Code([], None)
    node = root

    for token in tokens:
        if token.string == ".":
            name = next(tokens).string
            value = ""
            while True:
                token = next(tokens)
                if token.string == "\n":
                    break
                value += token.string
            node.children.append(Directive(name, value))
        elif tokens.lookahead(default=False) and tokens.lookahead().string == ":":
            node.children.append(Directive("label", token.string))
            tokens.skip(2)
        elif token.type == tokenize.NAME:
            op = opcode.opmap[token.string]
            if tokens.lookahead().string == "@":
                tokens.skip()
                if (
                    tokens.lookahead().string == "code"
                    and tokens.lookahead(2).string == ":"
                ):
                    child = Code([Directive("name", tokens.lookahead(1).string)], node)
                    node.children.append(Opcode(op, child))
                    node = child
                    tokens.skip(3)
                else:
                    arg = ""
                    while True:
                        token = next(tokens)
                        if token.string == "\n":
                            break
                        arg += token.string
                    node.children.append(Opcode(op, arg))
            else:
                if tokens.lookahead().string != "\n":
                    node.children.append(
                        Opcode(op, int(ast.literal_eval(next(tokens).string)))
                    )
                else:
                    node.children.append(Opcode(op, 0))
        elif token.type == tokenize.DEDENT:
            if node.parent:
                node = node.parent
        elif (
            token.type
            not in {
                tokenize.ENDMARKER, tokenize.ENCODING, tokenize.INDENT, tokenize.COMMENT
            }
            and token.string not in {"\n", ";"}
        ):
            raise ValueError(f"unexpected token {token.string}")

    return root


def pys_assemble(
    node: Code, filename: str = "<pys_assemble>", name: str = "<module>"
) -> CodeType:
    code_args: dict[str, Any] = {
        "argcount": 0,
        "posonlyargcount": 0,
        "kwonlyargcount": 0,
        "nlocals": 0,
        "stacksize": 0,
        "flags": 0,
        "codestring": bytearray(),
        "constants": [],
        "names": [],
        "varnames": [],
        "filename": filename,
        "name": name,
        "firstlineno": 1,
        "linetable": b"",
        "freevars": [],
        "cellvars": [],
    }
    labels: dict[str, int] = {}
    deferred_labels: dict[str, list[int]] = defaultdict(list)
    bytecode: bytearray = code_args["codestring"]
    for n in node.children:
        if isinstance(n, Directive):
            if n.name == "label":
                labels[n.value] = len(bytecode) // 2
                for i in deferred_labels[n.value]:
                    bytecode[i] = labels[n.value]
            elif n.name == "flags":
                for flag in n.value.split("|"):
                    code_args["flags"] |= CompilerFlags[flag].value
            elif n.name == "name":
                code_args["name"] = n.value
            elif n.name in code_args:
                code_args[n.name] = ast.literal_eval(n.value)
            else:
                raise ValueError(f"unknown directive {n.name} {n.value}")
        else:
            bytecode.append(n.op)
            if isinstance(n.arg, int):
                bytecode.append(n.arg)
            elif n.op in opcode.hasconst:
                if isinstance(n.arg, Code):
                    code_args["constants"].append(pys_assemble(n.arg))
                    bytecode.append(len(bytecode) - 1)
                else:
                    value = ast.literal_eval(n.arg)
                    for i, x in enumerate(code_args["constants"]):
                        if x is value:
                            bytecode.append(i)
                            break
                    else:
                        code_args["constants"].append(value)
                        bytecode.append(len(code_args["constants"]) - 1)
            elif n.op in opcode.hasname:
                if n.arg in code_args["names"]:
                    bytecode.append(code_args["names"].index(n.arg))
                else:
                    code_args["names"].append(n.arg)
                    bytecode.append(len(code_args["names"]) - 1)
            elif n.op in opcode.hasjabs:
                assert not isinstance(n.arg, Code)
                if (address := labels.get(n.arg)) is not None:
                    bytecode.append(address)
                else:
                    deferred_labels[n.arg].append(len(bytecode))
                    bytecode.append(0)
            else:
                raise ValueError(f"Can't parse opcode {n.op} @ {n.arg}")

    code_args["codestring"] = bytes(code_args["codestring"])
    for arg in ("constants", "names", "varnames", "freevars", "cellvars"):
        code_args[arg] = tuple(code_args[arg])
    return CodeType(*code_args.values())


def read_pys(file: BinaryIO) -> CodeType:
    return pys_assemble(pys_parse(file.readline), file.name)
