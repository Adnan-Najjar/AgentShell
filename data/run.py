#!/usr/bin/env python3

import json
import subprocess
import time

# Read commands from file
with open('commands.txt', 'r') as f:
    commands = [line.strip() for line in f if line.strip()]

# Initialize output dictionary
output = {}

# Execute each command
for cmd in commands:
    print(f"Executing: {cmd}")
    
    # Execute SSH command
    ssh_cmd = ['sshpass', '-p', 'password', 'ssh', '-p', '2222', '-o', 'LogLevel=ERROR', 'root@localhost', cmd]
    
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True)
        output[cmd] = result.stdout or result.stderr
        print(f"Output: {output[cmd]}")
    except Exception as e:
        output[cmd] = f"Error: {str(e)}"
    
    # Small delay to avoid overwhelming Cowrie
    time.sleep(3)

# Write output to JSON file
with open('output.json', 'w') as f:
    json.dump(output, f, indent=2)

print("Completed!")
