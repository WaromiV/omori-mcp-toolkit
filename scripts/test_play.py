#!/usr/bin/env python3
import os
import json
import time

os.environ["XDG_RUNTIME_DIR"] = "/run/user/1000"
os.environ["HOME"] = "/home/w"

# Get initial state
print("=== STATE ===")
os.system("muvm -i curl -s http://127.0.0.1:43111/state")

print("\n=== MOVE RIGHT ===")
os.system(
    "muvm -i curl -s -X POST -H 'Content-Type: application/json' -d '{\"id\":\"move_right\"}' http://127.0.0.1:43111/action"
)

time.sleep(1)

print("\n=== STATE AFTER ===")
os.system("muvm -i curl -s http://127.0.0.1:43111/state")
