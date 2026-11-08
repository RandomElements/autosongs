"""Checks the new pairing: the short code, the answer to a phone looking
for the bridge, and the claim that hands over the key."""
import json
import re
import socket
import subprocess
import os
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ytbridge  # noqa: E402

PORT = 8797
BRIDGE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "ytbridge.py")

# --- the code itself ---------------------------------------------------------
code = ytbridge.make_pair_code()
assert len(code) == 8, "the code is eight characters: %r" % code
assert all(ch in ytbridge.CROCKFORD for ch in code), code
assert ytbridge.normalize_pair_code(" %s " % code.lower()) == code
try:
    ytbridge.normalize_pair_code("ABCID")
    raise AssertionError("a letter that is not in the alphabet must be reported")
except ValueError:
    pass
print("OK  the short code is eight characters and reads the same either way")

# --- the bridge, running for real --------------------------------------------
proc = subprocess.Popen(
    [sys.executable, BRIDGE, "--port", str(PORT), "--pair", "--token", "A1B2C3D4E5F6"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(3)
lines = []


def read_output():
    for line in proc.stdout:
        lines.append(line.rstrip("\n"))


threading.Thread(target=read_output, daemon=True).start()


def wait_for_code():
    """The code the bridge shows on its screen."""
    for _ in range(100):
        for line in lines:
            found = re.fullmatch(r"\s{6}([0-9A-HJKMNP-TV-Z]{8})\s*", line)
            if found:
                return found.group(1)
        time.sleep(0.2)
    raise AssertionError("the bridge did not show a code:\n%s" % "\n".join(lines))


try:
    shown = wait_for_code()
    print("OK  the bridge shows its code: %s" % shown)
    # The answer a phone gets when it calls out to the network.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(4)
    sock.sendto(b"autosongs-pair-v1", ("127.0.0.1", PORT))
    data, _ = sock.recvfrom(2048)
    answer = json.loads(data.decode("utf-8"))
    assert answer["h"], "the answer carries a fingerprint of the code"
    assert answer["port"] == PORT, answer
    sock.close()
    print("OK  a phone that calls out finds the bridge: %s" % answer["host"])

    # /pair/info is open, and says the same thing.
    with urllib.request.urlopen("http://127.0.0.1:%d/pair/info" % PORT, timeout=10) as r:
        info = json.loads(r.read().decode("utf-8"))
    assert info["h"] == answer["h"], "both answers must agree"

    # The right code hands over the key; a wrong one does not.
    url = "http://127.0.0.1:%d/pair/claim?code=%s" % (PORT, shown)
    with urllib.request.urlopen(url, timeout=10) as r:
        claim = json.loads(r.read().decode("utf-8"))
    assert claim["token"] == "A1B2C3D4E5F6", claim
    print("OK  the right code hands over the key")

    try:
        urllib.request.urlopen(
            "http://127.0.0.1:%d/pair/claim?code=WRONG12" % PORT, timeout=10)
        raise AssertionError("a wrong code must not hand over the key")
    except urllib.error.HTTPError as e:
        assert e.code == 403, e.code
    print("OK  a wrong code is turned away")

    # And the bridge still wants the key for everything else.
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=10)
        raise AssertionError("health must still want the key")
    except urllib.error.HTTPError as e:
        assert e.code == 401, e.code
    print("OK  the rest of the bridge still asks for the key")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

print("OK  the pairing works")
