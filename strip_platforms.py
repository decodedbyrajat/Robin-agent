import re
import sys

platforms_to_remove = [
    "matrix", "mattermost", "dingtalk", "feishu", "wecom", "wecom_callback",
    "weixin", "bluebubbles", "qqbot", "homeassistant", "webhook"
]

def strip_file(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()
        
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # If this line matches any condition to drop, skip it (and possibly subsequent lines if it's a block, but let's just do line-by-line first)
        drop = False
        for p in platforms_to_remove:
            if f"Platform.{p.upper()}" in line or \
               f"    {p.upper()} = " in line or \
               f"{p}_cfg =" in line or \
               f"{p}_token =" in line or \
               f"{p}_url =" in line or \
               f"{p}_app" in line:
                drop = True
                break
        
        # Special logic: If it drops, we might have blocks like `if matrix_token:` on the next line.
        # This is a bit risky. A safer approach is to leave them as dead code or just do a manual replace.
        if not drop:
            out.append(line)
        i += 1
        
    with open(filepath, 'w') as f:
        f.writelines(out)

if __name__ == "__main__":
    strip_file("/Users/ifthenvoid/Robin/Robin_V4/gateway/config.py")
