/* Experiment only. No application imports this extension. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>

/* Evaluate at most 256 a values. Strict FP flags preserve Python operation order.
   round(raw_b) adds no candidate: it is always either floor or ceil for raw_b>=0. */
static PyObject *scan(PyObject *self, PyObject *args) {
    double t, d1, d2, error;
    long long start, stop, limit, best_a, best_b;
    if (!PyArg_ParseTuple(args, "dddLLLLLd", &t, &d1, &d2,
                          &start, &stop, &limit, &best_a, &best_b, &error)) return NULL;
    if (!isfinite(t) || !isfinite(d1) || !isfinite(d2) || d1 <= 0 || d2 <= 0 ||
        start < 0 || stop < start || stop - start > 256 || stop > 1000000000LL ||
        limit < -1 || limit > 1000000000LL || (limit >= 0 && stop > limit + 1) ||
        best_a < 0 || best_b < 0 || best_a > 1000000000LL || best_b > 1000000000LL ||
        isnan(error) || error < 0 || fabs(t / d1) > 1000000000.0 ||
        fabs(t / d2) > 1000000000.0) {
        PyErr_SetString(PyExc_ValueError, "Unsupported numerical batch bounds");
        return NULL;
    }
    Py_BEGIN_ALLOW_THREADS
    for (long long a = start; a < stop; ++a) {
        double rem = t - (double)a * d1;
        double raw = rem <= 0 ? 0 : rem / d2;
        long long lo = (long long)floor(raw), hi = (long long)ceil(raw);
        if (limit >= 0) {
            if (lo > limit - a) lo = limit - a;
            if (hi > limit - a) hi = limit - a;
        }
        for (int i = 0; i < (lo == hi ? 1 : 2); ++i) {
            long long b = i == 0 ? lo : hi;
            double e = fabs((double)a * d1 + (double)b * d2 - t);
            if (e < error - 1e-12 || (fabs(e - error) <= 1e-12 && a+b < best_a+best_b)) {
                best_a = a; best_b = b; error = e;
            }
        }
    }
    Py_END_ALLOW_THREADS
    return Py_BuildValue("LLd", best_a, best_b, error);
}
static PyMethodDef methods[] = {{"scan", scan, METH_VARARGS, "Bounded numerical scan."}, {NULL, NULL, 0, NULL}};
static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_optimizer_native_experiment", NULL, -1, methods};
PyMODINIT_FUNC PyInit__optimizer_native_experiment(void) { return PyModule_Create(&module); }
