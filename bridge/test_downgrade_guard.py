#!/usr/bin/env python3
"""The collision guard: a newer local bridge is never overwritten.

The legacy host still publishes an old bridge that carries the same version
number the previous local build had, and the desktop launchers used to put
whatever they fetched straight over the local copy - first fetch and every
start. These tests pin the fixed behaviour:

* bridge/ytbridge.py: it declares a version, the default self-update source
  is exactly https://autosongs.example/ytbridge.py, and self_update refuses a
  remote that is not newer (state "current", file untouched).
* The windows_Linux_Bridge launchers (.cmd and .sh) and both GUI
  implementations fetch from autosongs.example only, and replace a local
  ytbridge.py only with a strictly newer copy - the first fetch (nothing
  installed) still installs whatever valid copy answers.

Run with:  py -3 test_downgrade_guard.py
"""
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WL = os.path.join(ROOT, "windows_Linux_Bridge")
GUI = os.path.join(WL, "gui")
BRIDGE_PY = os.path.join(HERE, "ytbridge.py")

STUB = '''# fake bridge for the downgrade guard test
BRIDGE_VERSION = "%s"
def make_server(*a, **kw):
    raise NotImplementedError
'''

FAILED = []


def ps_quote(path):
    """Single-quote a Windows path for use inside a sh command line."""
    return "'" + str(path).replace("'", "'\\''") + "'"


def check(name, condition, detail=""):
    if condition:
        print("   OK %s" % name)
    else:
        print("   FAIL %s %s" % (name, detail))
        FAILED.append(name)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Publisher(http.server.BaseHTTPRequestHandler):
    payload = b""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/x-python")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *a):
        pass


def serve(payload):
    port = free_port()
    Publisher.payload = payload
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Publisher)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode(errors="replace")


def post(url):
    req = urllib.request.Request(url, data=b"{}", method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()


# ------------------------------------------------------------- static rules
def test_static():
    print("== static expectations")
    src = open(BRIDGE_PY, encoding="utf-8").read()
    # The version moves with every release, so the test reads it from the
    # bridge rather than repeating it here - a repeated number is a second
    # place to forget to change.
    import ytbridge
    check("ytbridge declares its version",
          ('BRIDGE_VERSION = "%s"' % ytbridge.BRIDGE_VERSION) in src,
          ytbridge.BRIDGE_VERSION)
    check("default self-update URL is autosongs.example/ytbridge.py",
          re.search(r'_UPDATE_URLS_DEFAULT = \[\s*"https://autosongs\.org/ytbridge\.py"\s*\]', src))

    legacy = re.compile(r"sslip\.io|space\.mcode\.io|space\.minimax\.io|104\.223\.108\.15")
    singular = re.compile(r"autosong([^s]|$)", re.I)
    for rel in ["windows_Linux_Bridge/autosongs-bridge.cmd",
                "windows_Linux_Bridge/autosongs-bridge.sh",
                "windows_Linux_Bridge/gui/autosongs_bridge_app.py",
                "windows_Linux_Bridge/gui/autosongs_bridge_gui.py"]:
        text = open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8").read()
        check("%s: no legacy release hosts" % rel, not legacy.search(text),
              legacy.search(text).group(0) if legacy.search(text) else "")
        check("%s: no singular autosong tokens" % rel, not singular.search(text))
    check("ytbridge.py: no legacy release hosts in defaults", not legacy.search(src))
    check("ytbridge.py: no singular autosong tokens", not singular.search(src))
    for rel in ["windows_Linux_Bridge/autosongs-bridge.cmd",
                "windows_Linux_Bridge/autosongs-bridge.sh",
                "windows_Linux_Bridge/gui/autosongs_bridge_app.py",
                "windows_Linux_Bridge/gui/autosongs_bridge_gui.py"]:
        text = open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8").read()
        check("%s: fetches autosongs.example" % rel, "autosongs.example" in text)


# --------------------------------------------------------- ytbridge.update
def test_ytbridge_refuses_older():
    print("== the bridge itself refuses an older published copy")
    tmp = tempfile.mkdtemp(prefix="guard_bridge_")
    live = os.path.join(tmp, "ytbridge.py")
    shutil.copy2(BRIDGE_PY, live)
    work = os.path.join(tmp, "downloads")
    os.makedirs(work, exist_ok=True)

    payload = (STUB % "1.3.23").encode("utf-8")
    srv, pub_port = serve(payload)

    port = free_port()
    env = dict(os.environ)
    env["YTBRIDGE_UPDATE_URLS"] = "http://127.0.0.1:%d/ytbridge.py" % pub_port
    log = open(os.path.join(tmp, "bridge.log"), "wb")
    proc = subprocess.Popen([sys.executable, live, "--port", str(port),
                             "--workdir", work],
                            stdout=log, stderr=subprocess.STDOUT, env=env)
    base = "http://127.0.0.1:%d" % port
    try:
        for _ in range(60):
            try:
                get(base + "/health")
                break
            except Exception:
                time.sleep(0.2)
        health = json.loads(get(base + "/health"))
        # The version moves with every release, so it is read from the
        # bridge rather than written down here.
        import ytbridge
        running = ytbridge.BRIDGE_VERSION
        check("the bridge starts as %s" % running, health["version"] == running, health)

        answer = json.loads(post(base + "/update"))
        check("the update refuses the older remote",
              answer.get("state") == "current" and answer.get("remote") == "1.3.23", answer)
        time.sleep(1.0)
        on_disk = open(live, encoding="utf-8").read()
        check("the file on disk is still %s" % running,
              ('BRIDGE_VERSION = "%s"' % running) in on_disk)
        check("no backup/downgrade artefacts", not os.path.exists(live + ".bak"))
        still = json.loads(get(base + "/health"))
        check("the bridge is still up as %s" % running, still["version"] == running)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        log.close()
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------- GUIs
def run_gui_cases(mod, name):
    tmp = tempfile.mkdtemp(prefix="guard_gui_")
    bridge = os.path.join(tmp, "ytbridge.py")
    srv, port = serve(b"")
    base = "http://127.0.0.1:%d" % port
    logs = []
    log = logs.append
    old_dir, old_bridge, old_hosts = mod.DIR, mod.BRIDGE, mod.HOSTS
    mod.DIR, mod.BRIDGE, mod.HOSTS = tmp, bridge, [base]
    try:
        # first fetch installs what answers
        Publisher.payload = (STUB % "1.3.24").encode()
        check("%s: first fetch installs the core" % name, mod.fetch_bridge(log) is True)
        check("%s: installed file is 1.3.24" % name,
              'BRIDGE_VERSION = "1.3.24"' in open(bridge, encoding="utf-8").read())

        # older remote never overwrites
        before = open(bridge, encoding="utf-8").read()
        Publisher.payload = (STUB % "1.3.23").encode()
        check("%s: older remote is refused" % name, mod.fetch_bridge(log) is False)
        check("%s: local copy untouched" % name, open(bridge, encoding="utf-8").read() == before)

        # version-less remote never overwrites
        Publisher.payload = b"x\ndef make_server(*a):\n    pass\n"
        check("%s: version-less remote is refused" % name, mod.fetch_bridge(log) is False)
        check("%s: still untouched" % name, open(bridge, encoding="utf-8").read() == before)

        # newer remote updates
        Publisher.payload = (STUB % "1.3.99").encode()
        check("%s: newer remote is installed" % name, mod.fetch_bridge(log) is True)
        check("%s: file is now 1.3.99" % name,
              'BRIDGE_VERSION = "1.3.99"' in open(bridge, encoding="utf-8").read())

        # not a bridge at all
        os.remove(bridge)
        Publisher.payload = b"<html>404</html>"
        check("%s: a page is not a bridge" % name, mod.fetch_bridge(log) is False)
        check("%s: nothing was written" % name, not os.path.exists(bridge))
    finally:
        mod.DIR, mod.BRIDGE, mod.HOSTS = old_dir, old_bridge, old_hosts
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


def test_guis():
    print("== GUI implementations' fetch_bridge")
    sys.path.insert(0, GUI)
    for fname in ("autosongs_bridge_app", "autosongs_bridge_gui"):
        try:
            mod = __import__(fname)
        except Exception as exc:  # tkinter/pystray missing: still test logic
            print("   SKIP %s cannot be imported (%s)" % (fname, exc))
            continue
        run_gui_cases(mod, fname)


# ------------------------------------------------------------ launchers
PATHFIX = '''
import os, subprocess, sys
def fix(a):
    if a.startswith("/tmp/") and os.environ.get("TEMP"):
        return os.path.join(os.environ["TEMP"], a[len("/tmp/"):])
    return a
# subprocess.call (not os.execv) so the child's exit code reaches the
# caller; stdin (the launcher's heredoc script) is inherited unchanged.
sys.exit(subprocess.call([sys.executable] + [fix(a) for a in sys.argv[1:]]))
'''

CURL_PROXY = '''
import os, sys, urllib.request
args = sys.argv[1:]
url = None
out = None
i = 0
while i < len(args):
    a = args[i]
    if a == "-o":
        out = args[i + 1]
        i += 2
        continue
    if a.startswith("--max-time") or a == "-w":
        i += 2
        continue
    if a.startswith("-"):
        i += 1
        continue
    url = url or a
    i += 1
if out and out.startswith("/tmp/"):
    # MSYS sees %TEMP% mounted at /tmp; native python does not.
    out = os.path.join(os.environ.get("TEMP", "/tmp"), out[len("/tmp/"):])
try:
    d = os.path.dirname(out)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = resp.read()
    if out:
        with open(out, "wb") as fh:
            fh.write(data)
except Exception:
    sys.exit(22)
'''


def run_sh_case(tmp, home, port_or_url):
    src = open(os.path.join(WL, "autosongs-bridge.sh"), encoding="utf-8").read()
    url = port_or_url if isinstance(port_or_url, str) else "http://127.0.0.1:%d" % port_or_url
    src = src.replace("https://autosongs.example", url)
    src = src.replace('exec "$PY" "$BRIDGE" --pair "$@"', 'echo WOULD-EXEC "$BRIDGE"')
    script = os.path.join(tmp, "run.sh")
    with open(script, "w", newline="\n") as fh:
        fh.write(src)
    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    # Git-Bash's MSYS runtime rewrites a Windows HOME into /tmp/... paths
    # that native tools (python, MinGW curl) cannot open. Real machines run
    # this launcher under POSIX /home paths with POSIX tools; here the
    # shims translate those paths back so the test exercises the launcher's
    # own logic (fetch loop, validation, version guard, mv) unchanged.
    pathfix = os.path.join(tmp, "pathfix.py")
    with open(pathfix, "w", newline="\n") as fh:
        fh.write(PATHFIX)
    proxy = os.path.join(tmp, "curl_proxy.py")
    with open(proxy, "w", newline="\n") as fh:
        fh.write(CURL_PROXY)
    shim = os.path.join(bin_dir, "python3")
    with open(shim, "w", newline="\n") as fh:
        fh.write('#!/bin/sh\nexec py -3 %s "$@"\n' % ps_quote(pathfix))
    os.chmod(shim, 0o755)
    with open(os.path.join(bin_dir, "curl"), "w", newline="\n") as fh:
        fh.write('#!/bin/sh\nexec py -3 %s "$@"\n' % ps_quote(proxy))
    os.chmod(os.path.join(bin_dir, "curl"), 0o755)
    env = dict(os.environ)
    env["HOME"] = home
    env["PATH"] = bin_dir + os.pathsep + env["PATH"]
    argv = ["sh"] + (["-x"] if os.environ.get("GUARD_TRACE") else []) + [script]
    r = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=180)
    if os.environ.get("GUARD_TRACE"):
        sys.stderr.write((r.stdout or "")[-4000:] + "\n" + (r.stderr or "")[-4000:] + "\n")
    return r


def launcher_version(home):
    p = os.path.join(home, ".autosongs", "ytbridge.py")
    if not os.path.exists(p):
        return None
    m = re.search(r'^BRIDGE_VERSION = "([^"]+)"', open(p, encoding="utf-8").read(), re.M)
    return m.group(1) if m else "no-version"


def local_stub(home, version):
    d = os.path.join(home, ".autosongs")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "ytbridge.py"), "w", newline="\n") as fh:
        fh.write(STUB % version)


def run_cmd_case(tmp, home, port_or_url):
    # newline="" keeps the file's CRLF endings: cmd.exe only finds the
    # batch labels (:try_host, :remote_is_newer) in CRLF files, and the
    # test must exercise exactly what ships.
    src = open(os.path.join(WL, "autosongs-bridge.cmd"), encoding="utf-8", newline="").read()
    url = port_or_url if isinstance(port_or_url, str) else "http://127.0.0.1:%d" % port_or_url
    src = src.replace("https://autosongs.example", url)
    src = src.replace('%PY% "%BRIDGE%" --pair %*', 'echo WOULD-EXEC %BRIDGE%')
    src = re.sub(r"(?m)^([ \t]*)pause[ \t]*\r?$", r"\1rem pause\r", src)
    script = os.path.join(tmp, "run.cmd")
    with open(script, "w", newline="") as fh:
        fh.write(src)
    env = dict(os.environ)
    env["USERPROFILE"] = home
    trace = bool(os.environ.get("GUARD_TRACE"))
    r = subprocess.run(["cmd", "/c", script] if not trace else ["cmd", "/c", script],
                       capture_output=True, text=True, env=env, timeout=180)
    if trace:
        sys.stderr.write("CMD %s rc=%s\nSTDOUT:%s\nSTDERR:%s\n" % (
            home, r.returncode, (r.stdout or "")[-3000:], (r.stderr or "")[-3000:]))
    return r


def test_launchers(kind, runner):
    print("== %s launcher" % kind)
    srv, port = serve((STUB % "1.3.24").encode("utf-8"))
    base = "http://127.0.0.1:%d" % port
    dead = free_port()
    try:
        # A) first fetch installs the core
        tmp = tempfile.mkdtemp(prefix="guard_%s_" % kind)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        r = runner(tmp, home, base)
        check("%s: first fetch exits 0" % kind, r.returncode == 0, r.stderr[-300:])
        check("%s: first fetch installs 1.3.24" % kind, launcher_version(home) == "1.3.24")
        check("%s: runs the bridge afterwards" % kind, "WOULD-EXEC" in r.stdout, r.stdout[-300:])
        shutil.rmtree(tmp, ignore_errors=True)

        # B) older remote never overwrites a newer local copy
        tmp = tempfile.mkdtemp(prefix="guard_%s_" % kind)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        local_stub(home, "1.3.24")
        Publisher.payload = (STUB % "1.3.23").encode("utf-8")
        r = runner(tmp, home, base)
        check("%s: downgrade attempt exits 0" % kind, r.returncode == 0, r.stderr[-300:])
        check("%s: local 1.3.24 survives remote 1.3.23" % kind,
              launcher_version(home) == "1.3.24", launcher_version(home))
        shutil.rmtree(tmp, ignore_errors=True)

        # C) newer remote updates
        tmp = tempfile.mkdtemp(prefix="guard_%s_" % kind)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        local_stub(home, "1.3.23")
        Publisher.payload = (STUB % "1.3.99").encode("utf-8")
        r = runner(tmp, home, base)
        check("%s: upgrade installs 1.3.99" % kind, launcher_version(home) == "1.3.99",
              launcher_version(home))
        shutil.rmtree(tmp, ignore_errors=True)

        # D) network dead, local stays
        tmp = tempfile.mkdtemp(prefix="guard_%s_" % kind)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        local_stub(home, "1.3.24")
        r = runner(tmp, home, dead)
        check("%s: dead network exits 0 with a local copy" % kind, r.returncode == 0,
              r.stdout[-300:])
        check("%s: dead network keeps 1.3.24" % kind, launcher_version(home) == "1.3.24")
        shutil.rmtree(tmp, ignore_errors=True)

        # E) network dead, nothing here -> fail like before
        tmp = tempfile.mkdtemp(prefix="guard_%s_" % kind)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        r = runner(tmp, home, dead)
        check("%s: no copy and no network is an error" % kind, r.returncode != 0)
        shutil.rmtree(tmp, ignore_errors=True)
    finally:
        srv.shutdown()


def main():
    test_static()
    test_ytbridge_refuses_older()
    test_guis()
    test_launchers("sh", run_sh_case)
    if os.name == "nt":
        test_launchers("cmd", run_cmd_case)
    else:
        print("== cmd launcher\n   SKIP not on Windows")
    print()
    if FAILED:
        print("%d FAILURES: %s" % (len(FAILED), "; ".join(FAILED)))
        return 1
    print("ALL DOWNGRADE-GUARD TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
