import lili.python;

// automatically called by python on import to initialise the module
extern (C) public PyObject* PyInit__vm() {
    static module_def = PyModuleDef("_vm", null, 0);

    static PyMethodDef[] methods = [{}];
    static PyModuleDef_Slot[] slots = [{Py_mod_exec, &execute}, {}];

    module_def.m_methods = methods.ptr;
    module_def.m_slots = slots.ptr;

    auto vm_module = PyModuleDef_Init(&module_def);

    return vm_module;
}

// this is called after the module object is initialised
extern (C) int execute(PyObject *vm_module) {
    static accelerator_vm = PyTypeObject("DCrossVM");
    static PyMethodDef[] accelerator_vm_methods = [
        {"call", &accelerator_vm_call},
        {"cont", &accelerator_vm_cont},
        {"step", &accelerator_vm_step},
        {}
    ];
    accelerator_vm.tp_flags = Py_TPFLAGS_BASETYPE;
    accelerator_vm.tp_methods = accelerator_vm_methods.ptr;
    accelerator_vm.tp_alloc = &PyType_GenericAlloc;
    accelerator_vm.tp_new =
        (PyTypeObject *cls, PyObject *args, PyObject* kwargs) => cls.tp_alloc(cls, 0);

    if (PyType_Ready(&accelerator_vm) < 0)
        return -1;

    if (PyModule_AddObject(vm_module, "DCrossVM", cast(PyObject*) &accelerator_vm) < 0)
        return -1;

    return 0;
}

extern (C) PyObject* accelerator_vm_call(PyObject *self, PyObject *args) {
    return null;
}

extern (C) PyObject* accelerator_vm_cont(PyObject *self, PyObject *args) {
    return null;
}

extern (C) PyObject* accelerator_vm_step(PyObject *self, PyObject *args) {
    return null;
}
