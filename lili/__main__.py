from __future__ import annotations

import builtins
import getopt
import marshal
import sys
import textwrap
import traceback
from collections.abc import Callable, Iterable
from types import CodeType, FunctionType
from typing import (
    Annotated,
    Any,
    ClassVar,
    Optional,
    Protocol,
    TypeVar,
    Union,
    cast,
    get_type_hints,
)

import opcode

import lili
from lili.assembler import read_pys
from lili.compat import MAGIC_NUMBER, PYC_MAGIC, CompilerFlags, Version, read_pyc
from lili.vm import CrossVM, UnresolvableOperation, UnsafeOperation

T = TypeVar("T", str, int)
# notifies handle_command an argument's string can't be empty
NotEmpty = Annotated[T, object()]


CSI = "\x1b["
RED = CSI + "31m"
GREEN = CSI + "32m"
YELLOW = CSI + "33m"
BLUE = CSI + "34m"
PURPLE = CSI + "35m"
CYAN = CSI + "36m"
REVERSE = CSI + "7m"
RESET = CSI + "0m"

USAGE = f"""\
lili {lili.__version__}

{BLUE}USAGE
    {PURPLE}lili {RESET}[flags] file            {YELLOW}Compile and debug script
    {PURPLE}lili {RESET}[flags] file [cmd...]   {YELLOW}Automatically run commands

{BLUE}FLAGS
    {PURPLE}-h, --help      {YELLOW}Display this message
    {PURPLE}-s, --assemble  {YELLOW}Parse file as human-readable bytecode
    {PURPLE}-b, --bytecode  {YELLOW}Parse file as raw bytecode (usually automatic)
    {PURPLE}--[no-]color    {YELLOW}Force usage of colors (on by default on terminals)
{RESET}\
"""


class Command(Protocol):
    __lili_command_names__: tuple[str, ...]

    @staticmethod
    def __call__(self: CommandHandler, *args: Union[str, int]) -> None:
        ...


class CommandError(Exception):
    pass


class CommandHandler:
    commands: ClassVar[dict[str, Command]] = {}
    command_set: ClassVar[set[Command]] = set()

    def __init_subclass__(cls) -> None:
        for base in cls.mro():
            if issubclass(base, CommandHandler):
                cls.commands |= base.commands
                cls.command_set |= base.command_set
                break

        for attr, value in cls.__dict__.items():
            for name in getattr(value, "__lili_command_names__", ()):
                cls.commands[name] = value
                cls.command_set.add(value)

    def _parse_int(self, string: str) -> Optional[int]:
        for i, j in [("0x", 16), ("0o", 8), ("0b", 2)]:
            if string.removeprefix("-").startswith(i):
                try:
                    return int(string, j)
                except ValueError:
                    return None
        if string.isdecimal():
            return int(string)
        return None

    def handle_command(self, name: str, arguments: list[str]) -> None:
        if name not in self.commands:
            self.fallback_command([name, *arguments])
            return

        arguments = arguments.copy()

        command = self.commands[name]
        type_hints = get_type_hints(command, include_extras=True)
        fn = cast(FunctionType, command)
        code = fn.__code__
        defaults = fn.__defaults__ or ()
        has_varargs = bool(code.co_flags & CompilerFlags.VARARGS)
        argc = code.co_argcount - 1  # don't include self
        if has_varargs:
            argc += len(arguments)
            var_arg_name = code.co_varnames[code.co_argcount]
            annotation = type_hints[var_arg_name]
            if annotation == NotEmpty[str] and not arguments:
                raise CommandError(f"expected at least one {var_arg_name}")

        command_args: list[Any] = []
        for i in range(argc):
            arg_name = code.co_varnames[min(i + 1, code.co_argcount)]
            required_type = type_hints[arg_name]
            if required_type is str or required_type == NotEmpty[str]:
                if i == argc - 1:
                    command_args.append(" ".join(arguments))
                    del arguments[:]
                else:
                    command_args.append(arguments.pop(0))
            elif required_type is int:
                if not arguments:
                    if i > argc - len(defaults) - 1:
                        break
                    raise CommandError(f"missing required argument {arg_name}")
                if (arg := self._parse_int(arguments[0])) is None:
                    raise CommandError(f"expected integer, but got {arguments[0]}")
                command_args.append(arg)
                arguments.pop(0)
            else:
                if arguments and (arg := self._parse_int(arguments[0])) is not None:
                    command_args.append(arg)
                    arguments.pop(0)
                elif i == argc - 1:
                    command_args.append(" ".join(arguments))
                    del arguments[:]
                else:
                    command_args.append(arguments.pop(0))
        if arguments:
            raise CommandError(f"unexpected argument: {' '.join(arguments)}")

        command(self, *command_args)

    def fallback_command(self, arguments: list[str]) -> None:
        ...


def command(*names: str) -> Callable[[Callable[..., None]], Command]:
    def decorator(fn: Callable[..., None]) -> Command:
        fn = cast(Command, fn)
        fn.__lili_command_names__ = names
        return fn

    return decorator


class Debugger(CommandHandler):
    def main(self) -> None:
        try:
            import readline
        except ModuleNotFoundError:
            pass
        else:
            self._readline = readline
            readline.parse_and_bind("tab: complete")
            readline.set_completer(self.complete)

        opts, args = getopt.getopt(
            sys.argv[1:],
            "bho:s",
            ["assemble", "bytecode", "color", "no-color", "help", "output="],
        )

        is_interactive = sys.stdout.isatty()

        mode = "auto"
        output = None
        self.use_color = is_interactive
        for opt, value in opts:
            if opt in {"-h", "--help"}:
                self.print(USAGE)
                sys.exit(0)
            if opt in {"-s", "--assemble"}:
                mode = "assemble"
            elif opt in {"-b", "--bytecode"}:
                mode = "bytecode"
            elif opt in {"-o", "--output"}:
                output = value
            elif opt == "--color":
                self.use_color = True
            elif opt == "--no-color":
                self.use_color = False

        if not args:
            self.print(USAGE, file=sys.stderr)
            self.print(f"{RED}ERROR:{RESET} missing file")
            sys.exit(1)

        filename = args.pop(0)
        with open(filename, "rb") as f:
            header = f.read(4)
            f.seek(0)
            if mode == "auto" and header[2:4] == PYC_MAGIC:
                mode = "bytecode"
            if mode == "assemble":
                code = read_pys(f)
                self.vm = CrossVM(code)
            elif mode == "bytecode":
                version, code = read_pyc(f)
                self.vm = CrossVM(code, version=version)
            else:
                self.vm = CrossVM(compile(f.read(), filename, "exec"))

        if output is not None:
            with open(output, "xb") as f:
                f.write(MAGIC_NUMBER)
                f.write(bytes(12))
                f.write(marshal.dumps(code))
            return

        for i in args:
            name, *cmd_args = i.split(" ")
            self.handle_command(name, cmd_args)

        if not is_interactive:
            return

        while True:
            try:
                for cmd in input(self.get_prompt()).split(";"):
                    name, *cmd_args = cmd.strip().split(" ")
                    self.handle_command(name, cmd_args)
            except EOFError:
                print("^D")
                break
            except KeyboardInterrupt:
                print("^C")
            except CommandError as e:
                self.print(f"{RED}[- failed -]:{RESET} {e}")
            except Exception:
                traceback.print_exc()

    def get_prompt(self) -> str:
        if not self.use_color:
            return f"[0x{self.vm.counter:0>8x}]> "
        return f"{YELLOW}[0x{self.vm.counter:0>8x}]>{RESET} "

    def print(self, *values: Any, **kwargs: Any) -> None:
        new_values: list[Any] = []
        for i in values:
            if isinstance(i, str) and not self.use_color:
                # continuously match <CSI><color>"m" and <CSI> and replace with nothing
                while (j := i.find(CSI)) != -1:
                    i = i[:j] + i[max(i.find("m", j), j) + 1 :]
            new_values.append(i)
        print(*new_values, **kwargs)

    def fallback_command(self, arguments: list[str]) -> None:
        code = " ".join(arguments)
        try:
            compile(code, "::<>", "eval")
        except SyntaxError:
            exec(code, get_eval_ctx(self.vm))
        else:
            print(eval(code, get_eval_ctx(self.vm)))

    def complete(self, text: str, state: int) -> Optional[str]:
        i = 0
        for name in self.commands:
            if name.startswith(text):
                if i == state:
                    return name + " "
                i += 1

        return None

    @command("help", "h", "?")
    def help(self, query: str = "") -> None:
        """Display help about debugger commands.

        Example: help cont!
        """

        if command := self.commands.get(query):
            self.print(fmt_command(command) + "\n")
            doc = command.__doc__ or ""
            doc = doc.strip()
            doc = doc.replace("Note:", f"{YELLOW}Note:{RESET}")
            doc = doc.replace("Example:", f"{YELLOW}Example:{PURPLE}")
            if "\n" in doc:
                first_line, doc = doc.split("\n", 1)
                doc = first_line + "\n" + textwrap.dedent(doc)
            self.print(doc)
            return

        for command in sorted(self.command_set, key=lambda c: c.__lili_command_names__):
            name, *aliases = command.__lili_command_names__
            if name == "meow":
                continue  # :3

            doc = (command.__doc__ or "").split("\n")[0].split(".")[0]
            signature = fmt_command(command)
            # str.center won't work because of the color escapes
            padding = " " * (32 - len(signature) + signature.count(CSI) * 5)
            self.print(f"{signature}{padding}{YELLOW} {doc}")

    @command("step", "s")
    def step(self, times: int = 1) -> None:
        """Step over the next instruction.

        Only opcodes with no side effects are executed. (see `step!`)
        """
        for i in range(times):
            if err := self.vm.step():
                self.print(fmt_error(err), fmt_current(self.vm))
                break

    @command("step!", "s!")
    def step_unsafe(self, times: int = 1) -> None:
        """Like step, but unsafe. May execute opcodes with side effects."""
        for i in range(times):
            if err := self.vm.step(unsafe=True):
                self.print(fmt_error(err), fmt_current(self.vm))
                break

    @command("cont", "c")
    def cont(self) -> None:
        """Step over instructions until a breakpoint is reached.

        Only executes opcodes with no side effects. (see `cont!`)
        """
        if err := self.vm.cont():
            self.print(fmt_error(err), fmt_current(self.vm))

    @command("cont!", "c!")
    def cont_unsafe(self) -> None:
        """Like cont, but unsafe. May execute opcodes with side effects."""
        if err := self.vm.cont(unsafe=True):
            self.print(fmt_error(err), fmt_current(self.vm))

    @command("where", "w")
    def where(self) -> None:
        """Display the current call stack and positions."""
        mark = "* "
        for i, x in enumerate(self.vm.traverse_calls()):
            self.print(f"{BLUE}[{mark}{i:>8}]:{RESET}", fmt_current(x))
            mark = "  "

    @command("meow")
    def meow(self, times: int = 1) -> None:
        """Please divert your attention into this cat.

          ／l、
        （ﾟ､ ｡ ７
          l、 ~ヽ
          じしf_,)ノ
        """
        for i in range(times):
            self.print("meow!")

    @command("dis", "d")
    def dis(self, obj: Union[str, int] = "") -> None:
        """Disassemble and display a function or object's bytecode."""
        if isinstance(obj, int):
            for i, x in enumerate(self.vm.traverse_calls()):
                if i == obj:
                    vm = x
                    break
            else:
                raise CommandError(f"call stack is too shallow ({i})")
        elif not obj:
            vm = self.vm
        else:
            query = eval(obj, get_eval_ctx(self.vm))

            if isinstance(query, CodeType):
                vm = CrossVM(query)
            elif isinstance(query, FunctionType):
                vm = CrossVM(query.__code__)
            elif isinstance(query, CrossVM):
                vm = query
            else:
                raise CommandError(f"not a code object or function: {query}")

        for i, op, arg in vm.opcodes():
            mark = "   "
            if i in vm.breakpoints:
                if vm.breakpoints[i] is not None:
                    mark = f" {YELLOW}o {GREEN}"
                else:
                    mark = f" {RED}o {GREEN}"

            if i == vm.counter:
                mark = " * "

            raw = vm.code.co_code[i : vm.next_opcode(i)]
            self.print(f"{BLUE}[0x{i:0>8x}]:", fmt_opcode(vm.code, op, arg, raw, mark))

    @command("info", "o")
    def info(self, obj: Union[str, int] = "") -> None:
        """Display info about the code and the VM."""
        if isinstance(obj, int):
            for i, x in enumerate(self.vm.traverse_calls()):
                if i == obj:
                    vm = x
                    break
        elif not obj:
            vm = self.vm
        else:
            query = eval(obj, get_eval_ctx(self.vm))
            if isinstance(query, CodeType):
                vm = CrossVM(query)
            elif isinstance(query, FunctionType):
                vm = CrossVM(query.__code__)
            elif isinstance(query, CrossVM):
                vm = query
            else:
                raise CommandError(f"not a code object or function: {query}")

        code = vm.code
        location = f"{code.co_name} @ {code.co_filename}:{code.co_firstlineno}"
        self.print(
            f"{BLUE}" + "-- code --".center(26),
            fmt_table(
                [
                    ("location", location),
                    ("stack size", code.co_stacksize),
                    ("flags", fmt_code_flags(code.co_flags)),
                ],
            ),
            fmt_table(
                [
                    (scope, "\n".join(getattr(code, "co_" + scope)))
                    for scope in ("names", "varnames", "freevars", "cellvars")
                ]
            ),
            fmt_table([("consts", "\n".join(map(fmt_const, code.co_consts)))]),
            f"{BLUE}" + "-- vm --".center(26),
            fmt_table(
                [
                    ("version", fmt_version(vm.version)),
                    ("implementation", "CPython"),
                ]
            ),
            sep="\n",
        )

    @command("break", "b")
    def break_(self, location: int, condition: str = "") -> None:
        """Toggle a breakpoint at location.

        If a condition is given, the breakpoint will only trigger if it
        evaluates to true.

        Example: break 0x4c x > 128
        """
        if condition:
            compile(condition, "::<>", "eval")  # let SyntaxError propragate

        self.vm.toggle_breakpoint(location, condition or None)

    @command("save")
    def save(self) -> None:
        """Save the current stack, locals and globals. Restore using restore."""
        self.vm.save()

    @command("restore")
    def restore(self, entry: int = 1) -> None:
        self.vm.restore(entry)

    @command("allow", "a")
    def allow(self, opcode: str, condition: str = "") -> None:
        """Mark an opcode as safe."""
        if condition:
            compile(condition, "::<>", "eval")

        self.vm.unsafe_ignores[opcode] = condition or None

    @command("disallow")
    def disallow(self, *opcodes: NotEmpty[str]) -> None:
        """Unmark an opcode as safe."""
        for op in opcodes:
            if op in self.vm.unsafe_ignores:
                del self.vm.unsafe_ignores[op]

    @command("stack", "ps")
    def stack(self) -> None:
        """Display the current stack."""
        if not self.vm.stack:
            self.print(f"{RED}stack is empty")
            return

        mark = " ↓"
        for i, x in reversed([*enumerate(self.vm.stack)]):
            self.print(f"{BLUE}[{mark}{i:>8}]: {fmt_const(x)}")
            mark = "  "

    @command("call", "l")
    def call(self, argc: int = 0) -> None:
        """Call function and drop into it's frame."""
        op, arg = self.vm.current_opcode()
        try:
            self.vm = self.vm.call()
        except TypeError:
            raise CommandError("not a python function")

    @command("return", "r")
    def return_(self) -> None:
        """Push top of stack into outer frame and pop the current frame."""
        if self.vm.parent is None:
            raise ValueError("no outer call")

        self.vm = self.vm.call()

    @command("push")
    def push(self, expr: str) -> None:
        """Push a value into the stack."""
        self.vm.stack.append(eval(expr, get_eval_ctx(self.vm)))

    @command("pop")
    def pop(self, *indices: int) -> None:
        """Pop and discard a value from the stack."""
        if not indices:
            indices = (-1,)
        for i in indices:
            self.print(fmt_const(self.vm.stack.pop(i)))

    @command("builtin")
    def builtin(self, *names: NotEmpty[str]) -> None:
        """Insert a builtin into the VM's builtins.

        The `builtins` scope is treated like `globals`, but can't be assigned.
        """
        for name in names:
            self.vm.builtins[name] = getattr(builtins, name)

    @command("incr", "i")
    def incr(self, count: int = 1) -> None:
        """Increment the instruction counter.

        Note: count is the opcode count, not bytes.
        """
        for i in range(count):
            self.vm.counter = self.vm.next_opcode()

    @command("quit", "q", "bai", "bye", "exit")
    def quit(self) -> None:
        """Exit the debugger."""
        sys.exit(0)


def fmt_command(command: Command) -> str:
    name, *aliases = command.__lili_command_names__
    fn = cast(FunctionType, command)
    code = fn.__code__
    defaults = fn.__defaults__ or ()
    has_varargs = bool(code.co_flags & CompilerFlags.VARARGS)
    argc = code.co_argcount
    if has_varargs:
        argc += 1
    args = code.co_varnames[1:argc]
    fmt = name
    for alias in aliases:
        if alias in fmt:
            common = fmt.replace(alias, "", 1)
            fmt = fmt.replace(common, f"{BLUE}[{common}]{PURPLE}")
        else:
            fmt += f", {alias}"

    fmt += f" {RESET}"
    for i, arg in enumerate(args):
        if i > argc - len(defaults) - 2:
            fmt += f"[{arg}] "
        elif has_varargs and i == argc - 2:
            fmt += f"[{arg}..]"
        else:
            fmt += f"{arg} "

    return PURPLE + fmt


def fmt_const(obj: Any, *, _depth: int = 0) -> str:
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


def fmt_opcode(code: CodeType, op: int, arg: int, raw: bytes, mark: str = "") -> str:
    fmt = f"{GREEN}[{mark}0x{raw.hex('_')}] {PURPLE}{opcode.opname[op]}"
    annotation = ""

    if op in opcode.hasname:
        annotation = code.co_names[arg]

    elif op in opcode.hasconst:
        annotation = fmt_const(code.co_consts[arg])

    elif op in opcode.hasjabs:
        annotation = f"0x{arg*2:0>8x}"

    elif op in opcode.hasjrel:
        annotation = f"+ 0x{arg*2:0>8x}"

    elif op >= opcode.HAVE_ARGUMENT:
        annotation = str(arg)

    if annotation:
        fmt += f" {RESET}@ {annotation}"

    return fmt + RESET


def fmt_current(vm: CrossVM, show_address: bool = True) -> str:
    raw = vm.code.co_code[vm.counter : vm.next_opcode()]
    fmt = fmt_opcode(vm.code, *vm.current_opcode(), raw)
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


def fmt_code_flags(flags: int) -> str:
    fmt = ""
    for i in range(32):
        flag = 1 << i
        if flags & flag:
            if name := CompilerFlags(flag).name:
                fmt += YELLOW + name
            else:
                fmt += f"{YELLOW}UNKNOWN {PURPLE}(1 << {i})"
            fmt += f"{RESET} | "
    return fmt.strip("| ") or f"{YELLOW}0"


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


# necessary for package script
def main() -> None:
    Debugger().main()


if __name__ == "__main__":
    Debugger().main()
