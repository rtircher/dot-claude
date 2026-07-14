#!/usr/bin/env bash
# Emits one JSON object describing this machine's capacity for a local
# inference stack: OS, container markers, CPU/RAM/disk, GPU vendor with total
# and FREE VRAM (free is what matters: other tenants may already hold memory),
# and whether ollama / opencode / node are already present.
# Read-only: probes only, changes nothing.
set -u

os=$(uname -s | tr '[:upper:]' '[:lower:]')
arch=$(uname -m)
cores=$( (command -v nproc >/dev/null 2>&1 && nproc) || sysctl -n hw.ncpu 2>/dev/null || echo 0)

if [ "$os" = darwin ]; then
  ram_gb=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 / 1024 / 1024 ))
else
  ram_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null)
  ram_gb=$(( ${ram_kb:-0} / 1024 / 1024 ))
fi

disk_free_gb=$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {print int($4/1024/1024)}')
disk_free_gb=${disk_free_gb:-0}

is_container=false
[ -f /.dockerenv ] && is_container=true
grep -qE 'docker|containerd|kubepods' /proc/1/cgroup 2>/dev/null && is_container=true

has_systemd=false
[ -d /run/systemd/system ] && has_systemd=true

gpu_vendor=none gpu_name="" vram_total_mb=0 vram_free_mb=0
if command -v nvidia-smi >/dev/null 2>&1; then
  line=$(nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
  if [ -n "$line" ]; then
    gpu_vendor=nvidia
    gpu_name=$(printf '%s' "$line" | cut -d, -f1 | sed 's/^ *//; s/ *$//')
    vram_total_mb=$(printf '%s' "$line" | cut -d, -f2 | tr -d ' ')
    vram_free_mb=$(printf '%s' "$line" | cut -d, -f3 | tr -d ' ')
  fi
elif command -v rocm-smi >/dev/null 2>&1; then
  # VRAM left 0: parse `rocm-smi --showmeminfo vram` by hand if this branch matters.
  gpu_vendor=amd
elif [ "$os" = darwin ] && [ "$arch" = arm64 ]; then
  gpu_vendor=apple
  gpu_name=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "Apple Silicon")
  # Unified memory: Metal lets a model use roughly 70% of RAM.
  vram_total_mb=$(( ram_gb * 1024 * 70 / 100 ))
  vram_free_mb=$vram_total_mb
fi

ollama_installed=false ollama_models="[]"
if command -v ollama >/dev/null 2>&1; then
  ollama_installed=true
  models=$(ollama list 2>/dev/null | awk 'NR>1 {printf "%s\"%s\"", (n++?",":""), $1}')
  ollama_models="[${models}]"
fi

opencode_installed=false
command -v opencode >/dev/null 2>&1 && opencode_installed=true

node_major=$(node -v 2>/dev/null | sed 's/^v//; s/\..*//')
node_major=${node_major:-0}

printf '{'
printf '"os":"%s","arch":"%s","cpu_cores":%s,"ram_gb":%s,"disk_free_gb":%s,' \
  "$os" "$arch" "$cores" "$ram_gb" "$disk_free_gb"
printf '"is_container":%s,"has_systemd":%s,' "$is_container" "$has_systemd"
printf '"gpu":{"vendor":"%s","name":"%s","vram_total_mb":%s,"vram_free_mb":%s},' \
  "$gpu_vendor" "$gpu_name" "$vram_total_mb" "$vram_free_mb"
printf '"ollama":{"installed":%s,"models":%s},' "$ollama_installed" "$ollama_models"
printf '"opencode_installed":%s,"node_major":%s' "$opencode_installed" "$node_major"
printf '}\n'
