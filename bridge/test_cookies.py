#!/usr/bin/env python3
"""The bridge has to get past YouTube's sign-in demand ("bot check").

YouTube answers some requests with "Sign in to confirm you're not a bot"
instead of the video. The cure is a cookie jar, and these tests pin the
three things that have to work for it:

* a jar is found without anyone being asked to name it,
* both ways of calling yt-dlp are given the jar - the command line and the
  library - because the app uses the library and every other bridge uses
  the command line, and
* a job that was refused is run again with the jar, from the top, because
  the refusal can land in the search as well as in the download.

Run with:  py -3 test_cookies.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ytbridge  # noqa: E402

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print("   OK %s" % name)
    else:
        print("   FAIL %s" % name)
        FAILED.append(name)
    if not condition and detail:
        print("        %s" % detail)


def with_cookies(value):
    """Runs a test with the bridge's cookie jar set to something."""
    global COOKIES
    old = ytbridge.COOKIES
    ytbridge.COOKIES = value
    try:
        yield
    finally:
        ytbridge.COOKIES = old


class _Nothing:
    """The jar of a bridge that has none."""
    path = ""
    source = ""

    @property
    def active(self):
        return False

    def cli_args(self):
        return []

    def api_opts(self):
        return {}


def temp_dir():
    return tempfile.mkdtemp(prefix="autosongs-cookies-")


def write_jar(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Netscape HTTP Cookie File\n")
    return path


def test_a_jar_is_found_without_being_asked_for():
    print("== a jar is looked for, not demanded")
    home = os.path.expanduser("~")
    places = [
        ("next to the bridge",
         os.path.join(os.path.dirname(os.path.abspath(ytbridge.__file__)), "cookies.txt")),
        ("in the work folder", os.path.join(temp_dir(), "cookies.txt")),
        ("in ~/.autosongs", os.path.join(home, ".autosongs", "cookies.txt")),
        ("in ~/autosongs", os.path.join(home, "autosongs", "cookies.txt")),
        ("in ~/.config/yt-dlp", os.path.join(home, ".config", "yt-dlp", "cookies.txt")),
    ]
    old_workdir = ytbridge.WORKDIR
    for where, path in places:
        if where == "in the work folder":
            ytbridge.WORKDIR = os.path.dirname(path)
        write_jar(path)
        try:
            found, source = ytbridge.find_cookie_source("")
            check("%s: the jar is found" % where, found == path,
                  "found %r (%s)" % (found, source))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    ytbridge.WORKDIR = old_workdir

    check("a bridge with no jar says so",
          ytbridge.find_cookie_source("")[1] == "none")


def test_a_named_jar_wins():
    print("== a jar somebody named wins over one that was lying around")
    chosen = write_jar(os.path.join(temp_dir(), "chosen.txt"))
    lying = write_jar(os.path.join(os.path.expanduser("~"), ".autosongs", "cookies.txt"))
    try:
        found, source = ytbridge.find_cookie_source(chosen)
        check("the named jar is the one that is used", found == chosen,
              "found %r" % found)
        check("and the bridge says where it came from", source == "the file you chose",
              source)
    finally:
        for path in (chosen, lying):
            try:
                os.remove(path)
            except OSError:
                pass

    missing = os.path.join(temp_dir(), "not-there.txt")
    found, source = ytbridge.find_cookie_source(missing)
    check("a named jar that is not there is not used", found == "",
          "found %r" % found)


def test_both_ways_of_calling_yt_dlp_are_given_the_jar():
    print("== both shapes of the option")
    source = ytbridge.CookieSource("/tmp/cookies.txt", "the file you chose")
    check("the command line is given the path",
          source.cli_args() == ["--cookies", "/tmp/cookies.txt"], source.cli_args())
    check("the library is given the option",
          source.api_opts() == {"cookiefile": "/tmp/cookies.txt"}, source.api_opts())

    empty = ytbridge.CookieSource()
    check("a bridge with no jar adds nothing to the command line",
          empty.cli_args() == [], empty.cli_args())
    check("a bridge with no jar adds nothing to the library",
          empty.api_opts() == {}, empty.api_opts())


def test_the_sign_in_demand_is_recognised():
    print("== the sign-in demand is recognised in one place")
    for phrase in ("Sign in to confirm you're not a bot",
                   "ERROR: Sign in to confirm you are not a bot",
                   "This helps protect our community. Please sign in",
                   "login required"):
        check("recognised: %r" % phrase[:44], ytbridge.is_bot_check(phrase) is True)
    for phrase in ("HTTP Error 403: Forbidden",
                   "unable to download video data",
                   "yt-dlp produced no file"):
        check("not the sign-in demand: %r" % phrase[:44],
              ytbridge.is_bot_check(phrase) is False)


def test_a_refused_job_is_run_again_with_the_jar():
    print("== a refused job is run again with the jar")
    workdir = temp_dir()
    old_workdir = ytbridge.WORKDIR
    ytbridge.WORKDIR = workdir

    calls = {"n": 0}

    def refused_search(query, depth=ytbridge.SEARCH_DEPTH):
        calls["n"] += 1
        raise RuntimeError("ERROR: Sign in to confirm you're not a bot")

    old_search = ytbridge.search_candidates
    ytbridge.search_candidates = refused_search
    try:
        # A jar in the work folder is the one the bridge is meant to find.
        jar = write_jar(os.path.join(workdir, "cookies.txt"))
        ytbridge.COOKIES = _Nothing()
        ytbridge.JOBS.clear()
        ytbridge.run_job("job1", "Some Artist - Some Song", "audio_m4a", 1080,
                         False, False, "Some Song", "Some Artist", 0)
        check("the job was run a second time", calls["n"] == 2,
              "the search ran %d time(s)" % calls["n"])
        check("the jar was put to use", ytbridge.COOKIES.path == jar,
              "cookies: %r" % ytbridge.COOKIES.path)
        check("the job says it was refused", ytbridge.JOBS["job1"].get("bot_check") is True,
              repr(ytbridge.JOBS["job1"]))
        check("the app is told that cookies are what is needed",
              ytbridge.JOBS["job1"].get("needs_cookies") is True,
              repr(ytbridge.JOBS["job1"]))

        # With no jar anywhere there is nothing to try, so the job is not
        # run again - running it twice would only fail the same way.
        calls["n"] = 0
        os.remove(jar)
        ytbridge.COOKIES = _Nothing()
        ytbridge.JOBS.clear()
        ytbridge.run_job("job2", "Some Artist - Some Song", "audio_m4a", 1080,
                         False, False, "Some Song", "Some Artist", 0)
        check("without a jar the job is not run again", calls["n"] == 1,
              "the search ran %d time(s)" % calls["n"])
        check("the app is still told that cookies are what is needed",
              ytbridge.JOBS["job2"].get("needs_cookies") is True,
              repr(ytbridge.JOBS["job2"]))
    finally:
        ytbridge.search_candidates = old_search
        ytbridge.WORKDIR = old_workdir
        ytbridge.COOKIES = _Nothing()


def test_a_jar_the_app_sends_is_used_and_can_be_taken_away():
    print("== a jar the app sends is used from then on")
    workdir = temp_dir()
    old_workdir = ytbridge.WORKDIR
    ytbridge.WORKDIR = workdir
    try:
        ytbridge.COOKIES = _Nothing()
        jar = ytbridge.set_cookie_jar("# Netscape HTTP Cookie File\n")
        check("the jar is in use", jar.active is True)
        check("and the bridge says where it came from",
              jar.source == "the file the app sent", jar.source)
        check("the jar was written where it will be found again",
              os.path.isfile(os.path.join(workdir, "cookies.txt")))

        found, source = ytbridge.find_cookie_source("")
        check("a jar in the work folder is found again",
              found == os.path.join(workdir, "cookies.txt"), "found %r" % found)

        # Taking it away leaves the bridge with no jar.
        gone = ytbridge.set_cookie_jar("")
        check("the jar can be taken away", gone.active is False, repr(gone))
    finally:
        ytbridge.WORKDIR = old_workdir
        ytbridge.COOKIES = _Nothing()


def main():
    test_a_jar_is_found_without_being_asked_for()
    test_a_named_jar_wins()
    test_both_ways_of_calling_yt_dlp_are_given_the_jar()
    test_the_sign_in_demand_is_recognised()
    test_a_refused_job_is_run_again_with_the_jar()
    test_a_jar_the_app_sends_is_used_and_can_be_taken_away()
    print()
    if FAILED:
        print("%d FAILURES: %s" % (len(FAILED), "; ".join(FAILED)))
        return 1
    print("cookies: all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
