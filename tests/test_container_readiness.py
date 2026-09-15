import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "skills/profiling-readiness/scripts/container-readiness.py"


class ContainerReadinessTest(unittest.TestCase):
    def test_reports_fake_cgroup_and_namespace_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "self/ns").mkdir(parents=True)
            (root / "321/ns").mkdir(parents=True)
            (root / "321").mkdir(exist_ok=True)
            (root / "321/status").write_text(
                "Uid:\t1000\t1000\nGid:\t1000\t1000\n"
                "Cpus_allowed_list:\t2-3\nMems_allowed_list:\t0\n"
                "CapEff:\t0000000000000000\nNoNewPrivs:\t1\nSeccomp:\t2\n")
            (root / "321/cgroup").write_text("0::/kubepods.slice/pod-x\n")
            os.symlink("pid:[1]", root / "self/ns/pid")
            os.symlink("mnt:[2]", root / "self/ns/mnt")
            os.symlink("pid:[1]", root / "321/ns/pid")
            os.symlink("mnt:[3]", root / "321/ns/mnt")
            cgroup = root / "cgroup/kubepods.slice/pod-x"
            cgroup.mkdir(parents=True)
            (cgroup / "cpu.max").write_text("100000 100000\n")
            run = subprocess.run(
                ["python3", str(SCRIPT), "--pid", "321"],
                env={**os.environ, "PROC_ROOT": str(root), "CGROUP_ROOT": str(root / "cgroup")},
                capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            self.assertEqual(result["cgroup_version"], "v2")
            self.assertEqual(result["cpus_allowed"], "2-3")
            self.assertTrue(result["same_pid_namespace_as_checker"])
            self.assertFalse(result["same_mount_namespace_as_checker"])


if __name__ == "__main__":
    unittest.main()
