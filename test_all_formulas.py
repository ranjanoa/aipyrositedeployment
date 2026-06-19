import json
import os
import pandas as pd
import numpy as np
import traceback
import re

json_dir = r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master\files\json"

def preprocess_formula(formula, sorted_variable_names):
    processed = formula
    for v in sorted_variable_names:
        if any(c in v for c in ' /-()+*%'):
            pattern = r'(?<![`\w])' + re.escape(v) + r'(?![`\w])'
            processed = re.sub(pattern, f"`{v}`", processed)
    return processed

def test_config(filename):
    fpath = os.path.join(json_dir, filename)
    print(f"\n========================================")
    print(f"TESTING FORMULAS IN {filename}")
    print(f"========================================")
    
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    controls_cfg = data.get("control_variables", {})
    indicators_cfg = data.get("indicator_variables", {})
    calc_vars_cfg = data.get("calculated_variables", {})
    
    # Generate dummy state map
    state_map = {}
    for k, v in {**controls_cfg, **indicators_cfg}.items():
        tag = v.get('tag_name', k)
        state_map[tag] = 50.0  # mock value
        state_map[k] = 50.0
        
    # Also mock formula targets
    for k, v in calc_vars_cfg.items():
        friendly = v.get('friendly_name', k)
        state_map[friendly] = 50.0
        state_map[k] = 50.0
        
    temp_df = pd.DataFrame([state_map])
    
    lookup_keys = set(controls_cfg.keys()) | set(indicators_cfg.keys()) | {v.get('friendly_name', k) for k, v in calc_vars_cfg.items()}
    sorted_vars = sorted(list(lookup_keys), key=len, reverse=True)
    
    for key, cfg in calc_vars_cfg.items():
        formula = cfg.get('formula')
        friendly_name = cfg.get('friendly_name')
        if not formula or not friendly_name:
            print(f"Skipping {key} (no formula or friendly_name)")
            continue
            
        processed_formula = preprocess_formula(formula, sorted_vars)
        print(f"Evaluating {friendly_name}:")
        print(f"  Raw formula: {formula}")
        print(f"  Processed:   {processed_formula}")
        try:
            result = temp_df.eval(processed_formula)
            print(f"  Result type: {type(result)} | Shape: {getattr(result, 'shape', 'N/A')}")
            # If the result has shape, verify it
            if isinstance(result, pd.DataFrame):
                print(f"  ⚠️ WARNING: eval returned a DataFrame for variable '{friendly_name}'!")
            elif isinstance(result, pd.Series):
                val = result.iloc[0]
                print(f"  Value: {val}")
            else:
                print(f"  Value: {result}")
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            traceback.print_exc(limit=2)

test_config("model_config.json")
test_config("model_confignew.json")
