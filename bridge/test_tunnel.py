"""Proves the bridge really can be reached over a tunnel.

The test starts the bridge with --tunnel, waits for it to hand out its
public address, and then talks to it *through that address* - which is
the only thing that proves the tunnel works. Talking to the bridge on
localhost would prove nothing.

It then checks the two things that matter for safety:

  * /pair/info without the key is refused when the bridge is public
  * /pair/info with the key answers, and names the public address
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

BRIDGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ytbridge.py")
PORT = 8793
LOG = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Temp", "tunnel_live.log")

failed = 0


def check(name, ok, detail=""):
    global failed
    print(("OK   " if ok else "FAIL ") + name + (("  " + detail) if detail else ""))
    if not ok:
        failed += 1


def fetch(url, token=None, timeout=25, tries=4):
    """Makes the request, and says what came back.

    curl is used rather than urllib because the name of a tunnel often
    does not resolve on the router in front of the machine - the one
    here, for one - and curl can be told which address to use while
    keeping the name for the certificate and the Host header. That is
    what a phone on a working connection would do anyway, so the test
    measures the bridge rather than the router.

    A code of 0 means curl never got an answer - the connection failed
    - and a code of 530 means Cloudflare cannot reach the origin yet.
    Both are facts about the network, not about the bridge, and both
    are retried rather than reported: a test that fails when the
    network hiccups sends somebody hunting a bug that is not there.
    """
    from urllib.parse import urlparse
    parts = urlparse(url)
    host = parts.hostname or ""
    cmd = ["curl", "-s", "--max-time", str(timeout),
           "-w", "\n%{http_code}"]
    if token:
        cmd += ["-H", "X-Auth-Token: %s" % token]
    if host:
        cmd += ["--resolve", "%s:%d:%s" % (host, parts.port or 443, resolve(host))]
    cmd.append(url)

    code, body = 0, ""
    for attempt in range(tries):
        out = subprocess.run(cmd, capture_output=True, text=True)
        body = out.stdout or ""
        code_text = body.rsplit("\n", 1)[-1].strip() if "\n" in body else "0"
        body = body.rsplit("\n", 1)[0] if "\n" in body else body
        try:
            code = int(code_text)
        except ValueError:
            code = 0
        # 530 is Cloudflare saying it cannot reach the origin yet. A
        # quick tunnel is announced before it is routable, so that is
        # a not-yet-there answer rather than a wrong one, and it is
        # retried like the connection failure above.
        if code and code != 530:
            return code, body
        if attempt + 1 < tries:
            time.sleep(2)
    return code, body


def resolve(host):
    """The address of a name, using a public resolver when it has to.

    Some routers do not resolve trycloudflare.com. That is a fact about
    the router, not about the bridge, so the address is looked up
    elsewhere and used instead.
    """
    # DNS over HTTPS first: it asks an authoritative resolver, and the
    # tunnel's name is new every time, so the local resolver may still
    # be holding an older answer for it. The local resolver is the
    # fallback, and the router in front of this machine does not know
    # about trycloudflare names at all.
    try:
        import json
        import urllib.request
        req = urllib.request.Request(
            "https://cloudflare-dns.com/dns-query?name=%s&type=A" % host,
            headers={"accept": "application/dns-json"})
        data = json.loads(urllib.request.urlopen(req, timeout=15).read())
        for answer in data.get("Answer", []):
            if answer.get("type") == 1:
                return answer["data"]
    except Exception:  # noqa: BLE001 - fall through to the local resolver
        pass

    # The local resolver, which usually knows these names.
    import socket
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
        addresses = sorted({i[4][0] for i in infos})
        if addresses:
            return addresses[0]
    except socket.gaierror:
        pass

    # And nslookup as a second try.
    out = subprocess.run(["nslookup", host, "8.8.8.8"],
                         capture_output=True, text=True)
    import re
    for ip in re.findall(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", out.stdout):
        if ip == "8.8.8.8":
            continue
        try:
            socket.inet_aton(ip)
            return ip
        except OSError:
            continue
    return host


# cloudflared is what opens the tunnel. It is a free download from
# Cloudflare, and the test says where to get it rather than failing in
# a way that does not explain itself.
sys.path.insert(0, os.path.dirname(BRIDGE))
import ytbridge
if not ytbridge.find_cloudflared():
    print("SKIP  cloudflared is not installed, so the tunnel cannot be tested.")
    print("      It is a free download from Cloudflare:")
    print("      https://developers.cloudflare.com/cloudflare-one/connections/connect-apps")
    raise SystemExit(0)

print("starting the bridge with a tunnel...")
log = open(LOG, "w", encoding="utf-8", errors="replace")
# The bridge keeps its fixed address and its key under the home folder. A
# test must not borrow the install's address - it would then be proving that
# address rather than its own tunnel - so the run gets a home of its own.
import tempfile
HOME = tempfile.mkdtemp(prefix="bridgetest_")
env = dict(os.environ, USERPROFILE=HOME, HOME=HOME, APPDATA=HOME)
proc = subprocess.Popen(
    [sys.executable, BRIDGE, "--pair", "--tunnel", "--port", str(PORT)],
    stdout=log, stderr=subprocess.STDOUT, cwd=os.path.dirname(BRIDGE), env=env,
)
try:
    url = None
    token = None
    long_code = None
    deadline = time.time() + 120
    while time.time() < deadline:
        text = open(LOG, encoding="utf-8", errors="replace").read()
        found = re.search(r"(?:reachable from outside at:|reachable at)\s*(https://\S+)", text)
        if found:
            url = found.group(1)
            code = re.search(
                r"long code[^\n]*\n\s*\n\s*([0-9A-Z]{4,}(?:-[0-9A-Z]+)+)", text)
            if code:
                long_code = code.group(1)
        if url and long_code:
            break
        if proc.poll() is not None:
            break
        time.sleep(1)

    if not url:
        detail = open(LOG, encoding="utf-8", errors="replace").read()[-600:]
        # Cloudflare limits how many quick tunnels one network may make
        # in a short time. A run of tests trips that limit, and it is
        # not a fault in the bridge - so it is a skip, with the reason,
        # and not a failure that sends someone looking for a bug.
        if "429" in detail or "refusing more tunnels" in detail:
            print("SKIP  Cloudflare is rate-limiting this network's quick")
            print("      tunnels, so the tunnel could not be made. The")
            print("      bridge's own error message says so, which is the")
            print("      behaviour under test. Try again in a minute.")
            raise SystemExit(0)
        check("the tunnel came up", False, detail)
        raise SystemExit(1)
    check("the tunnel came up", True, url)

    # What the code says, read by the same code the app uses.
    sys.path.insert(0, os.path.dirname(BRIDGE))
    import ytbridge
    host, port, secret, scheme, path = ytbridge.read_pairing_code(long_code)
    check("the code names the public address",
          host == url.replace("https://", "") and port == 443 and scheme == "https",
          "-> %s:%d %s" % (host, port, scheme))
    token = secret

    # The address is live. A quick tunnel is not routable the instant it
    # is announced - Cloudflare says so itself - so this waits for it
    # rather than counting a not-yet-there tunnel as a failure.
    status, body = 0, ""
    for _ in range(30):
        status, body = fetch(url + "/health", token)
        if status == 200:
            break
        # A 530 means the tunnel is not routable yet, and 0 means the
        # connection failed. Neither is an answer, so both are waited
        # out rather than taken for one.
        time.sleep(2)
    check("the bridge answers through the tunnel", status == 200,
          "-> HTTP %s %s" % (status, body[:80]))
    if status == 200:
        try:
            data = json.loads(body)
            check("the answer is the bridge's own", data.get("ok") is True,
                  "-> %s" % body[:120])
            check("the bridge says which version it is",
                  bool(data.get("version")), "-> version %s" % data.get("version"))
        except ValueError:
            check("the answer is the bridge's own", False, "-> not JSON: %s" % body[:120])

    # The pairing endpoints need the key when the bridge is public.
    status, body = 0, ""
    for _ in range(15):
        status, body = fetch(url + "/pair/info")
        if status == 401:
            break
        time.sleep(2)
    check("the pairing answers refuse a stranger", status == 401,
          "-> HTTP %s" % status)

    status, body = 0, ""
    for _ in range(15):
        status, body = fetch(url + "/pair/info", token)
        if status == 200:
            break
        time.sleep(2)
    check("the pairing answers take the key", status == 200,
          "-> HTTP %s %s" % (status, body[:80]))
    if status == 200:
        try:
            data = json.loads(body)
            check("the pairing answer names the public address",
                  data.get("host") == host.replace(":", "") or
                  data.get("host", "").startswith(host.split(":")[0]),
                  "-> %s" % data.get("host"))
            check("the pairing answer gives the scheme",
                  data.get("scheme") == "https", "-> %s" % data.get("scheme"))
        except ValueError:
            check("the pairing answer names the public address", False, body[:120])

    # And the key works on the ordinary endpoints too.
    status, body = fetch(url + "/health", "WRONGKEY")
    check("a wrong key is refused", status == 401, "-> HTTP %s" % status)

finally:
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    log.close()

print("")
if failed:
    print("FAIL  %d check(s) failed" % failed)
    sys.exit(1)
print("OK   the bridge can be reached over a tunnel")
