import socket
import shutil

from pathlib import Path

def get_hostname() -> str:
    return socket.gethostname()

def get_uptime() -> float:
    with open("/proc/uptime", "r") as f:
        uptime_seconds = float(f.readline().split()[0])

    return uptime_seconds

def get_load_average() -> list[float]:
    with open("/proc/loadavg", "r") as f:
        load_avg = f.readline().split()[:3]

    return [float(avg) for avg in load_avg]

def get_memory_info() -> tuple[float, float]:
    with open("/proc/meminfo", "r") as f:
        meminfo = f.readlines()

    mem_total_kb = float(meminfo[0].split()[1])
    mem_available_kb = float(meminfo[2].split()[1])

    return round(mem_total_kb / 1024, 2), round(mem_available_kb / 1024, 2)

def get_disk_usage(path: str = "/") -> tuple[float, float, float]:
    if not Path(path).exists():
        raise FileNotFoundError(f"Path does not exist {path}")

    usage = shutil.disk_usage(path)
    
    total_gb = round(usage.total / (1024 ** 3), 2)
    used_gb = round(usage.used / (1024 ** 3), 2)
    free_gb = round(usage.free / (1024 ** 3), 2)

    return total_gb, used_gb, free_gb

