"""Checks on the bridge app's Python wrapper.

The wrapper is a thin cover over the one bridge - the same file the
AutoSongs app carries inside itself. So the things worth checking are
that it really is a thin cover, that it starts the bridge the way the
bridge expects to be started, and that stopping it when nothing is
running does not fall over.

Run it the way the other bridge tests are run:

    python3 test_bridgeapp.py
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(os.path.dirname(HERE), "bridge")
WRAPPER = os.path.join(HERE, "src", "main", "python", "autosongs_bridge.py")

if BRIDGE not in sys.path:
    sys.path.insert(0, BRIDGE)

failures = []


def check(name, condition, detail=""):
    if condition:
        print("OK  %s" % name)
    else:
        print("FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


def load_wrapper():
    spec = importlib.util.spec_from_file_location("autosongs_bridge", WRAPPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    check("the wrapper is where it is supposed to be", os.path.exists(WRAPPER), WRAPPER)
    check("the shared bridge is where it is supposed to be",
          os.path.exists(os.path.join(BRIDGE, "ytbridge.py")))

    wrapper = load_wrapper()

    # It is a cover over the one bridge, not a second implementation.
    source = open(WRAPPER, encoding="utf-8").read()
    check("the wrapper imports the shared bridge", "import ytbridge" in source)
    check("the wrapper does not carry its own copy of the bridge",
          "def make_server(" not in source and "def make_pair_code(" not in source)

    # It starts the bridge the way the bridge expects to be started.
    import inspect
    start = inspect.signature(wrapper.start)
    check("the bridge starts on port 8765 by default",
          start.parameters["port"].default == 8765)
    check("the bridge takes a working folder", "workdir" in start.parameters)
    check("the bridge takes a library folder", "library" in start.parameters)

    # The bridge listens on every interface, so another phone can reach
    # it. This is the one thing that is different from the copy inside
    # the app, which only listens on this phone's own loopback.
    import ytbridge
    check("the bridge listens on every interface",
          '"0.0.0.0"' in source, "expected 0.0.0.0 in the wrapper")

    # The code the phone types is the bridge's own, made by the bridge.
    check("the bridge makes the pairing code",
          hasattr(ytbridge, "make_pair_code"))
    code = ytbridge.make_pair_code()
    check("the pairing code is eight characters", len(code) == 8, repr(code))
    check("the pairing code is one a person can read",
          all(c in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for c in code), repr(code))

    # Stopping a bridge that was never started must not fall over. The
    # app calls stop() on every teardown, including after a failure.
    check("stopping a bridge that never started is safe", wrapper.stop() is True)

    # The version the app shows comes from the one bridge.
    check("the wrapper reports the bridge's version",
          wrapper.version() == ytbridge.BRIDGE_VERSION)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nthe bridge app's wrapper is a thin cover over the one bridge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
