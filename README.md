# DC Exporter Releases

Public binary releases for dc-exporter-rs - GPU Metrics Exporter for Prometheus.

## Download

**Latest Release:** https://github.com/cryptolabsza/dc-exporter-releases/releases/latest

## Installation

### Option 1: DEB Package (Recommended)

```bash
# Download and install (replace VERSION with actual version, e.g., 0.1.0)
curl -LO https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/dc-exporter-rs_0.1.0_amd64.deb
sudo dpkg -i dc-exporter-rs_*.deb

# Enable and start service
sudo systemctl enable --now dc-exporter

# Check status
sudo systemctl status dc-exporter
curl http://localhost:9835/metrics
```

The DEB package includes:
- Binary: `/usr/local/bin/dc-exporter-rs`
- Systemd service: `/etc/systemd/system/dc-exporter.service` (port 9835)

### Option 2: Direct Binary

```bash
curl -L https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/dc-exporter-rs \
  -o /usr/local/bin/dc-exporter-rs && chmod +x /usr/local/bin/dc-exporter-rs
```

## Quick Start

```bash
# HTTP server mode (Prometheus metrics on port 9835)
dc-exporter-rs --port 9835

# Interactive TUI mode (like nvtop)
dc-exporter-rs --tui

# One-shot mode (print metrics and exit)
dc-exporter-rs --one-shot
```

## Features

| Feature | Description |
|---------|-------------|
| **VRAM Temperature** | Memory temperature (not in dcgm-exporter) |
| **Hotspot Temperature** | GPU junction temperature (not in dcgm-exporter) |
| **Throttle Reasons** | Individual throttle reason breakdown |
| **PCIe AER Errors** | PCIe bus error tracking |
| **VM Passthrough Safe** | Non-interfering with GPU passthrough |
| **Interactive TUI** | nvtop-like terminal interface |
| **Build Info Metric** | Version, build timestamp, git hash |

## Unique Metrics

```prometheus
# VRAM/Memory temperature
DCGM_FI_DEV_VRAM_TEMP{gpu="0"} 72

# Hotspot/Junction temperature
DCGM_FI_DEV_HOT_SPOT_TEMP{gpu="0"} 78

# Throttle reasons (individual)
DCGM_FI_DEV_CLOCKS_THROTTLE_REASON{reason="SwPowerCap",gpu="0"} 1

# PCIe AER errors
GPU_AER_TOTAL_ERRORS{gpu="0"} 0

# GPU error state (1=OK, 2=Error, 0=Unknown, 3=VM_Passthrough)
GPU_ERROR_STATE{gpu="0"} 1

# Build info (version tracking)
dc_exporter_build_info{version="0.1.0",build_timestamp="...",git_hash="..."} 1
```

## Requirements

- Linux x86_64
- NVIDIA drivers (any version)
- glibc 2.35+ (Ubuntu 22.04+, Debian 12+, etc.)
- Root access (for VRAM/Hotspot temps via direct register access)

## Links

- [All Releases](https://github.com/cryptolabsza/dc-exporter-releases/releases)
- [Checksums](https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/SHA256SUMS)
