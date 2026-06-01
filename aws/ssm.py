#!/usr/bin/env python3
"""SSM command runner for the sker-hermit EC2 instance.

Reads the instance ID from aws/.instance_id (saved by launch.py). Sends
a shell command via SSM RunShellScript, polls for completion, prints
stdout/stderr. No SSH key needed — SSM uses IAM-backed authentication.

Usage:
    python aws/ssm.py "tail -20 /var/log/sker-hermit-setup.log"
    python aws/ssm.py --timeout 300 "bash /home/ubuntu/clone_and_setup.sh"
    python aws/ssm.py --check <command-id>
    python aws/ssm.py --tail /home/ubuntu/foo.log
"""

import boto3
import time
import sys
import io
import argparse
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

REGION = "us-east-1"
INSTANCE_ID_FILE = Path(__file__).parent / '.instance_id'


def get_instance_id():
    """Return the instance ID saved by launch.py, or exit if none is recorded."""
    if INSTANCE_ID_FILE.exists():
        return INSTANCE_ID_FILE.read_text().strip()
    print("No instance ID found. Run 'python aws/launch.py' first.")
    sys.exit(1)


def run_commands(commands, timeout=120):
    """Send shell commands via SSM, poll to completion, print stdout/stderr; return True on success."""
    instance_id = get_instance_id()
    ssm = boto3.client("ssm", region_name=REGION)
    r = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
        TimeoutSeconds=timeout,
    )
    cmd_id = r["Command"]["CommandId"]
    print(f"Command: {cmd_id} (instance: {instance_id})")

    max_polls = timeout // 5 + 10
    for i in range(max_polls):
        time.sleep(5)
        try:
            inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
            status = inv["Status"]
            if status in ("Success", "Failed", "TimedOut", "Cancelled"):
                print(f"\nStatus: {status}")
                print("=== STDOUT ===")
                print(inv["StandardOutputContent"])
                if inv["StandardErrorContent"]:
                    print("=== STDERR ===")
                    print(inv["StandardErrorContent"][-3000:])
                return status == "Success"
        except Exception:
            pass
        if i % 6 == 0:
            print(f"  [{i * 5}s] waiting...")
    print("Timed out waiting for result")
    return False


def check_command(cmd_id):
    """Fetch and print the result (status + stdout/stderr tail) of a previously-sent SSM command."""
    instance_id = get_instance_id()
    ssm = boto3.client("ssm", region_name=REGION)
    inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
    print(f"Status: {inv['Status']}")
    print("=== STDOUT ===")
    print(inv["StandardOutputContent"][-8000:])
    if inv["StandardErrorContent"]:
        print("=== STDERR ===")
        print(inv["StandardErrorContent"][-3000:])


def tail_log(log_path, interval=5):
    """Poll a remote log file over SSM, printing only newly-appended bytes; Ctrl-C to stop."""
    print(f"Polling {log_path} every {interval}s. Ctrl-C to stop.")
    last_len = 0  # byte offset already printed; advances as the file grows
    try:
        while True:
            instance_id = get_instance_id()
            ssm = boto3.client("ssm", region_name=REGION)
            r = ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": [f"wc -c {log_path} 2>/dev/null && tail -c {last_len + 10000} {log_path} 2>/dev/null | tail -c +{last_len + 1}"]},
                TimeoutSeconds=30,
            )
            cmd_id = r["Command"]["CommandId"]
            time.sleep(2)
            for _ in range(10):
                try:
                    inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
                    if inv["Status"] in ("Success", "Failed", "TimedOut", "Cancelled"):
                        out = inv["StandardOutputContent"]
                        if out:
                            lines = out.splitlines()
                            if lines:
                                try:
                                    size = int(lines[0].split()[0])
                                    last_len = size
                                except Exception:
                                    pass
                                new_content = "\n".join(lines[1:])
                                if new_content.strip():
                                    print(new_content)
                        break
                except Exception:
                    pass
                time.sleep(1)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nTail stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("commands", nargs="*")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--check", type=str, metavar="CMD_ID")
    parser.add_argument("--tail", type=str, metavar="PATH")
    args = parser.parse_args()
    if args.check:    check_command(args.check)
    elif args.tail:   tail_log(args.tail)
    elif args.commands: run_commands(args.commands, timeout=args.timeout)
    else: parser.print_help()
