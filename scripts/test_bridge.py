#!/usr/bin/env python3
import subprocess
import os

env = os.environ.copy()
env["XDG_RUNTIME_DIR"] = "/run/user/1000"
env["HOME"] = "/home/w"

# Test using shell=True with full command
cmd = "muvm -i curl -s http://127.0.0.1:43111/health"
print(f"Running: {cmd}")
result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)
print("=== HEALTH ===")
print("stdout:", result.stdout)
print("stderr:", result.stderr)
print("returncode:", result.returncode)

# Try with curl directly if muvm fails
print("\n=== TRY DIRECT ===")
cmd2 = "curl -s http://127.0.0.1:43111/health"
result2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True, timeout=5)
print("stdout:", result2.stdout)
print("stderr:", result2.stderr)
print("returncode:", result2.returncode)
