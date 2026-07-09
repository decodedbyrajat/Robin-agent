import re

backends_to_remove = ["daytona", "modal", "singularity", "vercel_sandbox"]

def strip_file(filepath):
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return
        
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        drop = False
        for p in backends_to_remove:
            if f'"{p}"' in line or f"'{p}'" in line or f"== '{p}'" in line or f'== "{p}"' in line or f"{p}_image" in line or f"_{p}_" in line or f"from tools.environments.{p}" in line or f"from {p} import" in line:
                # We won't drop lines that have just the word unless it's specific syntax, 
                # but "modal", "daytona", "singularity" are fairly unique.
                # Let's drop lines containing the exact strings as part of lists or checks.
                # Actually, many lines are `if env_type in ("docker", "singularity", "modal", "daytona"):`
                pass
        
        # A safer regex replace for the lists:
        new_line = line
        for p in backends_to_remove:
            new_line = re.sub(r'\"' + p + r'\"(\s*,\s*)?', '', new_line)
            new_line = re.sub(r'\'' + p + r'\'(\s*,\s*)?', '', new_line)
            new_line = re.sub(r',\s*$', '', new_line.rstrip()) + "\n" if new_line.strip() else new_line
        
        # Clean up empty tuples/lists if it became empty
        new_line = new_line.replace('("docker", )', '("docker",)').replace("('docker', )", "('docker',)")
        
        # If the line is an `elif env_type == "daytona":` we should probably drop it and the block inside.
        # This is tough to parse perfectly. Since we are doing a quick strip, we can just replace the references and let dead code be dead code, or use a proper tool. Let's just drop lines that start with `elif env_type == "daytona":`
        if any(f'env_type == "{p}"' in new_line or f"env_type == '{p}'" for p in backends_to_remove):
            # drop this line and the next few indented lines
            pass # skipping block logic is hard here

        out.append(new_line)
        i += 1
        
    with open(filepath, 'w') as f:
        f.writelines(out)

for f in ["tools/terminal_tool.py", "tools/approval.py", "tools/code_execution_tool.py", "tools/file_operations.py", "tools/file_tools.py"]:
    strip_file("/Users/ifthenvoid/Robin/Robin_V4/" + f)
