/// libpython types for D.
module dtypes.python;

struct PyVarObject {
    PyObject ob_base;
    size_t ob_size;
}

struct PyTypeObject {
    PyVarObject ob_base = {{1, null}, 0};
    const char* tp_name;
    size_t tp_basicsize;
    size_t tp_itemsize;
    void* tp_dealloc;
    size_t tp_vectorcall_offet;
    void* tp_getattr;
    void* tp_setattr;
    void* tp_as_async;
    void* tp_repr;
    void* tp_as_number;
    void* tp_as_sequence;
    void* tp_as_mapping;
    void* tp_hash;
    void* tp_call;
    void* tp_str;
    void* tp_getattro;
    void* tp_setattro;
    void* tp_as_buffer;
    ulong tp_flags;
    const char* tp_doc;
    void* tp_traverse;
    void* tp_clear;
    void* tp_richcompare;
    size_t tp_weaklistoffset;
    void* tp_iter;
    void* tp_iternext;
    PyMethodDef* tp_methods;
    void* tp_members;
    void* tp_getset;
    void* tp_base;
    void* tp_dict;
    void* tp_descr_get;
    void* tp_descr_set;
    size_t tp_dictoffset;
    void* tp_init;
    extern (C) PyObject* function(PyTypeObject*, size_t) tp_alloc;
    PyObject* function(PyTypeObject*, PyObject*, PyObject*) tp_new;
    void* tp_free;
    void* tp_is_gc;
    void* tp_bases;
    void* tp_mro;
    void* tp_cache;
    void* tp_subclasses;
    void* tp_weaklist;
    void* tp_del;
    uint tp_version_tag;
    void* tp_finalize;
    void* tp_vectorcall;

    this(const char* name, PyTypeObject *base = null) {
        tp_name = name;
        ob_base.ob_base.ob_type = base;
    }
}

struct PyObject {
    size_t ob_refcnt;
    PyTypeObject *ob_type;
}

alias PyCFunction = extern (C) PyObject* function(PyObject*, PyObject*);

struct PyMethodDef {
    const char *ml_name;
    PyCFunction ml_meth;
    int ml_flags = METH_NOARGS;
    const char* ml_doc;
}

struct PyModuleDef_Slot {
    int slot;
    void *value;
}

struct PyModuleDef_Base {
    PyObject ob_base;
    PyObject* function() m_init;
    size_t m_index;
    PyObject* m_copy;
}

struct PyModuleDef {
    PyModuleDef_Base m_base = {{1, null}};
    const char* m_name;
    const char* m_doc;
    size_t m_size;
    PyMethodDef *m_methods = null;
    PyModuleDef_Slot *m_slots = null;
    int function(PyObject*, int function(PyObject*, void*), void*) m_traverse;
    int function(PyObject*) m_clear;
    void function(void*) m_free;

    this(const char* name, const char* doc, int size = -1) {
        m_name = name;
        m_doc = doc;
        m_size = size;
    }
}

enum {
    Py_mod_create = 1,
    Py_mod_exec = 2,
}

enum {
    Py_TPFLAGS_DISALLOW_INSTANTIATION = 1 << 7,
    Py_TPFLAGS_BASETYPE = 1 << 10,
}

enum {
    METH_VARARGS = 1 << 0,
    METH_KEYWORDS = 1 << 1,
    METH_NOARGS = 1 << 2,
}

extern (C) {
    int PyType_Ready(PyTypeObject*);
    PyObject* PyType_GenericAlloc(PyTypeObject*, size_t);

    PyObject* PyModuleDef_Init(PyModuleDef*);
    int PyModule_AddObject(PyObject*, const char*, PyObject*);

    void PyErr_SetString(PyObject *type, const char *message);
    PyObject* PyExc_Exception;

    PyObject* PyUnicode_FromString(immutable char*);
}
