# lili: tiny python bytecode debugger and emulator

![Screenshot](docs/screenshot_fib.png)

## Roadmap

- [ ] Backwards bytecode compatibility
    - [ ] Translate deleted opcodes, figure out what to do with conflicts
    - [ ] Patch `marshal`led data with missing `code` attributes
        - [x] `co_posonlyargcount`
        - [ ] ??
    - [x] Handle pre-3.6a2 opcodes (silly non fixed-width)
- [ ] Handle `EXTENDED_ARG`
- [ ] All 'em opcodes!! (47 of 127 for 3.10)
- [ ] Macros
- [ ] Document things (´；ω；\`)

## Install

Install with pip: (only requires python >= 3.9)

```sh
$ pip install git+https://github.com/dzshn/lili
# or `py -m pip` etc
```

## Commands

The following commands are recognised by `lili`. Text enclosed in `[]` is
optional, and text enclosed in `{}` means it's an required argument.

-   `s[tep][!]` : `step`, `s`

    Step over the next instruction. By default, only opcodes with no side
    effects will be executed unless the command ends with an exclamation mark.

-   `c[ont][!]` : `cont`, `c`

    Continuously execute (step over) instructions until a breakpoint is
    reached, or an opcode fails. `!` follows the same convention as `step`.

-   `w[here]` : `where`, `w`

    Display the current call stack and positions.

-   `d[is] [object]` : `dis`, `d`

    Disassemble and display a function or code object's bytecode. If no
    argument is given, disassemble the current frame. If the argument is an
    integer, disassemble the nth call frame.

-   `i[nfo]` : `info`, `i`

    Display info about the current code object and the VM.

-   `b[reak] {index} [condition]` : `break`, `b`

    Toggle or update a breakpoint at `index`. If a `condition` is given, the
    breakpoint will only be used if it evaluates to true.

-   `a[llow] {opcode} [condition]` : `allow`, `a`

    Mark an opcode as safe, optionally with a `condition`. The variables
    `stack` and `arg` are also available at when the condition is evaluated.

-   `disallow {opcode}`

    Remove a previously `allow`ed opcode.

-   `[cal]l [argc]` : `call`, `l`

    Call the function like `CALL_FUNCTION` and drop into it's frame.

-   `r[eturn]`

    Push top of stack into parent frame, then pop the current frame.

-   `push [expr]`

    Evaluate `expr` and push it into the stack.

-   `pop`

    Pop and discard a value from the stack.

-   `builtin [name…]`

    Insert a member from the `builtins` module into the VM's `builtins`, which
    is empty by default.

-   `q[uit]`

    Exit the debugger.
