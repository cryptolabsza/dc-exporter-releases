# DC Exporter Releases

Public binary releases for [dc-exporter-rs](https://github.com/cryptolabsza/dc-exporter-rs) - GPU Metrics Exporter for Prometheus.

## Download

**Latest Release:**

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

- **VRAM Temperature** - Memory temperature (not in dcgm-exporter)
- **Hotspot Temperature** - GPU junction temperature (not in dcgm-exporter)
- **Throttle Reasons** - Individual throttle reason breakdown
- **PCIe AER Errors** - PCIe bus error tracking
- **VM Passthrough Safe** - Non-interfering with GPU passthrough
- **Interactive TUI** - nvtop-like terminal interface

## Unique Metrics

```prometheus
DCGM_FI_DEV_VRAM_TEMP{gpu="0"} 72
DCGM_FI_DEV_HOT_SPOT_TEMP{gpu="0"} 78
DCGM_FI_DEV_CLOCKS_THROTTLE_REASON{reason="SwPowerCap",gpu="0"} 1
GPU_AER_TOTAL_ERRORS{gpu="0"} 0
GPU_ERROR_STATE{gpu="0"} 1
dc_exporter_build_info{version="0.1.0",build_timestamp="...",git_hash="..."} 1
```

## Systemd Service

```bash
cat > /etc/systemd/system/dc-exporter.service << 'SERVICE'
[Unit]
Description=DC Exporter - GPU Metrics for Prometheus
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/dc-exporter-rs --port 9835
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable --now dc-exporter
```

## Requirements

- Linux x86_64
- NVIDIA drivers (any version)
- Root access (for VRAM/Hotspot temps via direct register access)

## Links

- [All Releases](https://github.com/cryptolabsza/dc-exporter-releases/releases)
- [Checksums](https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/SHA256SUMS)
