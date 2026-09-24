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
 * PYTHON_DYLIB, PY_VERSION, PROJECT_DIR, RUN_PY, and LOG_PATH are baked in by
 * install.sh at compile time, matching this machine's Python and project
 * location.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

/*
 * The usual way this fails is Homebrew deleting the Python the app was built
 * against (brew autoremove treats a dependency-only python@3.x as unused).
 * Without a dialog the app just never appears, so say what broke and how to
 * fix it. MOMITO_LAUNCHER_NO_ALERT skips the dialog, for tests.
 */
static int fail(const char *detail) {
    fprintf(stderr, "Momito launcher: %s\n", detail);

    char body[2048];
    snprintf(body, sizeof body,
             "Momito runs on Python " PY_VERSION ", and that Python is no "
             "longer on this Mac. A Homebrew cleanup usually removes it.\n\n"
             "To fix it, run these two commands in Terminal:\n\n"
             "brew install python@" PY_VERSION "\n"
             "cd \"%s\" && ./install.sh",
             PROJECT_DIR);
    fprintf(stderr, "%s\n", body);

    if (getenv("MOMITO_LAUNCHER_NO_ALERT")) return 1;
    CFStringRef message =
        CFStringCreateWithCString(NULL, body, kCFStringEncodingUTF8);
    CFUserNotificationDisplayAlert(0, kCFUserNotificationStopAlertLevel, NULL,
                                   NULL, NULL, CFSTR("Momito can't start"),
                                   message, CFSTR("OK"), NULL, NULL, NULL);
    if (message) CFRelease(message);
    return 1;
}

int main(int argc, char *argv[]) {
    freopen(LOG_PATH, "a", stdout);
    freopen(LOG_PATH, "a", stderr);

    char detail[1024];
    void *lib = dlopen(PYTHON_DYLIB, RTLD_NOW | RTLD_GLOBAL);
    if (!lib) {
        snprintf(detail, sizeof detail, "cannot load Python: %s", dlerror());
        return fail(detail);
    }
    int (*py_main)(int, char **) = dlsym(lib, "Py_BytesMain");
    if (!py_main) {
        snprintf(detail, sizeof detail, "no Py_BytesMain: %s", dlerror());
        return fail(detail);
    }
    char *py_argv[] = {argv[0], RUN_PY, NULL};
    return py_main(2, py_argv);
}
