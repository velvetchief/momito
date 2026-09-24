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
 * Two build modes:
 *
 * - Repo install (install.sh): PYTHON_DYLIB, PY_VERSION, PROJECT_DIR, RUN_PY,
 *   and LOG_PATH are absolute paths baked in at compile time, matching this
 *   machine's Python and project location. The installed app runs the repo
 *   checkout it was built from, so rerunning install.sh from a new location
 *   is the update path.
 *
 * - Release bundle (scripts/make_release.sh, with -DMOMITO_PACKAGED): no
 *   build machine or checkout path survives in the binary. Paths resolve at
 *   runtime from the running bundle — the Python dylib and run.py live in
 *   Contents/Resources, logs go to ~/Library/Logs/Momito — so the app keeps
 *   working after the checkout is deleted. The launcher also sets
 *   MOMITO_PACKAGED=1 in the process environment so the Python side
 *   (momito/paths.py) resolves its assets from the bundle too.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#ifndef MOMITO_PACKAGED

#ifndef PYTHON_DYLIB
#error "repo builds need -DPYTHON_DYLIB"
#endif
#ifndef PROJECT_DIR
#error "repo builds need -DPROJECT_DIR"
#endif
#ifndef RUN_PY
#error "repo builds need -DRUN_PY"
#endif
#ifndef LOG_PATH
#error "repo builds need -DLOG_PATH"
#endif

#else /* MOMITO_PACKAGED */

#ifndef PYTHON_DYLIB_RELPATH
#error "release builds need -DPYTHON_DYLIB_RELPATH, relative to Contents/Resources"
#endif

#define RELEASES_URL "https://github.com/velvetchief/momito/releases"

static char g_resources[2 * PATH_MAX]; /* .../Momito.app/Contents/Resources */
static char g_dylib[2 * PATH_MAX];     /* the bundled Python dylib */
static char g_run_py[2 * PATH_MAX];    /* the bundled run.py */
static char g_log[2 * PATH_MAX];       /* ~/Library/Logs/Momito/momito.log */

/*
 * Locate the Contents/Resources directory of the bundle this executable
 * belongs to. CFBundleCopyResourcesDirectoryURL is the supported answer; the
 * argv[0] walk covers everything the bundle API does not see, e.g. running
 * the bare binary without LaunchServices.
 */
static int resolve_resources(const char *argv0) {
    char candidate[2 * PATH_MAX];
    int have = 0;

    CFBundleRef bundle = CFBundleGetMainBundle();
    if (bundle) {
        CFURLRef res_url = CFBundleCopyResourcesDirectoryURL(bundle);
        if (res_url) {
            CFStringRef res_path =
                CFURLCopyFileSystemPath(res_url, kCFURLPOSIXPathStyle);
            if (res_path) {
                have = CFStringGetCString(res_path, candidate,
                                          sizeof candidate,
                                          kCFStringEncodingUTF8);
                CFRelease(res_path);
            }
            CFRelease(res_url);
        }
    }
    if (!have) {
        /* argv[0] ends in .../Contents/MacOS/<name>; the Resources directory
           is its parent's parent. argv[0] may be relative — realpath
           normalizes. */
        const char *last_slash = argv0 ? strrchr(argv0, '/') : NULL;
        if (!last_slash) return 1;
        snprintf(candidate, sizeof candidate, "%.*s/../Resources",
                 (int)(last_slash - argv0), argv0);
    }
    /* CFBundleCopyResourcesDirectoryURL can return a path relative to the
       process's working directory (observed when the binary is exec'd with a
       tmp cwd), and every consumer below — dlopen, run.py, PYTHONHOME —
       needs an absolute, cwd-independent path. One realpath covers both
       branches. */
    return realpath(candidate, g_resources) ? 0 : 1;
}

static void ensure_log_dir(const char *home) {
    /* ~/Library and ~/Library/Logs exist on a stock macOS, but create each
       level anyway so a trimmed HOME still gets a working log. mkdir on an
       existing directory just fails with EEXIST, which is fine. */
    char dir[2 * PATH_MAX];
    snprintf(dir, sizeof dir, "%s/Library", home);
    mkdir(dir, 0755);
    snprintf(dir, sizeof dir, "%s/Library/Logs", home);
    mkdir(dir, 0755);
    snprintf(dir, sizeof dir, "%s/Library/Logs/Momito", home);
    mkdir(dir, 0755);
}

#endif /* MOMITO_PACKAGED */

/*
 * The usual way this fails is Homebrew deleting the Python the app was built
 * against (repo installs). Release bundles can only lose their dylib by
 * being damaged in transit; either way, without a dialog the app just never
 * appears, so say what broke and how to fix it.
 * MOMITO_LAUNCHER_NO_ALERT skips the dialog, for tests.
 */
static int fail(const char *detail) {
    fprintf(stderr, "Momito launcher: %s\n", detail);

#ifdef MOMITO_PACKAGED
    char body[1024];
    snprintf(body, sizeof body,
             "Momito.app is missing its Python runtime, so the copy on disk "
             "is incomplete.\n\nDownload Momito again from\n%s",
             RELEASES_URL);
#else
    char body[2048];
    snprintf(body, sizeof body,
             "Momito runs on Python " PY_VERSION ", and that Python is no "
             "longer on this Mac. A Homebrew cleanup usually removes it.\n\n"
             "To fix it, run these two commands in Terminal:\n\n"
             "brew install python@" PY_VERSION "\n"
             "cd \"%s\" && ./install.sh",
             PROJECT_DIR);
#endif
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

static void redirect_logging(const char *log_path) {
    /* freopen closes the original stream when it fails, so only hand stderr
       over if stdout's redirect landed; a missing log must not take the
       app's own output down with it. */
    if (freopen(log_path, "a", stdout)) freopen(log_path, "a", stderr);
}

int main(int argc, char *argv[]) {
#ifdef MOMITO_PACKAGED
    (void)argc;
    if (resolve_resources(argv[0]) != 0)
        return fail("cannot locate the Momito.app bundle resources");
    snprintf(g_dylib, sizeof g_dylib, "%s/%s", g_resources,
             PYTHON_DYLIB_RELPATH);
    snprintf(g_run_py, sizeof g_run_py, "%s/run.py", g_resources);

    const char *home = getenv("HOME");
    if (!home || !*home) home = "/tmp";
    snprintf(g_log, sizeof g_log, "%s/Library/Logs/Momito/momito.log", home);
    ensure_log_dir(home);

    /* The Python side reads these. MOMITO_PACKAGED switches momito.paths to
       the bundle layout; PYTHONHOME pins the stdlib to the bundled runtime
       once the packager has shipped one (it sits at Resources/python as a
       plain prefix: python/lib/pythonX.Y/). */
    setenv("MOMITO_PACKAGED", "1", 1);
    struct stat st;
    char pyhome[2 * PATH_MAX];
    snprintf(pyhome, sizeof pyhome, "%s/python", g_resources);
    if (stat(pyhome, &st) == 0 && S_ISDIR(st.st_mode))
        setenv("PYTHONHOME", pyhome, 1);

    const char *dylib_path = g_dylib;
    const char *run_py_path = g_run_py;
    const char *log_path = g_log;
#else
    const char *dylib_path = PYTHON_DYLIB;
    const char *run_py_path = RUN_PY;
    const char *log_path = LOG_PATH;
#endif

    redirect_logging(log_path);

    char detail[1024];
    void *lib = dlopen(dylib_path, RTLD_NOW | RTLD_GLOBAL);
    if (!lib) {
        snprintf(detail, sizeof detail, "cannot load Python: %s", dlerror());
        return fail(detail);
    }
    int (*py_main)(int, char **) = dlsym(lib, "Py_BytesMain");
    if (!py_main) {
        snprintf(detail, sizeof detail, "no Py_BytesMain: %s", dlerror());
        return fail(detail);
    }
    char *py_argv[] = {argv[0], (char *)run_py_path, NULL};
    return py_main(2, py_argv);
}
