#!/usr/bin/env python3
"""Read-only check of whether native code will give useful profiler stacks.

Inspects an ELF binary, or every executable mapping of a running process, with
GNU readelf: symbol tables, embedded or separate debuginfo, build-id, unwind
tables, frame-pointer and optimisation switches recorded in DW_AT_producer,
the linked allocator, and whether a JVM is loaded in the process.

Nothing is attached, written, or fetched over the network. PROC_ROOT and
HOST_ROOT redirect /proc and the file-system root for tests.

Exit status: 0 report produced, 1 no ELF object recognised, 2 bad arguments,
3 target unreadable or changed during the check.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROC_ROOT = Path(os.environ.get("PROC_ROOT", "/proc"))
HOST_ROOT = Path(os.environ.get("HOST_ROOT", "/"))
READELF_TIMEOUT = 60
ALLOCATOR_LIBS = (("jemalloc", "libjemalloc"), ("tcmalloc", "libtcmalloc"), ("mimalloc", "libmimalloc"))
FLAG = re.compile(r"^(-O\S*|-g\S*|-march=\S+|-flto\S*|-fprofile-use\S*|-fsanitize=\S+|-m(no-)?omit-leaf-frame-pointer)$")
SECTION = re.compile(r"^\s*\[\s*\d+\]\s+(\S+)", re.M)


class TargetError(Exception):
    pass


def readelf(args, path):
    try:
        run = subprocess.run(["readelf", "-W", *args, str(path)], capture_output=True,
                             text=True, errors="replace", timeout=READELF_TIMEOUT)
    except subprocess.TimeoutExpired:
        return ""
    return run.stdout


def is_elf(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def find_debug_file(logical, actual, build_id, debuglink):
    candidates = []
    if build_id and len(build_id) > 2:
        candidates.append(HOST_ROOT / "usr/lib/debug/.build-id" / build_id[:2] / f"{build_id[2:]}.debug")
    if debuglink:
        candidates += [actual.parent / debuglink, actual.parent / ".debug" / debuglink,
                       HOST_ROOT / "usr/lib/debug" / logical.parent.relative_to("/") / debuglink]
    return next((c for c in candidates if is_elf(c)), None)


def frame_pointers(producer):
    tokens = producer.split()
    setting = None
    for token in tokens:
        if token in ("-fomit-frame-pointer", "-fno-omit-frame-pointer"):
            setting = token
    if setting:
        return "kept" if setting == "-fno-omit-frame-pointer" else "omitted"
    opts = [t for t in tokens if t.startswith("-O")]
    return "kept" if opts and opts[-1] == "-O0" else "unspecified"


def summarise_producers(producers):
    compiled = [p for p in producers if not p.startswith("GNU AS")]
    if not compiled:
        return {"frame_pointers": "unknown", "flags": [], "compilers": []}
    states = {frame_pointers(p) for p in compiled}
    if len(states) > 1:
        fp = "mixed"
    else:
        fp = {"kept": "kept", "omitted": "omitted", "unspecified": "compiler_default"}[states.pop()]
    flags = sorted({t for p in compiled for t in p.split() if FLAG.match(t)})
    compilers = sorted({p.split(" -", 1)[0].strip() for p in compiled})
    return {"frame_pointers": fp, "flags": flags, "compilers": compilers}


def inspect(logical, actual):
    head = readelf(["-h", "-S", "-n", "-d"], actual)
    sections = set(SECTION.findall(head))
    build_id = (re.search(r"Build ID: ([0-9a-f]+)", head) or [None, None])[1]
    needed = re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", head)
    elf_type = (re.search(r"^\s*Type:\s+(\w+)", head, re.M) or [None, None])[1]
    debuglink = None
    if ".gnu_debuglink" in sections:
        dump = readelf(["--string-dump=.gnu_debuglink"], actual)
        debuglink = (re.search(r"^\s*\[\s*0\]\s+(\S+)", dump, re.M) or [None, None])[1]

    debug_source = None
    if ".debug_info" in sections:
        debuginfo, debug_source = "embedded", actual
    else:
        debug_source = find_debug_file(logical, actual, build_id, debuglink)
        if debug_source:
            debuginfo = "separate"
        else:
            debuginfo = "separate_missing" if debuglink else "none"
    producers = set()
    if debug_source:
        info = readelf(["--debug-dump=info", "--dwarf-depth=1"], debug_source)
        # "(strp) (offset: 0xd1): GNU C++17 ..." or "(string) GNU C11 ..."
        producers = {re.sub(r"^(\([^)]*\)\s*)+:?\s*", "", v)
                     for v in re.findall(r"DW_AT_producer\s*:\s*(.+)$", info, re.M)}

    symbols = "full" if ".symtab" in sections else "dynamic_only" if ".dynsym" in sections else "none"
    result = {
        "path": str(logical),
        "elf_type": elf_type,
        "build_id": build_id,
        "symbols": symbols,
        "debuginfo": debuginfo,
        "debug_file": str(debug_source) if debuginfo == "separate" else None,
        "eh_frame": ".eh_frame" in sections,
        "needed": needed,
        "symbolised": symbols == "full" or debuginfo in ("embedded", "separate"),
    }
    result.update(summarise_producers(producers))
    return result


def proc_identity(pid):
    base = PROC_ROOT / str(pid)
    try:
        status = (base / "status").read_text()
        stat = (base / "stat").read_text()
    except OSError as e:
        raise TargetError(f"cannot read /proc/{pid}: {e.strerror}") from None
    uid = int(re.search(r"^Uid:\s+\d+\s+(\d+)", status, re.M)[1])
    start = stat.rsplit(")", 1)[1].split()[19]
    try:
        exe = os.readlink(base / "exe")
    except OSError:
        exe = None
    return {"uid": uid, "exe": exe, "start_ticks": start}


def mapped_objects(pid):
    try:
        maps = (PROC_ROOT / str(pid) / "maps").read_text()
    except OSError as e:
        raise TargetError(f"cannot read /proc/{pid}/maps: {e.strerror} (run as the target's user)") from None
    seen = {}
    for line in maps.splitlines():
        fields = line.split(None, 5)
        if len(fields) == 6 and "x" in fields[1] and fields[5].startswith("/"):
            path = fields[5]
            deleted = path.endswith(" (deleted)")
            seen.setdefault(path[: -len(" (deleted)")] if deleted else path, deleted)
    return seen


def resolve(pid, logical):
    if pid is not None:
        in_ns = PROC_ROOT / str(pid) / "root" / logical.lstrip("/")
        if is_elf(in_ns):
            return in_ns
    return HOST_ROOT / logical.lstrip("/")


def status_of(objects):
    main, rest = objects[0], objects[1:]
    if not main["symbolised"]:
        return "DEGRADED_MAIN_UNSYMBOLISED"
    if any(not o["symbolised"] for o in rest):
        return "PARTIAL_LIBRARIES_UNSYMBOLISED"
    return "READY_SYMBOLISED"


def call_graph(objects):
    known = [o["frame_pointers"] for o in objects if o["frame_pointers"] != "unknown"]
    if known and all(fp == "kept" for fp in known) and len(known) == len(objects):
        return "fp"
    if all(o["eh_frame"] for o in objects):
        return "dwarf"
    return "dwarf (some objects lack .eh_frame; expect truncated stacks)"


def build_report(args):
    pid = args.pid
    identity = None
    if pid is not None:
        identity = proc_identity(pid)
        mappings = mapped_objects(pid)
        exe = identity["exe"]
        if exe and exe.endswith(" (deleted)"):
            exe = exe[: -len(" (deleted)")]
        order = sorted(mappings, key=lambda p: p != exe)
    else:
        path = Path(args.binary)
        if not is_elf(path):
            return None
        mappings = {str(path.resolve()): False}
        order = list(mappings)

    objects, skipped = [], []
    for logical in order[: args.max_objects]:
        actual = resolve(pid, logical) if pid is not None else Path(logical)
        if not is_elf(actual):
            skipped.append(logical)
            continue
        obj = inspect(Path(logical), actual)
        obj["deleted_since_start"] = mappings[logical]
        objects.append(obj)
    if not objects:
        return None
    if pid is not None and proc_identity(pid) != identity:
        raise TargetError(f"process {pid} changed during the check; re-run against a stable target")

    names = [Path(o["path"]).name for o in objects] + [n for o in objects for n in o["needed"]]
    allocator = next((a for a, lib in ALLOCATOR_LIBS if any(n.startswith(lib) for n in names)), "glibc")
    return {
        "target": {"pid": pid, **identity} if pid is not None else {"binary": objects[0]["path"]},
        "status": status_of(objects),
        "recommended_call_graph": call_graph(objects),
        "jvm_in_process": any(n.startswith("libjvm.so") for n in names),
        "allocator": allocator,
        "debuginfod_urls_set": bool(os.environ.get("DEBUGINFOD_URLS", "").strip()),
        "objects_truncated": len(order) > args.max_objects,
        "unreadable": skipped,
        "objects": objects,
    }


def print_text(report):
    t = report["target"]
    print(f"target: pid {t['pid']} uid {t['uid']}" if "pid" in t else f"target: {t['binary']}")
    for key in ("status", "recommended_call_graph", "jvm_in_process", "allocator", "debuginfod_urls_set"):
        print(f"{key}: {report[key]}")
    if report["allocator"] == "glibc":
        print("  (no jemalloc, tcmalloc, or mimalloc library linked; a statically linked allocator is not detected)")
    if report["objects_truncated"]:
        print("objects_truncated: true (raise --max-objects to see every mapping)")
    for path in report["unreadable"]:
        print(f"unreadable: {path}")
    for o in report["objects"]:
        print(f"\n{o['path']}{'  [DELETED since process start]' if o['deleted_since_start'] else ''}")
        print(f"  symbols={o['symbols']} debuginfo={o['debuginfo']} build_id={o['build_id'] or 'none'}"
              f" eh_frame={'yes' if o['eh_frame'] else 'no'} frame_pointers={o['frame_pointers']}")
        if o["debug_file"]:
            print(f"  debug_file={o['debug_file']}")
        if o["compilers"]:
            print(f"  compilers={'; '.join(o['compilers'])}")
        if o["flags"]:
            print(f"  flags={' '.join(o['flags'])}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--binary", help="ELF executable or shared library to inspect")
    target.add_argument("--pid", type=int, help="running process whose executable mappings to inspect")
    parser.add_argument("--max-objects", type=int, default=64, help="most mapped objects to inspect (default 64)")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()
    if args.pid is not None and args.pid <= 0 or args.max_objects <= 0:
        parser.error("--pid and --max-objects must be positive")
    try:
        report = build_report(args)
    except TargetError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    if report is None:
        print("error: no readable ELF object found", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
