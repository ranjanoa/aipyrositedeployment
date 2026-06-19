import json
import os

json_dir = r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master\files\json"

with open(os.path.join(json_dir, "model_configorig.json"), "r", encoding="utf-8") as f:
    orig = json.load(f)

with open(os.path.join(json_dir, "model_confignew.json"), "r", encoding="utf-8") as f:
    new_cfg = json.load(f)

if orig == new_cfg:
    print("model_configorig.json and model_confignew.json are IDENTICAL.")
else:
    print("model_configorig.json and model_confignew.json are DIFFERENT.")
    # Show diff
    for k in set(orig.keys()) | set(new_cfg.keys()):
        if k not in orig:
            print(f"Key {k} is in new but not in orig")
        elif k not in new_cfg:
            print(f"Key {k} is in orig but not in new")
        elif orig[k] != new_cfg[k]:
            print(f"Value diff for key {k}:")
            if isinstance(orig[k], dict) and isinstance(new_cfg[k], dict):
                added = set(new_cfg[k].keys()) - set(orig[k].keys())
                removed = set(orig[k].keys()) - set(new_cfg[k].keys())
                if added: print(f"  Added: {added}")
                if removed: print(f"  Removed: {removed}")
                for subk in set(orig[k].keys()) & set(new_cfg[k].keys()):
                    if orig[k][subk] != new_cfg[k][subk]:
                        print(f"  Subkey '{subk}' diff")
            else:
                print(f"  orig: {orig[k]}")
                print(f"  new: {new_cfg[k]}")
