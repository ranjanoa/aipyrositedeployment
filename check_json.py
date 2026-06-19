import json
import os

json_dir = r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master\files\json"

def load_json(name):
    fpath = os.path.join(json_dir, name)
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {name}: {e}")
        return None

orig = load_json("model_configorig.json")
curr = load_json("model_config.json")
new_cfg = load_json("model_confignew.json")

if not orig or not curr:
    print("Failed to load configs.")
    exit(1)

# Compare top-level keys
print("--- TOP-LEVEL KEYS COMPARISON ---")
print(f"Original keys count: {len(orig.keys())}")
print(f"Current keys count: {len(curr.keys())}")
added_top = set(curr.keys()) - set(orig.keys())
removed_top = set(orig.keys()) - set(curr.keys())
print(f"Added top-level keys: {added_top}")
print(f"Removed top-level keys: {removed_top}")

# Compare control, indicator, and calculated variables
for sec in ["control_variables", "indicator_variables", "calculated_variables"]:
    print(f"\n--- {sec.upper()} COMPARISON ---")
    orig_sec = orig.get(sec, {})
    curr_sec = curr.get(sec, {})
    
    print(f"Original items count: {len(orig_sec)}")
    print(f"Current items count: {len(curr_sec)}")
    
    added = set(curr_sec.keys()) - set(orig_sec.keys())
    removed = set(orig_sec.keys()) - set(curr_sec.keys())
    
    if added:
        print(f"Added keys in current ({len(added)}): {list(added)[:15]}")
        if len(added) > 15:
            print("...")
    if removed:
        print(f"Removed keys in current ({len(removed)}): {list(removed)[:15]}")
        if len(removed) > 15:
            print("...")

    # Compare properties inside each common key
    common = set(orig_sec.keys()) & set(curr_sec.keys())
    diff_props = {}
    for key in common:
        orig_val = orig_sec[key]
        curr_val = curr_sec[key]
        if isinstance(orig_val, dict) and isinstance(curr_val, dict):
            for pk, pv in orig_val.items():
                if pk not in curr_val:
                    diff_props.setdefault(key, []).append(f"Missing prop: {pk}")
                elif curr_val[pk] != pv:
                    diff_props.setdefault(key, []).append(f"Value diff for {pk}: original={pv} vs current={curr_val[pk]}")
            for pk, pv in curr_val.items():
                if pk not in orig_val:
                    diff_props.setdefault(key, []).append(f"Added prop: {pk}")
        elif orig_val != curr_val:
            diff_props[key] = [f"Value diff: original={orig_val} vs current={curr_val}"]
            
    if diff_props:
        print(f"Common keys with different properties ({len(diff_props)}):")
        for k, diffs in list(diff_props.items())[:10]:
            print(f"  - {k}: {diffs}")
        if len(diff_props) > 10:
            print("  ...")

# Check formulas inside calculated variables
print("\n--- FORMULAS IN CALCULATED VARIABLES ---")
for key, cfg in curr.get("calculated_variables", {}).items():
    formula = cfg.get("formula")
    friendly_name = cfg.get("friendly_name")
    print(f"{key} (friendly: {friendly_name}): formula={formula}")

# Check reactive_governor and hcf_config
print("\n--- REACTIVE GOVERNOR & HCF CONFIG ---")
for k in ["reactive_governor", "hcf_config"]:
    print(f"\n{k} original:")
    print(json.dumps(orig.get(k), indent=2))
    print(f"{k} current:")
    print(json.dumps(curr.get(k), indent=2))
