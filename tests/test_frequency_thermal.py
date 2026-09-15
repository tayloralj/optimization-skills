import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "skills/profiling-readiness/scripts/frequency-thermal-snapshot.py"


class FrequencyThermalTest(unittest.TestCase):
    def test_reads_fake_cpu_thermal_and_energy_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cpu = root / "sys/devices/system/cpu/cpu0/cpufreq"
            cpu.mkdir(parents=True)
            (cpu / "scaling_cur_freq").write_text("3500000\n")
            (cpu / "scaling_governor").write_text("performance\n")
            (root / "sys/devices/system/cpu/cpufreq").mkdir(parents=True)
            (root / "sys/devices/system/cpu/cpufreq/boost").write_text("1\n")
            thermal = root / "sys/class/thermal/thermal_zone0"
            thermal.mkdir(parents=True)
            (thermal / "type").write_text("x86_pkg_temp\n")
            (thermal / "temp").write_text("42000\n")
            power = root / "sys/class/powercap/intel-rapl:0"
            power.mkdir(parents=True)
            (power / "name").write_text("package-0\n")
            (power / "energy_uj").write_text("1234\n")
            run = subprocess.run(["python3", str(SCRIPT), "--root", str(root)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            self.assertEqual(result["cpus"][0]["scaling_governor"], "performance")
            self.assertEqual(result["thermal_zones"][0]["temp"], "42000")
            self.assertEqual(result["powercap_zones"][0]["name"], "package-0")


if __name__ == "__main__":
    unittest.main()
