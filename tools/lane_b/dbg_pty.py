#!/usr/bin/env python3
# Lane B: run the DOSBox-X rig under a pty so the ncurses debugger can be driven headlessly.
# The debugger (Debug menu / Alt+Pause) is only enabled when stdin/stdout/stderr are TTYs
# (gui/sdlmain.cpp does isatty() checks), so the relaunch.sh setsid+>/dev/null start hides it.
#
# Usage:
#   dbg_pty.py start "<dosbox command line>"   # spawn under pty, return
#   dbg_pty.py cmd "MEMDUMPBIN 50:0 A0000 x.bin"   # append one debugger command line
# Output (raw curses ANSI) -> /mnt/nvme/tlrb2/logs/dbg_pty.log
# Commands are appended to /mnt/nvme/tlrb2/logs/dbg.cmd; the parent polls it and writes to the pty.
import os, sys, time, pty, fcntl, termios, struct, select, signal

LOG = "/mnt/nvme/tlrb2/logs/dbg_pty.log"
CMDF = "/mnt/nvme/tlrb2/logs/dbg.cmd"
PIDF = "/mnt/nvme/tlrb2/logs/dosboxx.pid"

def start(cmdline):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 160, 0, 0))
    pid = os.fork()
    if pid == 0:
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        os.dup2(slave, 0); os.dup2(slave, 1); os.dup2(slave, 2)
        if slave > 2: os.close(slave)
        os.close(master)
        os.environ["TERM"] = "xterm"
        os.environ["DISPLAY"] = ":98"
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        os.environ.setdefault("SDL_VIDEODRIVER", "x11")
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.chdir("/mnt/nvme/tlrb2/logs")
        os.execv("/bin/bash", ["/bin/bash", "-c", cmdline])
    os.close(slave)
    with open(PIDF, "w") as f: f.write(str(pid))
    with open(CMDF, "wb") as f: pass   # truncate command file
    with open(LOG, "wb") as log: pass
    pos = 0
    while True:
        r, _, _ = select.select([master], [], [], 0.2)
        if r:
            try: data = os.read(master, 65536)
            except OSError: break
            if not data: break
            with open(LOG, "ab") as log: log.write(data)
        try:
            sz = os.path.getsize(CMDF)
        except FileNotFoundError:
            sz = 0
        if sz > pos:
            with open(CMDF, "rb") as f:
                f.seek(pos); chunk = f.read(); pos = sz
            for line in chunk.split(b"\n"):
                if line.startswith(b"\x00RAW:"):
                    os.write(master, line[5:].replace(b"\x00", b""))
                elif line.strip():
                    os.write(master, line.strip() + b"\r")
                time.sleep(0.05)
        # exit when the child is gone
        try:
            done, st = os.waitpid(pid, os.WNOHANG)
            if done:
                with open(LOG, "ab") as log: log.write(b"\n[[child exited]]\n")
                return
        except ChildProcessError:
            return

if __name__ == "__main__":
    if sys.argv[1] == "start":
        start(sys.argv[2])
    elif sys.argv[1] == "cmd":
        with open(CMDF, "a") as f: f.write(sys.argv[2] + "\n")
    elif sys.argv[1] == "raw":
        # raw bytes to the pty (e.g. F5 = ESC [ 1 5 ~ for ncurses)
        with open(CMDF, "a") as f: f.write("\x00RAW:" + sys.argv[2].encode().decode("unicode_escape") + "\x00\n")
