"""The code the bridge shows and the phone types must mean the same thing.

The bridge prints one code, the user pastes it into the app, and from then
on the two know each other. If the code loses the address or the key on the
way, the phone is paired with nothing - and the user has no way to tell.

So this checks the round trip, the typo catching, and that the letters
people mistype are not in the alphabet at all.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ytbridge  # noqa: E402

failed = 0


def check(name, ok, detail=""):
    global failed
    if ok:
        print("OK  %s" % name)
    else:
        failed += 1
        print("FAIL  %s %s" % (name, detail))


# ---- the round trip -------------------------------------------------------
for host, port in (("192.168.1.50", 8765),
                    ("10.0.0.7", 9000),
                    ("nas.local", 8765),
                    ("bridge.example.org", 1234)):
    secret = "A1B2C3D4E5F6"
    code = ytbridge.pairing_code(host, port, secret)
    got_host, got_port, got_secret, got_scheme, got_path = \
        ytbridge.read_pairing_code(code)
    check("the code carries %s:%d" % (host, port),
          got_host == host and got_port == port and got_secret == secret,
          "-> got %s:%d %s" % (got_host, got_port, got_secret))
    check("%s is reached over plain http" % host,
          got_scheme == "http" and got_path == "",
          "-> got %s %r" % (got_scheme, got_path))

# ---- a bridge that is reached over the internet ----------------------------
# The phone cannot find this one by asking the network, so the code has
# to carry the whole address: the scheme, the host, the port the address
# names and any path under it.
secret = "A1B2C3D4E5F6"
for public, want_host, want_port, want_path in (
        ("https://penalty-federation-urgent-unwrap.trycloudflare.com",
         "penalty-federation-urgent-unwrap.trycloudflare.com", 443, ""),
        ("https://bridge.example.com",
         "bridge.example.com", 443, ""),
        ("http://bridge.example.com:8080",
         "bridge.example.com", 8080, ""),
        ("https://example.com/auto/bridge",
         "example.com", 443, "/auto/bridge"),
):
    code = ytbridge.pairing_code("192.168.1.50", 8765, secret,
                                 public_url=public)
    got_host, got_port, got_secret, got_scheme, got_path = \
        ytbridge.read_pairing_code(code)
    check("the code carries %s" % public,
          got_host == want_host and got_port == want_port
          and got_path == want_path and got_secret == secret,
          "-> got %s:%d %r" % (got_host, got_port, got_path))
    check("%s is reached over %s" % (public, want_host),
          got_scheme == ("https" if public.startswith("https") else "http"),
          "-> got %s" % got_scheme)

# The bridge's own port must not leak into a public code: it is a
# number on this machine and means nothing outside it.
code = ytbridge.pairing_code("192.168.1.50", 8765, secret,
                             public_url="https://bridge.example.com")
check("the public code does not carry the bridge's own port",
      ytbridge.read_pairing_code(code)[1] == 443,
      "-> got %d" % ytbridge.read_pairing_code(code)[1])

# ---- a name with a dot in it is not an address ------------------------------
code = ytbridge.pairing_code("192.168.1.50", 8765, "A1B2C3D4E5F6")
check("an address stays an address",
      ytbridge.read_pairing_code(code)[0] == "192.168.1.50")

# ---- a typo must not be accepted ------------------------------------------
mangled = list(code)
mangled[3] = "X" if mangled[3] != "X" else "Y"
try:
    ytbridge.read_pairing_code("".join(mangled))
    check("a wrong letter is caught", False, "- it was accepted")
except ValueError as exc:
    check("a wrong letter is caught", True)

# ---- and rubbish is not a code --------------------------------------------
for rubbish in ("hello", "", "1234", "A-B-C"):
    try:
        ytbridge.read_pairing_code(rubbish)
        check("rubbish is refused (%r)" % rubbish, False, "- it was accepted")
    except ValueError:
        check("rubbish is refused (%r)" % rubbish, True)

# ---- the letters people mistype are not in the alphabet --------------------
alphabet = "".join(ytbridge.pairing_code("192.168.1.50", 8765, "A1B2C3D4E5F6")
                   .replace("-", ""))
for letter in "ILOU":
    check("the code never uses the letter %s" % letter,
          letter not in alphabet)

# ---- the key is kept, so a phone stays paired ------------------------------
secret = ytbridge.load_or_make_secret()
check("the key is made once and kept",
      len(secret) >= 16 and secret == ytbridge.load_or_make_secret(),
      "-> %r" % secret)

# ---- the code and the key are the same thing -------------------------------
code = ytbridge.pairing_code("192.168.1.50", 8765, secret)
check("the code carries the key the bridge checks",
      ytbridge.read_pairing_code(code)[2] == secret)

# ---- the split of a public address ---------------------------------------
check("an https address is read as https",
      ytbridge.split_public_url("https://a.example.com/x") ==
      ("https", "a.example.com", "/x"))
check("an address without a scheme is taken as https",
      ytbridge.split_public_url("a.example.com")[0] == "https")
check("the public port of an https address is 443",
      ytbridge.public_port("https", "a.example.com", 8765) == 443)
check("a port in the address is the one that is used",
      ytbridge.public_port("https", "a.example.com:8443", 8765) == 8443)

print("")
if failed:
    print("FAIL  %d check(s) failed" % failed)
    sys.exit(1)
print("OK  the pairing code works")
