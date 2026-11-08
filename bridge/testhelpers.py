"""Shared helpers for the bridge's tests.

The tests that exercise a download put a fake yt-dlp on PATH and let
the bridge find it there. The fake is a shell script, because that is
the simplest thing that can behave like yt-dlp: read the arguments,
print a search result, write a file.

On Linux and macOS that works as it is. On Windows it does not, and
the failure looks like a bug in the bridge rather than a bug in the
test:

    shutil.which("yt-dlp") only finds files whose extension is in
    PATHEXT, and a file called "yt-dlp" with no extension is not one
    of those. So the bridge never finds the fake, the real yt-dlp
    never runs, and the test fails with

        search failed: search returned nothing

which says nothing about the code under test.

So on Windows the fake is installed as "yt-dlp.cmd", which PATHEXT
does include, and that file runs the same shell script through bash.
Windows runs a .cmd file through the command interpreter by itself, so
the bridge's subprocess.run([...]) needs no change - and the
arguments arrive at the script exactly as they were passed, including
paths with spaces and backslashes.

The tests keep their own script bodies. This module only decides how
to put one on PATH so the bridge can find it.
"""

import os
import shutil
import stat
import sys


def _is_windows():
    return os.name == "nt"


def find_bash():
    """The bash to run a fake with, or None if there is none.

    The tests only need this on Windows, where a .cmd file has to hand
    the work to a shell. Git for Windows is the usual way to get one.
    """
    found = shutil.which("bash")
    if found:
        return found
    for candidate in (r"C:\Program Files\Git\bin\bash.exe",
                      r"C:\Program Files\Git\usr\bin\bash.exe",
                      r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if os.path.exists(candidate):
            return candidate
    return None


def make_stub(directory, name, script):
    """Put a fake program on PATH and return the file that was written.

    `name` is the program name the bridge looks for ("yt-dlp") and
    `script` is the shell script that becomes the fake.

    The script is always written as "<name>.sh" as well, because a
    script may want to run another one - "python -m pip" has to reach
    the pip fake - and the only way to say "the one next to me" that
    works on both platforms is "$(dirname "$0")/other.sh".

    On POSIX the fake is the script itself, made executable. On Windows
    it is a .cmd file next to the script, and the .cmd runs the script
    through bash.

    Returns the path that was written, so a test can check it or
    report it.
    """
    os.makedirs(directory, exist_ok=True)
    script_path = os.path.join(directory, name + ".sh")
    # Newlines are written as they are. A CRLF shebang line makes bash
    # say "bad interpreter", and the script does nothing at all.
    with open(script_path, "w", newline="\n") as handle:
        handle.write(script)

    if not _is_windows():
        stub = os.path.join(directory, name)
        with open(stub, "w", newline="\n") as handle:
            handle.write(script)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR | stat.S_IXGRP |
                 stat.S_IXOTH)
        return stub

    bash = find_bash()
    if not bash:
        raise RuntimeError(
            "These tests need bash on Windows, because a fake program "
            "has to be a .cmd file and a .cmd file has to run through a "
            "shell. Install Git for Windows, which brings bash with it.")

    # The .cmd is written with CRLF, because cmd.exe is what reads it.
    stub = os.path.join(directory, name + ".cmd")
    with open(stub, "w", newline="\r\n") as handle:
        handle.write("@echo off\r\n")
        # %~dp0 is the folder this file is in. It has to be written as
        # %%~dp0 here, because this line is a %-format string.
        handle.write('"%s" "%%~dp0%s.sh" %%*\r\n' % (bash, name))
    return stub


def stub_on_path(directory, name, script, path_env=None):
    """Make a fake program and put its directory at the front of PATH.

    `path_env` is the environment to change - the tests pass their own
    copy, so they do not change the environment of the process they
    run in.
    """
    stub = make_stub(directory, name, script)
    if path_env is None:
        path_env = os.environ
    path_env["PATH"] = directory + os.pathsep + path_env.get("PATH", "")
    return stub


def skip_without_bash(test_name=None):
    """True when the test cannot run here, and why.

    A test that needs a fake program on Windows needs bash to put it
    there. Without it the test is skipped rather than failed: a
    missing shell is a missing tool, not a broken product.
    """
    if not _is_windows():
        return None
    if find_bash():
        return None
    return ("bash is not installed, and this test needs it to put a fake "
            "yt-dlp on PATH for the bridge to find. Git for Windows "
            "brings bash with it.")
