import json
import os

json_path = r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master\files\json\model_config.json"

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)
    calc_vars = data.get("calculated_variables", {})
    print(f"Total calculated variables: {len(calc_vars)}")
    for k, v in calc_vars.items():
        print(f"Key: {repr(k)}")
        for prop_k, prop_v in v.items():
            print(f"  {prop_k}: {repr(prop_v)}")
