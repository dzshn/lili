in := "./lili/_vm.d"
out := "./lili/_vm.so"

cc := if `which ldc2 2>/dev/null || true` != "" {
    "ldc2 -O3 --shared -L=-lpython3 " + in + " --of=" + out
} else if `which gdc 2>/dev/null || true` != "" {
    "gdc -O3 -fPIC -shared -Lpython3 " + in + " -o " + out
} else if `which dmd 2>/dev/null || true` != "" {
    "dmd -O -shared -L=-lpython3 " + in + " -of=" + out
} else {
    error("no suitable D compiler")
}

build-accelerator:
    {{ cc }}
    -rm -f lili/_vm.o
