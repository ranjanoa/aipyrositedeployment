import ast
import os

def check_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content, filepath)
    except Exception as e:
        # print(f"Error parsing {filepath}: {e}")
        return
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    # Check if the slice is a List or Tuple (meaning assigning to multiple columns)
                    if isinstance(target.slice, (ast.List, ast.Tuple)):
                        col_names = []
                        for el in target.slice.elts:
                            if isinstance(el, ast.Constant):
                                col_names.append(el.value)
                            elif isinstance(el, ast.Name):
                                col_names.append(el.id)
                        
                        # Print the line and files
                        print(f"\n[ASSIGN] File: {filepath} (Line {node.lineno})")
                        print(f"  Target columns: {col_names}")
                        try:
                            # Print the source code line
                            lines = content.splitlines()
                            print(f"  Source: {lines[node.lineno-1].strip()}")
                        except:
                            pass

def main():
    for root, dirs, files in os.walk(r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master"):
        for f in files:
            if f.endswith(".py"):
                check_file(os.path.join(root, f))

if __name__ == "__main__":
    main()
