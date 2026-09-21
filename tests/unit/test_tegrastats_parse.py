from edgeface.metrics.tegrastats import TegrastatsMonitor, parse_line

LINE = ("RAM 1971/3956MB (lfb 25x4MB) SWAP 0/1978MB (cached 0MB) "
        "CPU [12%@1479,10%@1479,3%@1479,5%@1479] EMC_FREQ 0% GR3D_FREQ 47% "
        "PLL@31C CPU@33.5C PMIC@100C GPU@31C AO@39C thermal@32.25C "
        "POM_5V_IN 2085/2085 POM_5V_GPU 124/60 POM_5V_CPU 249/249")


def test_parse_full_line():
    s = parse_line(LINE)
    assert s["ram_used_mb"] == 1971 and s["ram_total_mb"] == 3956
    assert s["swap_used_mb"] == 0
    assert s["cpu_pct"] == [12, 10, 3, 5]
    assert s["cpu_mhz"] == [1479] * 4
    assert s["gpu_pct"] == 47 and s["emc_pct"] == 0
    assert s["temp_c"]["GPU"] == 31.0 and s["temp_c"]["CPU"] == 33.5
    assert s["power_mw"]["POM_5V_IN"] == {"cur_mw": 2085, "avg_mw": 2085}
    assert s["power_mw"]["POM_5V_GPU"]["avg_mw"] == 60


def test_parse_partial_and_garbage():
    assert parse_line("RAM 100/3956MB") == {"ram_used_mb": 100, "ram_total_mb": 3956}
    assert parse_line("") == {}
    assert parse_line("hello world") == {}


def test_summary_aggregates():
    mon = TegrastatsMonitor()
    mon.samples = [parse_line(LINE), parse_line(LINE.replace("RAM 1971", "RAM 2500")
                                                .replace("GR3D_FREQ 47%", "GR3D_FREQ 99%"))]
    s = mon.summary()
    assert s["n_samples"] == 2
    assert s["ram_peak_mb"] == 2500
    assert s["gpu_pct_peak"] == 99 and s["gpu_pct_mean"] == 73.0
    assert s["cpu_pct_mean_per_core"] == [12.0, 10.0, 3.0, 5.0]
    assert s["power_mw"]["POM_5V_IN"]["peak"] == 2085
    assert s["temp_c_peak"]["PMIC"] == 100.0


def test_monitor_without_tegrastats_binary():
    mon = TegrastatsMonitor(binary="definitely-not-a-binary").start()
    assert mon.available is False
    assert mon.stop().summary() == {}
