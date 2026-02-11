# DC Exporter

GPU Metrics Exporter for Prometheus with **unique metrics not available in dcgm-exporter**.

## Download

| Channel | Link | Description |
|---------|------|-------------|
| **Stable** | [Latest Release](https://github.com/cryptolabsza/dc-exporter-releases/releases/latest) | Production-ready |
| **Dev** | [dev-latest](https://github.com/cryptolabsza/dc-exporter-releases/releases/tag/dev-latest) | Testing builds |

### Quick Download

```bash
# Download latest stable binary
curl -L https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/dc-exporter-rs \
  -o /usr/local/bin/dc-exporter-rs
chmod +x /usr/local/bin/dc-exporter-rs
```

## Installation

### Option 1: DEB Package (Recommended)

```bash
# Download latest DEB package
curl -LO https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/dc-exporter-rs_amd64.deb
sudo dpkg -i dc-exporter-rs_amd64.deb

# Enable and start service
sudo systemctl enable --now dc-exporter

# Verify
curl http://localhost:9835/metrics | head -10
```

**What's included:**
- Binary: `/usr/local/bin/dc-exporter-rs`
- Systemd service: `/etc/systemd/system/dc-exporter.service`
- Auto-starts on port 9835

### Option 2: Manual Setup

```bash
# Download binary
curl -L https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/dc-exporter-rs \
  -o /usr/local/bin/dc-exporter-rs
chmod +x /usr/local/bin/dc-exporter-rs

# Create systemd service
cat > /etc/systemd/system/dc-exporter.service << 'EOF'
[Unit]
Description=DC Exporter - GPU Metrics for Prometheus
After=network.target nvidia-persistenced.service

[Service]
Type=simple
ExecStart=/usr/local/bin/dc-exporter-rs --port 9835
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
systemctl daemon-reload
systemctl enable --now dc-exporter
```

## Usage

```bash
# HTTP server (default)
dc-exporter-rs --port 9835

# Interactive TUI (like nvtop)
dc-exporter-rs --tui

# One-shot (print and exit)
dc-exporter-rs --one-shot

# Help
dc-exporter-rs --help
```

## Unique Metrics

These metrics are **not available in dcgm-exporter**:

| Metric | Description |
|--------|-------------|
| `DCGM_FI_DEV_VRAM_TEMP` | VRAM/Memory temperature |
| `DCGM_FI_DEV_HOT_SPOT_TEMP` | Hotspot/Junction temperature |
| `DCGM_FI_DEV_CLOCKS_THROTTLE_REASON` | Individual throttle reasons |
| `GPU_AER_TOTAL_ERRORS` | PCIe AER error count |
| `GPU_ERROR_STATE` | GPU health (1=OK, 2=Error, 0=Unknown, 3=VM) |
| `dc_exporter_build_info` | Version, timestamp, git hash |

**Example:**
```prometheus
DCGM_FI_DEV_VRAM_TEMP{gpu="0"} 72
DCGM_FI_DEV_HOT_SPOT_TEMP{gpu="0"} 78
DCGM_FI_DEV_CLOCKS_THROTTLE_REASON{reason="SwPowerCap",gpu="0"} 1
GPU_ERROR_STATE{gpu="0"} 1
dc_exporter_build_info{version="0.2.0",build_timestamp="1769457515",git_hash="d7631b9"} 1
```

## Features

- **VRAM & Hotspot temps** - Direct register access (RTX 30/40/50, L40, Professional)
- **VM Passthrough Safe** - Non-interfering, collects from VMs via guest agent
- **Throttle Reasons** - Individual breakdown (thermal, power, etc.)
- **Interactive TUI** - nvtop-like terminal interface
- **Build Info** - Track deployed versions via Prometheus
- **Rate Limited** - Protection against DoS
- **Watchdog** - Auto-recovery from stuck NVML

## Supported GPUs

| Type | Models |
|------|--------|
| **Consumer** | RTX 5090/5080/5070, RTX 4090/4080/4070/4060, RTX 3090/3080/3070 |
| **Professional** | RTX 6000/5000/4500/4000 Ada, RTX A6000/A5000/A4500/A2000 |
| **Datacenter** | H100, H200, A100, A40, A30, L40S, L40, L4 |

## Requirements

- Linux x86_64
- NVIDIA drivers (any version with NVML)
- glibc 2.35+ (Ubuntu 22.04+, Debian 12+)
- Root access (for VRAM/Hotspot temps)

### Optional: Enable VRAM/Hotspot Temperature

Add to `/etc/default/grub`:
```
GRUB_CMDLINE_LINUX="iomem=relaxed"
```

Then run:
```bash
sudo update-grub && sudo reboot
```

## Service Management

```bash
systemctl start dc-exporter      # Start
systemctl stop dc-exporter       # Stop
systemctl restart dc-exporter    # Restart
systemctl status dc-exporter     # Status
journalctl -u dc-exporter -f     # Logs
```

## Updating

```bash
systemctl stop dc-exporter
curl -L https://github.com/cryptolabsza/dc-exporter-releases/releases/latest/download/dc-exporter-rs \
  -o /usr/local/bin/dc-exporter-rs
chmod +x /usr/local/bin/dc-exporter-rs
systemctl start dc-exporter
curl http://localhost:9835/metrics | grep build_info
```

## Prometheus Configuration

```yaml
scrape_configs:
  - job_name: 'dc-exporter'
    scrape_interval: 15s
    static_configs:
      - targets:
        - 'server1:9835'
        - 'server2:9835'
```

## Grafana Dashboard

A pre-built Grafana dashboard is included in the `dashboards/` directory.

### Import Dashboard

1. Open Grafana → Dashboards → Import
2. Upload `dashboards/DC_Exporter_Details.json` or paste the JSON
3. Select your Prometheus data source
4. Click Import

### Dashboard Features

| Panel | Description |
|-------|-------------|
| **Total GPU Count** | Number of GPUs being monitored |
| **Hosts with GPUs** | Number of unique hosts |
| **GPU Utilization** | Real-time utilization graph |
| **GPU Temperatures** | Core, Hotspot, and VRAM temps |
| **GPU Power** | Usage vs Limit |
| **Fan Speed** | Fan speed percentage |
| **PCIe Throughput** | TX/RX bandwidth |
| **NVENC/NVDEC** | Encoder/Decoder utilization |
| **GPU Memory** | Used vs Free |
| **GPU Processes** | Compute/Graphics process count |
| **GPU Clocks** | SM and Memory clock speeds |
| **PCIe AER Errors** | Error count table |
| **GPU Error State** | Health status (OK/Error/VM) |
| **GPU Inventory** | Table of all GPUs with details |

### Quick Download

```bash
# Download dashboard JSON directly
curl -L https://raw.githubusercontent.com/cryptolabsza/dc-exporter-releases/main/dashboards/DC_Exporter_Details.json \
  -o DC_Exporter_Details.json
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
sudo systemctl daemon-reload
```

## License

MIT License - CryptoLabs ZA
