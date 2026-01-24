# DC Exporter

GPU Metrics Exporter for Prometheus with **unique metrics not available in dcgm-exporter**.

## Download

| File | Description |
|------|-------------|
| [dc-exporter-rs_0.1.0_amd64.deb](https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/dc-exporter-rs_0.1.0_amd64.deb) | DEB package (recommended) |
| [dc-exporter-rs](https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/dc-exporter-rs) | Standalone binary |
| [SHA256SUMS](https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/SHA256SUMS) | Checksums |

**All Releases:** https://github.com/cryptolabsza/dc-exporter-releases/releases

## Installation

### DEB Package (Recommended)

```bash
curl -LO https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/dc-exporter-rs_0.1.0_amd64.deb
sudo dpkg -i dc-exporter-rs_0.1.0_amd64.deb
sudo systemctl enable --now dc-exporter
```

**Verify:**
```bash
sudo systemctl status dc-exporter
curl http://localhost:9835/metrics
```

**Package contents:**
- `/usr/local/bin/dc-exporter-rs` - Binary
- `/etc/systemd/system/dc-exporter.service` - Systemd service (port 9835)

### Direct Binary

```bash
sudo curl -L https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/dc-exporter-rs \
  -o /usr/local/bin/dc-exporter-rs
sudo chmod +x /usr/local/bin/dc-exporter-rs
```

## Usage

```bash
# HTTP server mode (Prometheus metrics)
dc-exporter-rs --port 9835

# Interactive TUI mode (like nvtop)
dc-exporter-rs --tui

# One-shot mode (print and exit)
dc-exporter-rs --one-shot

# Help
dc-exporter-rs --help
```

## Unique Metrics

These metrics are **not available in the official dcgm-exporter**:

| Metric | Description |
|--------|-------------|
| `DCGM_FI_DEV_VRAM_TEMP` | VRAM/Memory temperature |
| `DCGM_FI_DEV_HOT_SPOT_TEMP` | Hotspot/Junction temperature |
| `DCGM_FI_DEV_CLOCKS_THROTTLE_REASON` | Individual throttle reasons |
| `GPU_AER_TOTAL_ERRORS` | PCIe AER error count |
| `GPU_ERROR_STATE` | GPU health state (1=OK, 2=Error, 0=Unknown, 3=VM) |
| `dc_exporter_build_info` | Version, build timestamp, git hash |

**Example output:**
```prometheus
DCGM_FI_DEV_VRAM_TEMP{gpu="0",UUID="GPU-xxx",modelName="NVIDIA GeForce RTX 4090"} 72
DCGM_FI_DEV_HOT_SPOT_TEMP{gpu="0",UUID="GPU-xxx",modelName="NVIDIA GeForce RTX 4090"} 78
DCGM_FI_DEV_CLOCKS_THROTTLE_REASON{reason="SwPowerCap",gpu="0"} 1
GPU_ERROR_STATE{gpu="0"} 1
dc_exporter_build_info{version="0.1.0",build_timestamp="1769295035",git_hash="c4cd78f"} 1
```

## Features

- **VRAM & Hotspot temps** - Direct register access for RTX 30/40/50 series, Professional, L40
- **VM Passthrough Safe** - Non-interfering, collects metrics from VMs via guest agent
- **Throttle Reasons** - Individual breakdown (thermal, power cap, etc.)
- **Interactive TUI** - nvtop-like terminal interface with graphs
- **Build Info** - Track deployed versions via Prometheus

## Supported GPUs

| Type | GPUs |
|------|------|
| **Consumer** | RTX 5090/5080/5070, RTX 4090/4080/4070/4060, RTX 3090/3080/3070 |
| **Professional** | RTX 6000/5000/4500/4000 Ada, RTX A6000/A5000/A4500 |
| **Datacenter** | H100, H200, A100, A40, A30, L40S, L40, L4 |

## Requirements

- Linux x86_64
- NVIDIA drivers (any version)
- glibc 2.35+ (Ubuntu 22.04+, Debian 12+)
- Root access (for VRAM/Hotspot temps)
- `iomem=relaxed` kernel parameter (optional, for direct register access)

## Prometheus Configuration

```yaml
scrape_configs:
  - job_name: 'dc-exporter'
    static_configs:
      - targets:
        - 'server1:9835'
        - 'server2:9835'
```

## Uninstall

```bash
# DEB package
sudo dpkg -r dc-exporter-rs

# Manual
sudo systemctl stop dc-exporter
sudo systemctl disable dc-exporter
sudo rm /usr/local/bin/dc-exporter-rs
sudo rm /etc/systemd/system/dc-exporter.service
```

## License

MIT License - CryptoLabs ZA
