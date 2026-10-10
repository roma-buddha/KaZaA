"""After-finish actions (all tasks done)."""
import os
import subprocess
import sys


def perform(action):
    if action == "exit":
        return
    if sys.platform != "win32":
        return
    cmds = {
        "shutdown": [["shutdown", "/s", "/t", "30"]],
        "restart": [["shutdown", "/r", "/t", "30"]],
        "logoff": [["shutdown", "/l"]],
        "hibernate": [["rundll32.exe", "powrprof.dll,SetSuspendState", "1,1,0"]],
        "standby": [["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]],
    }
    for argv in cmds.get(action, []):
        try:
            subprocess.Popen(argv)
        except OSError:
            pass


def confirm_text(action):
    return {
        "shutdown": "Shut down the computer when all tasks finish?",
        "restart": "Restart the computer when all tasks finish?",
        "logoff": "Log off when all tasks finish?",
        "hibernate": "Hibernate when all tasks finish?",
        "standby": "Stand by when all tasks finish?",
    }.get(action, "")
