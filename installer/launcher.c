/*
 * Momito.app launcher.
 *
 * Loads Python as a shared library and runs run.py inside THIS process,
 * instead of exec'ing the python binary. macOS attributes a process to the
 * bundle its executable lives in, so exec'ing python turns Momito into
 * "Python" everywhere: rocket in the Dock, "Python" in the menu bar, and
 * permission grants that don't stick to Momito. Keeping the interpreter
 * in-process makes the app genuinely Momito.app to the OS (same approach
 * py2app uses).
 *
 * PYTHON_DYLIB, RUN_PY, and LOG_PATH are baked in by install.sh at compile
 * time, matching this machine's Homebrew Python and project location.
 */
#include <dlfcn.h>
#include <stdio.h>

int main(int argc, char *argv[]) {
    freopen(LOG_PATH, "a", stdout);
    freopen(LOG_PATH, "a", stderr);

    void *lib = dlopen(PYTHON_DYLIB, RTLD_NOW | RTLD_GLOBAL);
    if (!lib) {
        fprintf(stderr, "Momito launcher: cannot load Python: %s\n", dlerror());
        return 1;
    }
    int (*py_main)(int, char **) = dlsym(lib, "Py_BytesMain");
    if (!py_main) {
        fprintf(stderr, "Momito launcher: no Py_BytesMain: %s\n", dlerror());
        return 1;
    }
    char *py_argv[] = {argv[0], RUN_PY, NULL};
    return py_main(2, py_argv);
}
