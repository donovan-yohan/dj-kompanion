# GPU Analyzer Setup (Proxmox + Tailscale)

Offload the analyzer to a Proxmox server with a GTX 1080 for CUDA-accelerated analysis.

## Architecture

```
Mac (local)                          Proxmox (beanworld)
┌─────────────────┐                  ┌──────────────────────────┐
│ Chrome Extension │                  │ LXC / VM                 │
│       ↓          │                  │ ┌──────────────────────┐ │
│ Server (:9234)   │──tailnet:9235──→ │ │ Analyzer (GPU)       │ │
│ - yt-dlp         │                  │ │ - PyTorch + CUDA     │ │
│ - tagging        │                  │ │ - Demucs             │ │
│ - VDJ writes     │                  │ │ - allin1             │ │
│                  │                  │ └──────────────────────┘ │
│ ~/Music/DJ Lib ←─sshfs over tailnet─→ /mnt/dj-library (mount) │
└─────────────────┘                  └──────────────────────────┘
```

## Step 1: Create an LXC Container on Proxmox

In the Proxmox web UI (`https://beanworld:8006/`):

1. Create a new **privileged** LXC container (GPU passthrough requires privileged)
   - Template: Ubuntu 22.04
   - Disk: 30GB+
   - RAM: 4GB+
   - CPU: 4+ cores
   - Check "Nesting" under Features

2. Pass through the GPU. Edit the container config on the Proxmox host:

   ```bash
   # SSH into the Proxmox host
   nano /etc/pve/lxc/<CTID>.conf
   ```

   Add these lines:

   ```
   lxc.cgroup2.devices.allow: c 195:* rwm
   lxc.cgroup2.devices.allow: c 509:* rwm
   lxc.mount.entry: /dev/nvidia0 dev/nvidia0 none bind,optional,create=file
   lxc.mount.entry: /dev/nvidiactl dev/nvidiactl none bind,optional,create=file
   lxc.mount.entry: /dev/nvidia-uvm dev/nvidia-uvm none bind,optional,create=file
   lxc.mount.entry: /dev/nvidia-uvm-tools dev/nvidia-uvm-tools none bind,optional,create=file
   ```

3. Install NVIDIA drivers on the **Proxmox host** (must match driver version inside container):

   ```bash
   # On Proxmox host
   apt install pve-headers-$(uname -r)
   apt install nvidia-driver
   nvidia-smi  # verify GPU is visible
   ```

4. Start the LXC and install matching NVIDIA drivers inside:

   ```bash
   # Inside the LXC
   apt update && apt install -y nvidia-driver-535  # match host version
   nvidia-smi  # verify GPU passthrough works
   ```

## Step 2: Install Docker + NVIDIA Runtime in LXC

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh

# Install NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt update && apt install -y nvidia-container-toolkit

# Configure Docker to use the NVIDIA runtime
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

# Verify GPU is visible to Docker
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

## Step 3: Install Tailscale in LXC

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up
```

Note the Tailscale hostname (e.g., `beanworld-analyzer`) or use the Proxmox host's existing Tailscale IP if routing through it.

## Step 4: Mount Music Library via sshfs over Tailscale

On your **Mac**, enable Remote Login (SSH):
- System Settings → General → Sharing → Remote Login → On

On the **LXC**:

```bash
apt install -y sshfs

# Create mount point
mkdir -p /mnt/dj-library

# Mount via Tailscale hostname (replace YOUR_MAC_HOSTNAME and YOUR_USERNAME)
sshfs YOUR_USERNAME@YOUR_MAC_HOSTNAME:"Music/DJ Library" /mnt/dj-library \
  -o allow_other,reconnect,ServerAliveInterval=15,ServerAliveCountMax=3

# Verify
ls /mnt/dj-library
```

To make it persistent across reboots, add to `/etc/fstab`:

```
YOUR_USERNAME@YOUR_MAC_HOSTNAME:Music/DJ\ Library /mnt/dj-library fuse.sshfs allow_other,reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,_netdev 0 0
```

For passwordless auth, copy your SSH key:

```bash
ssh-keygen -t ed25519  # if you don't have one
ssh-copy-id YOUR_USERNAME@YOUR_MAC_HOSTNAME
```

## Step 5: Deploy the GPU Analyzer

Copy the project to the LXC (or clone from git):

```bash
# From your Mac
scp -r analyzer/ docker-compose.gpu.yml root@beanworld-analyzer:/opt/dj-kompanion/
```

On the LXC:

```bash
cd /opt/dj-kompanion
docker compose -f docker-compose.gpu.yml up -d

# Verify GPU is being used
docker compose -f docker-compose.gpu.yml logs -f
```

First run will build the image and download models (~10 min). After that, startup is seconds.

## Step 6: Point Local Server at Remote Analyzer

On your **Mac**, update the config:

```bash
nano ~/.config/dj-kompanion/config.yaml
```

Change:

```yaml
analysis:
  analyzer_url: http://beanworld-analyzer:9235
```

(Use whatever Tailscale hostname or IP the LXC has.)

Restart your local server and test — analysis should now run on GPU.

## Expected Performance

| Stage | CPU (Rosetta) | GTX 1080 |
|-------|--------------|----------|
| Demucs separation | ~4 min | ~15-30 sec |
| allin1 inference | ~2 min | ~10-20 sec |
| Key detection | ~5 sec | ~5 sec (CPU-bound) |
| **Total** | **~6 min** | **~30-60 sec** |

## Troubleshooting

**`nvidia-smi` not found in LXC:**
Driver version mismatch between host and container. Ensure both run the same NVIDIA driver version.

**sshfs mount is empty:**
Check that Remote Login is enabled on Mac and the Tailscale connection is up (`tailscale ping YOUR_MAC_HOSTNAME`).

**Analyzer can't find audio files:**
The path inside the container is `/audio`. Verify the sshfs mount is at `/mnt/dj-library` and `docker-compose.gpu.yml` maps it correctly.

**CUDA out of memory:**
GTX 1080 has 8GB VRAM. Demucs uses ~3-4GB. If other processes use the GPU, you may need to stop them first.

**Container can't reach HuggingFace:**
Ensure the LXC has internet access. Check DNS and `curl https://huggingface.co` from inside the container.
