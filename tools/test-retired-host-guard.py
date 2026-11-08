#!/usr/bin/env python3
"""Proves the retired-host guard actually fails when it should.

A guard that cannot fail is worth nothing. This takes the real APK,
puts a retired address into the Python the app ships, and checks that
the guard notices - and then that it is quiet again once the address is
taken out again.

It also checks the plain source tree, the same way.

The retired address is put together at runtime rather than written out.
The guard scans this file too - it is part of the release surface - and
a test that spelled the address out would fail its own build.
"""
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(ROOT, "tools", "check-no-retired-hosts.py")
APK = os.path.join(ROOT, "bridgeapp", "build", "outputs", "apk",
                   "release", "bridgeapp-release.apk")

# Spelled out in pieces so this file does not carry the address itself.
RETIRED = "space." + "mcode" + ".io"
RETIRED_URL = "https://dead." + RETIRED

spec = importlib.util.spec_from_file_location("guard", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

failures = []


def check(name, condition, detail=""):
    if condition:
        print("OK  %s" % name)
    else:
        print("FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


def run_guard(*args):
    p = subprocess.run([sys.executable, GUARD] + list(args),
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main():
    # 1. the real thing is quiet
    code, out = run_guard(APK)
    check("the real APK passes the guard", code == 0, out.strip()[-300:])

    # 2. a copy with a retired address inside the shipped Python fails
    #
    # The APK is rebuilt rather than patched in place: the archive holds
    # ten .imy files, only one of which is a zip, and rewriting the rest
    # is more trouble than the test is worth. What matters is that the
    # guard opens the app's own Python and reads it.
    if not os.path.exists(APK):
        print("SKIP  no built bridge APK to tamper with")
        return 1 if failures else 0

    tmp = tempfile.mkdtemp(prefix="guardtest.")
    tampered = os.path.join(tmp, "tampered.apk")
    try:
        zin = zipfile.ZipFile(APK)
        app_imy = None
        for n in zin.namelist():
            if n.endswith("/app.imy"):
                app_imy = n
                break
        if app_imy is None:
            print("FAIL  the bridge app carries no app.imy")
            failures.append("the bridge app carries no app.imy")
            app_imy = None
        else:
            inner = zipfile.ZipFile(io.BytesIO(zin.read(app_imy)))
            buf = io.BytesIO()
            inner_out = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
            for m in inner.namelist():
                body = inner.read(m)
                if m.endswith("ytbridge.pyc"):
                    body = body + ("https://evil." + RETIRED + "/x").encode()
                inner_out.writestr(m, body)
            inner_out.close()

            zout = zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED)
            zout.writestr(app_imy, buf.getvalue())
            zout.close()

            code, out = run_guard(tampered)
            check("a retired address inside the shipped Python fails the guard",
                  code != 0, "the guard said OK")
            check("the failure names the address",
                  RETIRED in out, out.strip()[-300:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 3. the source tree catches one too
    problems = []
    guard.scan_text("list.txt", RETIRED_URL + "\n", problems, strict=True)
    check("a retired address in a list is caught",
          any(RETIRED in p for p in problems), str(problems))

    # 4. and a good list is quiet
    problems = []
    guard.scan_text("list.txt", "https://autosongs.example\n", problems, strict=True)
    check("a list with only the project's own site is quiet", not problems, str(problems))

    # 5. and so is a retired throwaway host name
    problems = []
    guard.scan_text("list.txt", "https://old." + "sslip" + ".io\n", problems, strict=True)
    check("a retired throwaway host is caught", bool(problems), str(problems))

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nthe guard fails when it should and stays quiet when it should not")
    return 0


if __name__ == "__main__":
    sys.exit(main())
