import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "skills/cpp-build-readiness/scripts/native-build-check.py"
SOURCE = "#include <stdio.h>\nint work(int n) { return n * 3; }\nint main(void) { printf(\"%d\\n\", work(2)); return 0; }\n"
TOOLS = ("gcc", "readelf", "objcopy", "strip")


def run(args, env=None):
    return subprocess.run(["python3", str(SCRIPT), *args, "--json"], capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


@unittest.skipUnless(all(shutil.which(t) for t in TOOLS), "needs gcc and binutils")
class NativeBuildCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "app.c").write_text(SOURCE)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def compile(self, name, *flags):
        out = self.tmp / name
        subprocess.run(["gcc", *flags, "-Wl,--build-id", "-o", str(out), str(self.tmp / "app.c")], check=True)
        return out

    def report(self, *args, env=None):
        proc = run(args, env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_debug_build_with_frame_pointers_is_ready_for_fp_stacks(self):
        binary = self.compile("debug", "-O2", "-g", "-fno-omit-frame-pointer")
        result = self.report("--binary", str(binary))
        obj = result["objects"][0]
        self.assertEqual(result["status"], "READY_SYMBOLISED")
        self.assertEqual(result["recommended_call_graph"], "fp")
        self.assertEqual((obj["symbols"], obj["debuginfo"], obj["frame_pointers"]), ("full", "embedded", "kept"))
        self.assertIn("-O2", obj["flags"])
        self.assertTrue(obj["build_id"])
        self.assertFalse(result["jvm_in_process"])
        self.assertEqual(result["allocator"], "glibc")

    def test_stripped_build_is_degraded_and_frame_pointers_unknown(self):
        binary = self.compile("stripped", "-O2")
        subprocess.run(["strip", str(binary)], check=True)
        result = self.report("--binary", str(binary))
        obj = result["objects"][0]
        self.assertEqual(result["status"], "DEGRADED_MAIN_UNSYMBOLISED")
        self.assertEqual((obj["symbols"], obj["debuginfo"], obj["frame_pointers"]), ("dynamic_only", "none", "unknown"))
        self.assertEqual(result["recommended_call_graph"], "dwarf")

    def test_separate_debuginfo_found_by_build_id(self):
        binary = self.compile("split", "-O2", "-g")
        build_id = self.report("--binary", str(binary))["objects"][0]["build_id"]
        store = self.tmp / "root/usr/lib/debug/.build-id" / build_id[:2]
        store.mkdir(parents=True)
        subprocess.run(["objcopy", "--only-keep-debug", str(binary), str(store / f"{build_id[2:]}.debug")], check=True)
        subprocess.run(["strip", str(binary)], check=True)
        result = self.report("--binary", str(binary), env={"HOST_ROOT": str(self.tmp / "root")})
        obj = result["objects"][0]
        self.assertEqual(result["status"], "READY_SYMBOLISED")
        self.assertEqual((obj["symbols"], obj["debuginfo"]), ("dynamic_only", "separate"))
        self.assertEqual(obj["frame_pointers"], "compiler_default")

    def test_missing_debuglink_target_is_reported(self):
        binary = self.compile("linked", "-O2", "-g")
        debug = self.tmp / "linked.debug"
        subprocess.run(["objcopy", "--only-keep-debug", str(binary), str(debug)], check=True)
        subprocess.run(["strip", str(binary)], check=True)
        subprocess.run(["objcopy", f"--add-gnu-debuglink={debug}", str(binary)], check=True)
        debug.unlink()
        result = self.report("--binary", str(binary), env={"HOST_ROOT": str(self.tmp / "empty")})
        self.assertEqual(result["objects"][0]["debuginfo"], "separate_missing")

    def test_non_elf_is_not_recognised(self):
        proc = run(["--binary", str(self.tmp / "app.c")])
        self.assertEqual(proc.returncode, 1)

    def test_pid_mode_reads_maps_detects_jvm_allocator_and_replaced_binary(self):
        binary = self.compile("server", "-O2", "-g")
        host = self.tmp / "host"
        for rel in ("opt/app/server", "opt/jdk/lib/server/libjvm.so", "opt/lib/libjemalloc.so.2"):
            (host / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(binary, host / rel)
        proc = self.tmp / "proc/4242"
        proc.mkdir(parents=True)
        (proc / "status").write_text("Name:\tserver\nUid:\t1000\t1000\t1000\t1000\n")
        (proc / "stat").write_text("4242 (my server) S " + " ".join(["0"] * 18) + " 777 0\n")
        (proc / "maps").write_text(
            "7f0000000000-7f0000001000 r-xp 00000000 08:01 1 /opt/jdk/lib/server/libjvm.so\n"
            "7f0000002000-7f0000003000 r--p 00000000 08:01 2 /opt/lib/not-executable.so\n"
            "7f0000004000-7f0000005000 r-xp 00000000 08:01 3 /opt/lib/libjemalloc.so.2\n"
            "7f0000006000-7f0000007000 r-xp 00000000 00:00 0 \n"
            "55aa00000000-55aa00001000 r-xp 00000000 08:01 4 /opt/app/server (deleted)\n")
        os.symlink("/opt/app/server (deleted)", proc / "exe")
        result = self.report("--pid", "4242", env={"PROC_ROOT": str(self.tmp / "proc"), "HOST_ROOT": str(host)})
        self.assertEqual([o["path"] for o in result["objects"]],
                         ["/opt/app/server", "/opt/jdk/lib/server/libjvm.so", "/opt/lib/libjemalloc.so.2"])
        self.assertTrue(result["objects"][0]["deleted_since_start"])
        self.assertTrue(result["jvm_in_process"])
        self.assertEqual(result["allocator"], "jemalloc")
        self.assertEqual((result["target"]["uid"], result["target"]["start_ticks"]), (1000, "777"))

    def test_unreadable_target_exits_3(self):
        (self.tmp / "proc/99").mkdir(parents=True)
        proc = run(["--pid", "99"], {"PROC_ROOT": str(self.tmp / "proc")})
        self.assertEqual(proc.returncode, 3)
        self.assertIn("cannot read", proc.stderr)


if __name__ == "__main__":
    unittest.main()
