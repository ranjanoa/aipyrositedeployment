import ast
import os

def check_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content, filepath)
    except Exception as e:
        return
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    lines = content.splitlines()
                    source_line = lines[node.lineno-1].strip()
                    val_name = ""
                    if isinstance(target.value, ast.Name):
                        val_name = target.value.id
                    elif isinstance(target.value, ast.Attribute) and isinstance(target.value.value, ast.Name):
                        val_name = f"{target.value.value.id}.{target.value.attr}"
                    
                    if any(x in val_name.lower() for x in ["df", "real", "future", "hist", "data", "train", "state", "action"]):
                        print(f"[ASSIGN] {os.path.relpath(filepath)}:{node.lineno} -> {source_line}")

def main():
    for root, dirs, files in os.walk(r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master"):
        for f in files:
            if f.endswith(".py"):
                if f in ["check_duplicates.py", "compare_new_and_current.py", "print_calc_vars.py", "print_mpc_config.py", "run_validation.py", "find_dataframe_assignments.py", "find_subscript_assignments.py", "find_target_assignments.py"]:
                    continue
                check_file(os.path.join(root, f))

if __name__ == "__main__":
    main()
