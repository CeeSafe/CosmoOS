#!/usr/bin/env python3
"""Roadmap 1.3 R3's acceptance test: the cross-built ports, installed with
`pkg install` on an installed system and run (docs/pkg/testing.md,
"test-ports"; docs/pkg/design.md, "Cross-built ports").

    ports_test.py --image cosmoos.img --repo SERVER_REPO --sign-key KEY --arch ARCH --workdir DIR

The live image installs itself on a blank disk (install_test.stage_install).
The installed system then boots on QEMU user networking with its ssh port
forwarded, and this harness serves the ports repository (--repo, `make
server-ports`'s, made a network one by `pkgbuild.py publish` as
scripts/publish-repo.py does) over HTTPS from 127.0.0.1 (the guest's
10.0.2.2) with test certificates made for the run (tests/boot/tlstest.py).

  a. `pkg update && pkg install nano` from that repository, the package
     fetched from the server.
  c. `pkg install curl`; `curl -fsS` of a file the harness serves over HTTPS
     (the test CA in the system's bundle, which curl reads) gives its
     bytes, and curl refuses the same file from a server whose certificate
     another CA signed (exit 60), with nothing requested from that server.
  g. `pkg install git`; `git clone` over HTTPS of a repository the harness
     made for the run (two commits, served as files: git's dumb HTTP
     protocol) gives its files and history; a commit in the clone makes the
     third; `git fsck` finds nothing wrong.
  b. nano under a terminal: an ssh session (`ssh -tt` under a host pty,
     pty_keys, TERM=xterm-256color) runs `nano FILE`, types a line,
     writes it out (^O, Enter) and leaves (^X);
     the file holds the line, and the session drew nano's title bar.
  z. No program a port installs met a system call the Linux personality
     lacks: the kernel's log (a debug kernel's: the lines are DEBUG) has
     no `unimplemented system call` line naming one. A probe compiled on
     the target by tcc makes such a call first, and its line must be
     there, so the check is seen to work.

Exit 0 PASS, 1 FAIL.
"""
import argparse
import fcntl
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import sys
import termios
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import install_test  # noqa: E402  (Boot, Fail, need, stage_install)
import tlstest  # noqa: E402
from install_test import Boot, Fail, need  # noqa: E402
from net_login_test import WIN_COLS, WIN_ROWS, free_port, ssh_base, ssh_run, ssh_wait  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKGBUILD = os.path.join(ROOT, "tools", "pkgbuild.py")
DAY = 86400
# The programs the ports install: a call the Linux personality lacks, made by
# one of them, fails the test (z). The base system's are reported, not judged.
PORT_PROGRAMS = {"nano", "curl", "git", "git-remote-https", "git-remote-http"}


def utc(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def publish(www, built, key, serial):
    """The built repository made a network one, as scripts/publish-repo.py
    makes it: INDEX.90 and INDEX, one serial, and every package."""
    d = os.path.join(www, "ports")
    os.makedirs(d, exist_ok=True)
    for f in sorted(os.listdir(built)):
        if f.endswith(".cpk"):
            shutil.copy(os.path.join(built, f), os.path.join(d, f))
    for out, days in (("INDEX.90", 90), ("INDEX", 30)):
        r = subprocess.run([sys.executable, PKGBUILD, "publish", "--index", os.path.join(built, "INDEX"),
                            "--sign-key", key, "--serial", str(serial), "--days", str(days),
                            "--published", utc(time.time() - DAY), "--out", os.path.join(d, out)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise Fail(f"pkgbuild.py publish: {r.stderr.strip()[-400:]}")


def login_key(work, b):
    """A key for root's logins, typed into authorized_keys on the console."""
    key = os.path.join(work, "id_ed25519")
    for f in (key, key + ".pub", os.path.join(work, "known_hosts")):
        if os.path.exists(f):
            os.unlink(f)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "ports-test", "-f", key], check=True)
    pub = open(key + ".pub").read().strip()
    out = b.status(f"mkdir -p /root/.ssh && echo '{pub}' > /root/.ssh/authorized_keys", "key")
    need(out, r"^key=0$", "root's authorized_keys")


def pty_keys(work, port, steps, marker, timeout=120):
    """ssh -tt under a host pty, as net_login_test.ssh_pty_session, but
    typing raw keys: each step is (bytes, what to wait for after it, or
    None). A terminal's Enter is CR, which a full-screen program reads as
    Enter; the LF ssh_pty_session ends each line with is ^J, which nano
    reads as Justify. The session's whole output once `marker` was seen."""
    master, slave = pty.openpty()
    p = None
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", WIN_ROWS, WIN_COLS, 0, 0))
        p = subprocess.Popen(ssh_base(work, port, True)[:-1] + ["-tt", "root@127.0.0.1"], stdin=slave,
                             stdout=slave, stderr=slave, close_fds=True, start_new_session=True)
    finally:
        os.close(slave)
    out = b""
    t_end = time.monotonic() + timeout

    def pump(until, secs, start=0):
        """Read until `until` appears in what arrived from `start` on."""
        nonlocal out
        end = min(t_end, time.monotonic() + secs)
        while time.monotonic() < end and (until is None or until not in out[start:]):
            r, _, _ = select.select([master], [], [], 0.2)
            if r:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
        return until is None or until in out[start:]

    try:
        if not pump(b"# ", 30):
            raise Fail("the ssh session's shell prompt never came")
        start = 0
        for keys, wait in steps:
            start = len(out)   # what a step waits for must come after its keys
            os.write(master, keys)
            if wait is not None and not pump(wait, 30, start):
                raise Fail(f"after typing {keys!r}: no {wait!r} on the terminal within 30 s")
            pump(None, 0.5)
        pump(("\n" + marker).encode(), max(1.0, t_end - time.monotonic()), start)
        os.write(master, b"exit\r")
        try:
            p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        pump(None, 0.5)
    finally:
        if p is not None and p.poll() is None:
            p.kill()
            p.wait()
        os.close(master)
    return out.decode("utf-8", "replace").replace("\r", "")


def stage_nano(work, results, port):
    """b: nano under the harness's terminal, over ssh."""
    note = "/root/ports-note.txt"
    line = "written by nano under a pty"
    out = pty_keys(work, port, [
        (f"nano {note}\r".encode(), b"GNU nano"),
        (line.encode() + b"\r", None),
        (b"\x0f", b"Write to File"),      # ^O
        (b"\r", b"Wrote 2 lines"),        # Enter: the name nano offers
        (b"\x18", b"# "),                 # ^X, nothing unsaved: the shell's prompt again, before typing on
        (f"cat {note}; echo nano-done=$?\r".encode(), None),
    ], "nano-done=")
    with open(os.path.join(work, "nano-session.txt"), "w") as f:   # the terminal's bytes, for a failure
        f.write(out)
    need(out, r"GNU nano 9\.3", "nano's title bar on the terminal")
    need(out, rf"^{re.escape(line)}$", "the file nano wrote, read back")
    need(out, r"^nano-done=0$", "cat of the file nano wrote")
    rc, back = ssh_run(work, port, True, f"cat {note}")
    if rc != 0 or back.strip() != line:
        raise Fail(f"{note}: status {rc}, contents {back!r}; expected {line!r}")
    results.append(f"b. nano under ssh -tt (xterm-256color): drew its title bar, wrote {note} with ^O, left with ^X; "
                   f"the file holds {line!r}")


def stage_curl(b, results, www, server, untrusted):
    """c: curl over HTTPS, and a certificate it must refuse."""
    body = os.urandom(48).hex() + "\n"
    with open(os.path.join(www, "hello.txt"), "w") as f:
        f.write(body)
    out = b.status("pkg install curl", "inst")
    need(out, r"^inst=0$", "pkg install curl")
    need(out, r"^pkg: installing curl-8\.23\.0 \(\d+ files?\)$", "curl installed")
    out = b.status(f"curl -fsS https://10.0.2.2:{server.port}/hello.txt -o /tmp/hello.txt && cat /tmp/hello.txt",
                   "get")
    need(out, r"^get=0$", "curl -fsS over HTTPS from the harness")
    need(out, rf"^{body.strip()}$", "the served file's bytes")
    if "/hello.txt" not in server.paths():
        raise Fail(f"the server saw {server.paths()}; curl did not fetch /hello.txt from it")
    out = b.status(f"curl -fsS https://10.0.2.2:{untrusted.port}/hello.txt -o /tmp/bad.txt", "bad")
    need(out, r"^bad=60$", "curl refusing a certificate another CA signed (exit 60)")
    if untrusted.requests:
        raise Fail(f"the untrusted server received {untrusted.paths()}; nothing should reach it")
    out = b.run("curl --version | head -n 1")
    ver = need(out, r"^(curl 8\.23\.0 .*)$", "curl --version").group(1)
    results.append(f"c. pkg install curl; curl -fsS over HTTPS fetched the served file byte for byte; a certificate "
                   f"from another CA refused (exit 60, no request reached that server); {ver!r}")


def host_git(*argv, cwd=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="ports test", GIT_AUTHOR_EMAIL="ports@test.invalid",
               GIT_COMMITTER_NAME="ports test", GIT_COMMITTER_EMAIL="ports@test.invalid",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    r = subprocess.run(["git"] + list(argv), cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise Fail(f"host git {' '.join(argv)}: {r.stderr.strip()[-400:]}")
    return r.stdout


def served_repo(work, www):
    """A repository of two commits, made on the host and served from www as
    files (git's dumb HTTP protocol: info/refs and the objects). Its
    README's contents and its head commit."""
    src = os.path.join(work, "gitsrc")
    host_git("init", "-q", "-b", "main", src)
    body = "made by the ports test " + os.urandom(8).hex()
    with open(os.path.join(src, "README"), "w") as f:
        f.write(body + "\n")
    host_git("add", "README", cwd=src)
    host_git("commit", "-q", "-m", "first", cwd=src)
    with open(os.path.join(src, "second.txt"), "w") as f:
        f.write("second\n")
    host_git("add", "second.txt", cwd=src)
    host_git("commit", "-q", "-m", "second", cwd=src)
    bare = os.path.join(www, "repo.git")
    host_git("clone", "-q", "--bare", src, bare)
    host_git("update-server-info", cwd=bare)
    return body, host_git("rev-parse", "HEAD", cwd=src).strip()


def stage_git(b, results, work, www, server):
    """g: git clone over HTTPS, a commit, fsck."""
    body, head = served_repo(work, www)
    out = b.status("pkg install git", "inst")
    need(out, r"^inst=0$", "pkg install git")
    need(out, r"^pkg: installing git-2\.56\.1 \(\d+ files?\)$", "git installed")
    out = b.status(f"git clone -q https://10.0.2.2:{server.port}/repo.git /root/clone && cat /root/clone/README && "
                   "git -C /root/clone rev-parse HEAD && git -C /root/clone log --oneline | wc -l", "clone")
    need(out, r"^clone=0$", "git clone over HTTPS")
    need(out, rf"^{re.escape(body)}$", "the clone's README")
    need(out, rf"^{head}$", "the clone's head, the served repository's")
    need(out, r"^\s*2$", "two commits in the clone")
    if not any(p.startswith("/repo.git/") for p in server.paths()):
        raise Fail(f"the server saw {server.paths()}; git did not fetch /repo.git from it")
    out = b.status("cd /root/clone && echo 'third, made on CosmoOS' > third.txt && git add third.txt && "
                   "git -c user.name=cosmo -c user.email=cosmo@test.invalid commit -q -m third && "
                   "git log --oneline | wc -l && git --no-pager log -1 --format=%s && git fsck --no-progress && cd /",
                   "commit")
    need(out, r"^commit=0$", "git add, commit and fsck in the clone")
    need(out, r"^\s*3$", "three commits after the commit")
    need(out, r"^third$", "the new commit's subject")
    out = b.run("git --version")
    ver = need(out, r"^(git version 2\.56\.1)$", "git --version").group(1)
    results.append(f"g. pkg install git; git clone over HTTPS (dumb protocol) gave the README and head {head[:12]} "
                   f"(2 commits); a commit made the third; git fsck clean; {ver!r}")


def stage_ports(args, results, inst):
    work = args.workdir
    tls, www = os.path.join(work, "tls"), os.path.join(work, "www")
    tlstest.make_test_certs(tls, ip="10.0.2.2")
    os.makedirs(www, exist_ok=True)
    shutil.copy(os.path.join(tls, "ca.pem"), os.path.join(www, "testca.pem"))
    publish(www, args.repo, args.sign_key, 1)
    server = tlstest.Server(www, tls, "server")
    untrusted = tlstest.Server(www, tls, "untrusted")
    plain = tlstest.Server(www)
    port = free_port()
    env = {"QEMU_DISKS": "boot", "QEMU_NET_HOSTFWD": f"tcp:127.0.0.1:{port}-:22"}
    b = Boot("ports", inst["target"], work, env, args.timeout)
    try:
        b.wait_prompt("the first prompt")
        # The boot is a long run of commands, so each has a budget of its own
        # (Boot.per_command): `pkg install git` (15 MiB fetched over HTTPS and
        # verified) took 146 s on x86-64 under TCG with this debug kernel
        # (2026-11-19), and AArch64 under TCG is the slower of the two.
        b.per_command(360)
        need(b.text(), r"^init: switched to the disk root \S+ ", "the installed boot")
        out = b.status(f"wget -q -O /tmp/testca.pem http://10.0.2.2:{plain.port}/testca.pem && "
                       "cat /tmp/testca.pem >> /etc/ssl/certs/ca-certificates.crt && "
                       f"echo 'ports https://10.0.2.2:{server.port}/ports' > /etc/pkg/repos.conf", "ca")
        need(out, r"^ca=0$", "the test CA in the bundle and the ports repository in repos.conf")

        # a. Install.
        out = b.status("pkg update && pkg install nano", "inst")
        need(out, r"^inst=0$", "pkg update && pkg install nano")
        need(out, r"^pkg: fetching nano-9\.3\.cpk from ports$", "nano fetched")
        files = need(out, r"^pkg: installing nano-9\.3 \((\d+) files?\)$", "nano installed").group(1)
        if "/ports/nano-9.3.cpk" not in server.paths():
            raise Fail(f"the server saw {server.paths()}; nano-9.3.cpk was not fetched from it")
        results.append(f"a. pkg update && pkg install nano: nano-9.3.cpk fetched over HTTPS, {files} files installed")

        stage_curl(b, results, www, server, untrusted)
        stage_git(b, results, work, www, server)

        login_key(work, b)
        waited = ssh_wait(work, port, strict=False)
        results.append(f"ssh: key login as root in {waited:.1f} s")
        stage_nano(work, results, port)

        # z. What the Linux personality lacked. First a call it lacks on
        # purpose (inotify_init1, from a program the system's own tcc
        # compiles), so the check is seen to find a line when there is one.
        out = b.status("printf '#include <stdio.h>\\n#include <unistd.h>\\n#include <sys/syscall.h>\\n"
                       "int main(void){printf(\"probe-pid=%%d\\\\n\",(int)getpid());fflush(stdout);"
                       "return syscall(SYS_inotify_init1,0)==-1?0:1;}\\n' > /tmp/unimpl.c && "
                       "tcc -o /tmp/unimpl /tmp/unimpl.c && /tmp/unimpl", "probe")
        need(out, r"^probe=0$", "the probe's inotify_init1 refused (tcc on the target)")
        probe = need(out, r"^probe-pid=(\d+)$", "the probe's pid").group(1)
        out = b.run("dmesg | grep 'unimplemented system call' ; echo dmesg-done")
        lines = re.findall(r"linux: pid (\d+) \(([^)]*)\): unimplemented system call (\d+)$", out, re.M)
        if not any(pid == probe and name == "unimpl" for pid, name, _ in lines):
            raise Fail(f"the probe (pid {probe}, unimpl) made a call the personality lacks and the kernel's log has "
                       f"no line for it: the check below would see nothing (a release kernel does not log DEBUG; "
                       f"test-ports runs on a debug build)")
        ported = sorted({f"{name}: system call {nr}" for _, name, nr in lines if name in PORT_PROGRAMS})
        if ported:
            raise Fail("system calls the Linux personality lacks, made by the ports:\n" + "\n".join(ported))
        base = sorted({f"{name} {nr}" for pid, name, nr in lines if pid != probe and name not in PORT_PROGRAMS})
        results.append(f"z. the kernel's log names the probe's unimplemented call (pid {probe}) and none made by "
                       f"{', '.join(sorted(PORT_PROGRAMS))}" +
                       (f"; the base system's, not this test's: {', '.join(base)}" if base else ""))
        rc = b.finish()
        if rc != install_test.EXIT_SUCCESS:
            raise Fail(f"ports boot: QEMU exit code {rc}")
    except Exception:
        b.kill()
        raise
    finally:
        server.shutdown()
        untrusted.shutdown()
        plain.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--repo", required=True, help="the ports repository (make server-ports's SERVER_REPO)")
    ap.add_argument("--sign-key", required=True, help="the key the build signed it with (PKGSIGN_KEY)")
    ap.add_argument("--arch", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--timeout", type=float, default=240.0, help="per boot")
    args = ap.parse_args()
    os.environ["TERM"] = "xterm-256color"   # what the ssh client asks the server's pty to be
    shutil.rmtree(args.workdir, ignore_errors=True)
    os.makedirs(args.workdir)
    results = []
    try:
        inst = install_test.stage_install(args, results)
        stage_ports(args, results, inst)
    except (Fail, tlstest.CertError) as e:
        for r in results:
            print(f"test-ports: {r}")
        print(f"test-ports: FAIL: {e} (logs in {args.workdir})")
        return 1
    for r in results:
        print(f"test-ports: {r}")
    print("test-ports: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
