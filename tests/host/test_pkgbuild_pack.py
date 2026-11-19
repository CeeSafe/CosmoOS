#!/usr/bin/env python3
"""tools/pkgbuild.py's `pack --package FILE --root STAGE` (roadmap 1.3 R3;
docs/pkg/design.md, "Cross-built ports"; docs/pkg/testing.md): a cross-built
port's package file names paths in its staged install, each with a mode, and
the package installs them at the same paths. The manifest carries the file's
depends and each file's mode; a `DIR/` line takes every regular file under it;
the archive is the same bytes on a second run; what the file format or the
destination rules refuse is refused before anything is written.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pkgbuild  # noqa: E402

PKGBUILD = os.path.join(ROOT, "tools", "pkgbuild.py")


def check(cond, what):
    if not cond:
        raise SystemExit(f"test_pkgbuild_pack: FAIL {what}")
    print(f"ok   {what}")


def write(path, data, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, mode)


def pack(work, text, key, out):
    pf = os.path.join(work, "package")
    with open(pf, "w") as f:
        f.write(text)
    return subprocess.run([sys.executable, PKGBUILD, "pack", "--package", pf, "--root", os.path.join(work, "stage"),
                           "--sign-key", key, "--out", out], capture_output=True, text=True)


def main():
    with tempfile.TemporaryDirectory() as work:
        key = os.path.join(work, "k.key")
        with open(key, "w") as f:
            f.write("11" * 32 + "\n")
        stage = os.path.join(work, "stage")
        write(os.path.join(stage, "usr/bin/tool"), b"\x7fELF not really\n", 0o644)   # the stage's mode is not used
        write(os.path.join(stage, "usr/share/tool/b.txt"), b"b\n")
        write(os.path.join(stage, "usr/share/tool/a.txt"), b"a\n")
        write(os.path.join(stage, "usr/share/tool/sub/c.txt"), b"c\n")
        os.symlink("a.txt", os.path.join(stage, "usr/share/tool/link.txt"))
        # Links to a directory outside the stage, holding a file no package may carry: one as a
        # parent directory of a path named, one inside a DIR/ tree (#535's review).
        outside = os.path.join(work, "outside")
        write(os.path.join(outside, "secret"), b"not the stage's\n")
        os.symlink(outside, os.path.join(stage, "usr/lnk"))
        os.symlink(outside, os.path.join(stage, "usr/share/tool/sub/lnkdir"))
        write(os.path.join(stage, "etc/tool.conf"), b"x = 1\n")
        repo = os.path.join(work, "repo")
        os.makedirs(repo)
        good = ("# a comment\nname: tool\nversion: 2.1-3\nsummary: a tool\ndepends: other >= 1.0\n"
                "file: usr/bin/tool 0755\nfile: usr/share/tool/ 0644\nfile: etc/tool.conf 0600\n")

        r = pack(work, good, key, repo)
        check(r.returncode == 0, f"pack --package into a repository directory ({r.stderr.strip()})")
        out = os.path.join(repo, "tool-2.1-3.cpk")
        check(os.path.isfile(out), "named NAME-VERSION.cpk in the directory")
        fields, blob = pkgbuild.read_manifest_from_package(out)   # signed, +MANIFEST first, or it dies
        check(fields == {"name": "tool", "version": "2.1-3", "summary": "a tool", "depends": ["other >= 1.0"]},
              f"the manifest's name, version, summary and depends ({fields})")
        check(b"file: usr/bin/tool 0755 " in blob and b"file: etc/tool.conf 0600 " in blob,
              "each file at its line's mode, not the stage's")
        for p in (b"usr/share/tool/a.txt", b"usr/share/tool/b.txt", b"usr/share/tool/sub/c.txt"):
            check(b"file: " + p + b" 0644 " in blob, f"the DIR/ line took {p.decode()}")
        check(b"link.txt" not in blob, "a symbolic link under DIR/ left out")
        check(b"secret" not in blob and b"not the stage's" not in blob,
              "a linked directory under DIR/ pointing outside the stage left out")
        first = blob
        r = pack(work, good, key, os.path.join(work, "again.cpk"))
        check(r.returncode == 0 and open(os.path.join(work, "again.cpk"), "rb").read() == first,
              "the same bytes from a second run (--out a file)")

        refused = (
            ("an unknown key", good + "program: bin/x x.c\n", "unknown key 'program'"),
            ("a file without a mode", good + "file: usr/bin/tool\n", "file needs 'path mode'"),
            ("a mode that is not octal", good.replace("0755", "0789"), "file needs 'path mode'"),
            ("a path not in the stage", good + "file: usr/bin/none 0755\n", "is not a regular file"),
            ("a symbolic link named", good + "file: usr/share/tool/link.txt 0644\n", "is not a regular file"),
            ("a file through a linked parent directory", good + "file: usr/lnk/secret 0644\n",
             "is not a regular file"),
            ("a DIR/ through a linked directory", good + "file: usr/lnk/ 0644\n", "is not a directory"),
            ("a path that leaves /", good + "file: ../outside 0644\n", "bad destination"),
            ("a forbidden destination", good + "file: dev/null 0644\n", "destination not allowed"),
            ("a file listed twice", good + "file: usr/share/tool/a.txt 0644\n", "a file is listed twice"),
            ("no file at all", "name: t\nversion: 1.0\nsummary: s\n", "no file"),
            ("a missing version", good.replace("version: 2.1-3\n", ""), "missing 'version'"),
            ("a bad dependency", good.replace("other >= 1.0", "Other >>> 1"), "bad dependency"),
        )
        for what, text, msg in refused:
            dest = os.path.join(work, "refused.cpk")
            r = pack(work, text, key, dest)
            check(r.returncode != 0 and msg in r.stderr and not os.path.exists(dest), f"refused: {what} ({msg})")

        pf = os.path.join(work, "package")
        with open(pf, "w") as f:
            f.write(good)
        r = subprocess.run([sys.executable, PKGBUILD, "pack", "--package", pf, "--root", stage, "--name", "x",
                            "--sign-key", key, "--out", os.path.join(work, "x.cpk")], capture_output=True, text=True)
        check(r.returncode != 0 and "--package takes the name" in r.stderr, "refused: --package with --name")
        r = subprocess.run([sys.executable, PKGBUILD, "pack", "--package", pf, "--sign-key", key,
                            "--out", os.path.join(work, "x.cpk")], capture_output=True, text=True)
        check(r.returncode != 0 and "--package needs --root" in r.stderr, "refused: --package without --root")
    print("test_pkgbuild_pack: PASS")


if __name__ == "__main__":
    main()
