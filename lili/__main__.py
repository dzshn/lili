import builtins
import opcode
import sys
import traceback
import types
from typing import Any
from lili.compat import PYC_MAGIC, read_pyc

from lili.vm import CrossVM


CSI = "\x1b["
RED = CSI + "31m"
GREEN = CSI + "32m"
YELLOW = CSI + "33m"
BLUE = CSI + "34m"
PURPLE = CSI + "35m"
CYAN = CSI + "36m"
RESET = CSI + "0m"


def fmt_current(vm: CrossVM, show_address: bool = True) -> str:
    op, arg = vm.current_opcode()

    fmt = ""
    if show_address:
        fmt += f"{BLUE}[0x{vm.counter:0>8x}]@ "

    fmt += (
        f"{GREEN}[0x{op:0>2x}_{arg:0>2x}] "
        f"{PURPLE}{opcode.opname[op]}"
    )
    annotation = ""

    if op in opcode.hasname:
        annotation = vm.code.co_names[arg]

    elif op in opcode.hasconst:
        annotation = repr(vm.code.co_consts[arg])

    elif op >= opcode.HAVE_ARGUMENT:
        annotation = str(arg)

    if annotation:
        fmt += f" {RESET}@ {annotation}"

    return fmt + RESET


def get_eval_ctx(vm: CrossVM) -> dict[str, Any]:
    return {
        "vm": vm,

        "code": vm.code,
        "stack": vm.stack,
        "locals": vm.locals,
        "globals": vm.globals,
        "builtins": vm.builtins,
    }


def traverse_calls(vm: CrossVM) -> list[CrossVM]:
    calls = []
    while True:
        calls.append(vm)
        if not vm.parent:
            break
        vm = vm.parent  # type: ignore # no Self?
    return calls


def main():
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

    on_break = True
    while True:
        if not on_break:
            try:
                if not vm.step():
                    continue
            except KeyboardInterrupt:
                pass
            print(f"{BLUE}[- paused -]*", fmt_current(vm))
            on_break = True

        prompt = f"{YELLOW}[0x{vm.counter:0>8x}]>{RESET} "
        try:
            expr = input(prompt)
        except EOFError:
            print("^D")
            return
        except KeyboardInterrupt:
            print("^C")
            return
        for i in expr.split(";"):
            i = i.strip()
            if not i:
                continue

            cmd, *args = i.split(" ")

            if cmd.removesuffix("!") in {"step", "s"}:
                if not vm.step(unsafe=cmd.endswith("!")):
                    continue
                print(f"{BLUE}[unresolved]*{RESET}", fmt_current(vm))

            elif cmd in {"show", "where", "w"}:
                mark = "* "
                for i, x in enumerate(traverse_calls(vm)):
                    print(f"{BLUE}[{mark}{i:>8}]:{RESET}", fmt_current(x))
                    mark = "  "

            elif cmd in {"cont", "c"}:
                on_break = False

            elif cmd in {"stack", "ps"}:
                if vm.stack:
                    for i, x in reversed([*enumerate(vm.stack)]):
                        print(f"{YELLOW}{i:>4} {PURPLE}{x}")
                    print(RESET)
                else:
                    print(f"{RED}stack is empty{RESET}")

            elif cmd == "call":
                op, arg = vm.current_opcode()
                try:
                    if op == opcode.opmap["CALL_FUNCTION"]:
                        vm = vm.call(arg)
                    else:
                        argc = int(args[0]) if args else 0
                        vm = vm.call(argc)
                except TypeError:
                    print(f"{RED}[- failed -]{RESET} not callable")

            elif cmd == "return":
                if not vm.parent:
                    print(f"{RED}no outer frame{RESET}")
                vm = vm.return_call()

            elif cmd == "push":
                try:
                    vm.stack.append(eval(" ".join(args), get_eval_ctx(vm)))
                except Exception:
                    traceback.print_exc()
                    print(f"{RED}[- failed -]{RESET}")

            elif cmd == "pop":
                for i in args or ["0"]:
                    print(vm.stack.pop(int(i)))

            elif cmd == "builtin":
                if not args:
                    print(vm.builtins)
                    continue
                for i in args:
                    vm.builtins[i] = getattr(builtins, i)

            elif cmd[0] in {"incr", "i"}:
                vm.counter += 2

            else:
                code = " ".join([cmd] + args)
                try:
                    compile(code, "::<>", "eval")
                except SyntaxError:
                    pass
                else:
                    code = "print(" + code + ")"

                try:
                    exec(code, get_eval_ctx(vm))
                except Exception:
                    traceback.print_exc()
                    print(f"{RED}[- failed -]{RESET}")


if __name__ == "__main__":
    main()
