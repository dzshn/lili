import builtins
import sys
import traceback
from collections.abc import Iterable, Iterator
from types import CodeType, FunctionType
from typing import Any

import opcode

from lili.compat import PYC_MAGIC, Version, read_pyc
from lili.vm import CrossVM, UnresolvableOperation, UnsafeOperation

CSI = "\x1b["
RED = CSI + "31m"
GREEN = CSI + "32m"
YELLOW = CSI + "33m"
BLUE = CSI + "34m"
PURPLE = CSI + "35m"
CYAN = CSI + "36m"
RESET = CSI + "0m"


def fmt_const(obj: Any, _depth: int = 0) -> str:
    if _depth >= 8:
        return f"{RESET}…"

    if obj in (None, StopIteration, Ellipsis):
        return f"{YELLOW}{obj}"

    if isinstance(obj, (str, bytes)):
        return f"{GREEN}{obj!r}"

    if isinstance(obj, (int, float)):
        return f"{YELLOW}{obj}"

    if isinstance(obj, tuple):
        fmt = f"{RESET}("
        for i in obj:
            fmt += f"{fmt_const(i, _depth=_depth+1)}{RESET}, "
        fmt = fmt.strip() + ")"
        return fmt

    if isinstance(obj, CodeType):
        return (
            f"{BLUE}<code "
            f"{GREEN}{obj.co_name} "
            f"{RESET}({len(obj.co_code)} bytes, "
            f"{len(obj.co_consts)} consts, "
            f"{len(obj.co_names + obj.co_varnames)} names){BLUE}>"
        )

    return f"{RESET}{obj!r}"


def fmt_opcode(code: CodeType, op: int, arg: int, mark: str = "") -> str:
    fmt = f"{GREEN}[{mark}0x{op:0>2x}_{arg:0>2x}] {PURPLE}{opcode.opname[op]}"
    annotation = ""

    if op in opcode.hasname:
        annotation = code.co_names[arg]

    elif op in opcode.hasconst:
        annotation = fmt_const(code.co_consts[arg])

    elif op >= opcode.HAVE_ARGUMENT:
        annotation = str(arg)

    if annotation:
        fmt += f" {RESET}@ {annotation}"

    return fmt + RESET


def fmt_current(vm: CrossVM, show_address: bool = True) -> str:
    fmt = fmt_opcode(vm.code, *vm.current_opcode())
    if show_address:
        fmt = f"{BLUE}[0x{vm.counter:0>8x}]: " + fmt

    return fmt + RESET


def fmt_error(error: UnresolvableOperation) -> str:
    fmt = f"{BLUE}[- paused -]* {PURPLE}"
    if isinstance(error, UnsafeOperation):
        fmt += "(unsafe)"
    elif error.args:
        if isinstance(error.args[0], Exception):
            inner = error.args[0]
            fmt += f"({type(inner).__name__}: {inner})"
        else:
            fmt += f"({error.args[0]})"

    return fmt


def fmt_version(version: Version) -> str:
    fmt = ""
    for part in version:
        if isinstance(part, int):
            if fmt and fmt[-1].isdecimal():
                fmt += "."
            fmt += str(part)
        elif part == "alpha":
            fmt += "a"
        elif part == "beta":
            fmt += "b"
        elif part == "candidate":
            fmt += "rc"
        elif part == "final":
            break
    return fmt


def fmt_table(table: Iterable[tuple[str, Any]]) -> str:
    fmt = ""
    for k, v in table:
        if not isinstance(v, str):
            v = str(v)
        prefix = f"{PURPLE}{k:>12}: {RESET}"
        for line in v.splitlines():
            fmt += prefix + line + "\n"
            prefix = " " * 14
    return fmt.strip()


def get_eval_ctx(vm: CrossVM) -> dict[str, Any]:
    return {
        "vm": vm,
        "code": vm.code,
        "stack": vm.stack,
        "locals": vm.locals,
        "globals": vm.globals,
        "builtins": vm.builtins,
    }


def traverse_calls(vm: CrossVM) -> Iterator[CrossVM]:
    while True:
        yield vm
        if not vm.parent:
            break
        vm = vm.parent  # type: ignore # no Self?


def main() -> None:
    try:
        import readline

        readline.parse_and_bind("")
    except ModuleNotFoundError:
        pass

    filename = sys.argv[1]
    with open(filename, "rb") as f:
        header = f.read(4)
        f.seek(0)
        if header[2:4] == PYC_MAGIC:
            version, code = read_pyc(f)
            vm = CrossVM(code, version=version)
        else:
            vm = CrossVM(compile(f.read(), filename, "exec"))

    while True:
        prompt = f"{YELLOW}[0x{vm.counter:0>8x}]>{RESET} "
        try:
            if len(sys.argv) > 2:
                body = sys.argv.pop(2)
            else:
                body = input(prompt)
        except EOFError:
            print("^D")
            return
        except KeyboardInterrupt:
            print("^C")
            continue
        for expr in body.split(";"):
            expr = expr.strip()
            if not expr:
                continue

            cmd, *args = expr.split(" ")

            if cmd in {"step", "step!", "s", "s!"}:
                if err := vm.step(unsafe=cmd.endswith("!")):
                    print(fmt_error(err), fmt_current(vm))

            elif cmd in {"cont", "cont!", "c", "c!"}:
                try:
                    if err := vm.cont(unsafe=cmd.endswith("!")):
                        print(fmt_error(err), fmt_current(vm))
                    else:
                        print(f"{BLUE}[breakpoint]*", fmt_current(vm))
                except KeyboardInterrupt:
                    pass

            elif cmd in {"where", "w"}:
                mark = "* "
                for i, x in enumerate(traverse_calls(vm)):
                    print(f"{BLUE}[{mark}{i:>8}]:{RESET}", fmt_current(x))
                    mark = "  "

            elif cmd in {"dis", "i"}:
                try:
                    query = eval(" ".join(args) or "0", get_eval_ctx(vm))
                except Exception:
                    traceback.print_exc()
                    print(f"{RED}[- failed -]{RESET}")
                    return

                if isinstance(query, int):
                    for i, x in enumerate(traverse_calls(vm)):
                        if i == query:
                            obj = x
                            break
                elif isinstance(query, CodeType):
                    obj = CrossVM(query)
                elif isinstance(query, FunctionType):
                    obj = CrossVM(query.__code__)
                elif isinstance(query, CrossVM):
                    obj = query
                else:
                    print(f"{RED}[- failed -]{RESET} invalid object")
                    continue

                for i, op, arg in obj.opcodes():
                    mark = "   "
                    if i in obj.breakpoints:
                        if obj.breakpoints[i] is not None:
                            mark = f" {YELLOW}o {GREEN}"
                        else:
                            mark = f" {RED}o {GREEN}"
                    if i == obj.counter:
                        mark = " * "
                    print(
                        f"{BLUE}[0x{i:0>8x}]:",
                        fmt_opcode(obj.code, op, arg, mark),
                    )

            elif cmd in {"info", "f"}:
                code = vm.code
                location = f"{code.co_name} @ {code.co_filename}:{code.co_firstlineno}"
                print(
                    f"{BLUE}{'-- code --':^26}",
                    fmt_table(
                        [
                            ("location", location),
                            ("stack size", code.co_stacksize),
                            ("flags", code.co_flags),
                        ]
                    ),
                    fmt_table([("consts", "\n".join(map(fmt_const, code.co_consts)))]),
                    fmt_table(
                        [
                            (scope, "\n".join(getattr(code, "co_" + scope)))
                            for scope in ["names", "varnames", "freevars", "cellvars"]
                        ]
                    ),
                    f"{BLUE}{'-- vm --':^26}",
                    fmt_table([("version", fmt_version(vm.version))]),
                    sep="\n",
                )

            elif cmd in {"break", "b"}:
                if not args:
                    print(f"{RED}[- failed -]{RESET} missing index argument")
                    continue
                addr = args[0]
                condition = " ".join(args[1:])
                if condition:
                    try:
                        compile(condition, "::<>", "eval")
                    except SyntaxError:
                        print(f"{RED}[- failed -]{RESET} invalid condition")
                        continue
                if addr.startswith("0x"):
                    vm.toggle_breakpoint(int(addr, 16), condition or None)
                elif addr.isdecimal():
                    vm.toggle_breakpoint(int(addr), condition or None)

            elif cmd in {"allow", "a"}:
                if not args:
                    print(f"{RED}[- failed -]{RESET} missing opcode argument")
                    continue
                condition = " ".join(args[1:])
                if condition:
                    try:
                        compile(condition, "::<>", "eval")
                    except SyntaxError:
                        print(f"{RED}[- failed -]{RESET} invalid condition")
                        continue
                vm.unsafe_ignores[args[0]] = condition or None

            elif cmd == "disallow":
                for op_name in args:
                    del vm.unsafe_ignores[op_name]

            elif cmd in {"stack", "ps"}:
                if vm.stack:
                    mark = " ↓"
                    for i, x in reversed([*enumerate(vm.stack)]):
                        print(f"{BLUE}[{mark}{i:>8}]: {fmt_const(x)}{RESET}")
                        mark = "  "
                else:
                    print(f"{RED}stack is empty{RESET}")

            elif cmd in {"call", "l"}:
                op, arg = vm.current_opcode()
                try:
                    if op == opcode.opmap["CALL_FUNCTION"]:
                        vm = vm.call(arg)  # type: ignore
                    else:
                        argc = int(args[0]) if args else 0
                        vm = vm.call(argc)  # type: ignore
                except TypeError:
                    print(f"{RED}[- failed -]{RESET} not a python function")

            elif cmd in {"return", "r"}:
                if not vm.parent:
                    print(f"{RED}no outer frame{RESET}")
                vm = vm.return_call()  # type: ignore

            elif cmd == "push":
                try:
                    vm.stack.append(eval(" ".join(args), get_eval_ctx(vm)))
                except Exception:
                    traceback.print_exc()
                    print(f"{RED}[- failed -]{RESET}")

            elif cmd == "pop":
                for idx in args or ["-1"]:
                    print(vm.stack.pop(int(idx)))

            elif cmd == "builtin":
                if not args:
                    print(vm.builtins)
                    continue
                for name in args:
                    vm.builtins[name] = getattr(builtins, name)

            elif cmd in {"incr", "i"}:
                vm.counter = vm.next_opcode()

            elif cmd in {"bai", "bye", "exit", "quit", "q"}:
                return

            else:
                code_str = " ".join([cmd] + args)
                try:
                    compile(code_str, "::<>", "eval")
                except SyntaxError:
                    pass
                else:
                    code_str = "print(" + code_str + ")"

                try:
                    exec(code_str, get_eval_ctx(vm))
                except Exception:
                    traceback.print_exc()
                    print(f"{RED}[- failed -]{RESET}")


if __name__ == "__main__":
    main()
