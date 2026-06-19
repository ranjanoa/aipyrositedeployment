import json
import os

json_dir = r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master\files\json"

with open(os.path.join(json_dir, "model_config.json"), "r", encoding="utf-8") as f:
    curr = json.load(f)

with open(os.path.join(json_dir, "model_confignew.json"), "r", encoding="utf-8") as f:
    new_cfg = json.load(f)

print("--- KEY DIFFERENCES ---")
for k in set(curr.keys()) | set(new_cfg.keys()):
    if k not in curr:
        print(f"[+] Key '{k}' is ONLY in model_confignew.json")
    elif k not in new_cfg:
        print(f"[-] Key '{k}' is ONLY in model_config.json")
    elif curr[k] != new_cfg[k]:
        print(f"[*] Key '{k}' is DIFFERENT:")
        if isinstance(curr[k], dict) and isinstance(new_cfg[k], dict):
            added = set(new_cfg[k].keys()) - set(curr[k].keys())
            removed = set(curr[k].keys()) - set(new_cfg[k].keys())
            if added:
                print(f"    Added subkeys in new: {added}")
            if removed:
                print(f"    Removed subkeys in new: {removed}")
            for subk in set(curr[k].keys()) & set(new_cfg[k].keys()):
                if curr[k][subk] != new_cfg[k][subk]:
                    print(f"    Subkey '{subk}' differs.")
                    if isinstance(curr[k][subk], dict) and isinstance(new_cfg[k][subk], dict):
                        print(f"      Current keys: {list(curr[k][subk].keys())}")
                        print(f"      New keys: {list(new_cfg[k][subk].keys())}")
        elif isinstance(curr[k], list) and isinstance(new_cfg[k], list):
            print(f"    Current list len: {len(curr[k])}")
            print(f"    New list len: {len(new_cfg[k])}")
        else:
            print(f"    Current value: {curr[k]}")
            print(f"    New value: {new_cfg[k]}")
