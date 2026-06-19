import json
import os
import re

json_dir = r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master\files\json"

def check_formula_vars(filename):
    fpath = os.path.join(json_dir, filename)
    print(f"\n===== Checking Formula Variables in {filename} =====")
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    controls = data.get("control_variables", {})
    indicators = data.get("indicator_variables", {})
    calculated = data.get("calculated_variables", {})
    
    all_defined = set(controls.keys()) | set(indicators.keys()) | set(calculated.keys())
    
    # We find all words enclosed in backticks, or other variable-like patterns
    for name, cfg in calculated.items():
        formula = cfg.get("formula")
        if not formula:
            continue
            
        # Extract variables from formula. In these formulas, variables are usually enclosed in backticks
        # Let's find all backticked names
        vars_found = re.findall(r'`([^`]+)`', formula)
        
        # If no backticks, let's also split by non-alphanumeric characters
        if not vars_found:
            # simple parser for variables that don't have spaces (like tag names)
            tokens = re.split(r'[^a-zA-Z0-9_\(\)\% ]', formula)
            for t in tokens:
                t = t.strip()
                if t and not t.isdigit() and t.lower() not in ['true', 'false', 'and', 'or', 'not']:
                    vars_found.append(t)
                    
        for v in vars_found:
            v = v.strip()
            if v not in all_defined:
                print(f"  ❌ WARNING: In formula for '{name}', variable '{v}' is NOT defined in config.")
            else:
                print(f"  [OK] In formula for '{name}', variable '{v}' is defined.")

check_formula_vars("model_config.json")
check_formula_vars("model_confignew.json")
