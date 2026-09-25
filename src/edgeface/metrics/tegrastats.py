"""Parse `tegrastats` output: RAM, swap, per-core CPU, GPU, power rails, temperatures.

Sample line (Jetson Nano, JetPack 4.6):
  RAM 1971/3956MB (lfb 25x4MB) SWAP 0/1978MB (cached 0MB) CPU [12%@1479,10%@1479,3%@1479,
  5%@1479] EMC_FREQ 0% GR3D_FREQ 0% PLL@31C CPU@33.5C PMIC@100C GPU@31C AO@39C
  thermal@32.25C POM_5V_IN 2085/2085 POM_5V_GPU 0/0 POM_5V_CPU 249/249

Fields differ between JetPack versions, so every field is optional: the parser returns
only what the line actually contains.
"""
import collections
import re
import subprocess
import threading

_RE_RAM = re.compile(r"RAM (\d+)/(\d+)MB")
_RE_SWAP = re.compile(r"SWAP (\d+)/(\d+)MB")
_RE_CPU = re.compile(r"CPU \[([^\]]+)\]")
_RE_CPU_CORE = re.compile(r"(\d+)%@(\d+)")
_RE_GR3D = re.compile(r"GR3D_FREQ (\d+)%")
_RE_EMC = re.compile(r"EMC_FREQ (\d+)%")
_RE_TEMP = re.compile(r"(\w+)@([\d.]+)C")
_RE_POWER = re.compile(r"(POM_[A-Z0-9_]+) (\d+)/(\d+)")


def parse_line(line):
    """tegrastats line -> dict. Missing fields are simply absent from the result."""
    out = {}
    m = _RE_RAM.search(line)
    if m:
        out["ram_used_mb"], out["ram_total_mb"] = int(m.group(1)), int(m.group(2))
    m = _RE_SWAP.search(line)
    if m:
        out["swap_used_mb"], out["swap_total_mb"] = int(m.group(1)), int(m.group(2))
    m = _RE_CPU.search(line)
    if m:
        cores = _RE_CPU_CORE.findall(m.group(1))
        out["cpu_pct"] = [int(p) for p, _ in cores]
        out["cpu_mhz"] = [int(f) for _, f in cores]
    m = _RE_GR3D.search(line)
    if m:
        out["gpu_pct"] = int(m.group(1))
    m = _RE_EMC.search(line)
    if m:
        out["emc_pct"] = int(m.group(1))
    temps = {k: float(v) for k, v in _RE_TEMP.findall(line)}
    if temps:
        out["temp_c"] = temps
    power = {}
    for rail, cur, avg in _RE_POWER.findall(line):
        power[rail] = {"cur_mw": int(cur), "avg_mw": int(avg)}
    if power:
        out["power_mw"] = power
    return out


class TegrastatsMonitor(object):
    """Run tegrastats in the background and collect samples.

    Usage:
        mon = TegrastatsMonitor(interval_ms=500)
        mon.start(); ...; mon.stop(); print(mon.summary())

    `tegrastats` exits silently when it is not available (dev machine): `available`
    becomes False and `summary()` returns {}.
    """

    def __init__(self, interval_ms=500, binary="tegrastats", sudo=False,
                 max_samples=0):
        self.interval_ms = interval_ms
        self.binary = binary
        self.sudo = sudo
        self.available = False
        # A benchmark wants every sample; a process that runs all day wants the last few
        # and no growing list. max_samples=0 keeps the benchmark behaviour.
        self.samples = collections.deque(maxlen=max_samples or None)
        self._proc = None
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        cmd = ([self.binary, "--interval", str(self.interval_ms)])
        if self.sudo:
            cmd = ["sudo", "-n"] + cmd
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                universal_newlines=True)
        except (OSError, ValueError):
            self.available = False
            return self
        self.available = True
        self._thread = threading.Thread(target=self._read_loop)
        self._thread.daemon = True
        self._thread.start()
        return self

    def _read_loop(self):
        for line in iter(self._proc.stdout.readline, ""):
            if self._stop.is_set():
                break
            sample = parse_line(line)
            if sample:
                self.samples.append(sample)

    def latest(self):
        """The newest sample, or {} before the first line arrives."""
        return self.samples[-1] if self.samples else {}

    def stop(self):
        self._stop.set()
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait()
            except Exception:  # pragma: no cover
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        return self

    def summary(self):
        """Peaks and means over the collected samples."""
        if not self.samples:
            return {}
        out = {"n_samples": len(self.samples)}
        rams = [s["ram_used_mb"] for s in self.samples if "ram_used_mb" in s]
        if rams:
            out["ram_peak_mb"] = max(rams)
            out["ram_mean_mb"] = sum(rams) / float(len(rams))
            out["ram_total_mb"] = self.samples[-1].get("ram_total_mb")
        gpus = [s["gpu_pct"] for s in self.samples if "gpu_pct" in s]
        if gpus:
            out["gpu_pct_mean"] = sum(gpus) / float(len(gpus))
            out["gpu_pct_peak"] = max(gpus)
        cpus = [s["cpu_pct"] for s in self.samples if "cpu_pct" in s]
        if cpus:
            n_cores = len(cpus[0])
            out["cpu_pct_mean_per_core"] = [
                sum(c[i] for c in cpus) / float(len(cpus)) for i in range(n_cores)]
            out["cpu_pct_mean_total"] = sum(out["cpu_pct_mean_per_core"])
        rails = {}
        for sample in self.samples:
            for rail, vals in sample.get("power_mw", {}).items():
                rails.setdefault(rail, []).append(vals["cur_mw"])
        if rails:
            out["power_mw"] = {
                rail: {"mean": sum(v) / float(len(v)), "peak": max(v)}
                for rail, v in rails.items()}
        temps = {}
        for sample in self.samples:
            for name, value in sample.get("temp_c", {}).items():
                temps.setdefault(name, []).append(value)
        if temps:
            out["temp_c_peak"] = {k: max(v) for k, v in temps.items()}
        return out
