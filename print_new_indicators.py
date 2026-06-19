import json
import os

json_dir = r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master\files\json"

with open(os.path.join(json_dir, "model_confignew.json"), "r", encoding="utf-8") as f:
    data = json.load(f)

added_keys = ['Kiln hood P', 'Target Temp. Burner Zone', 'PLC_KilnFeed_HH', 'Target Temp Secondary Air', 
              'Target Temp. C4', 'Target Chlorine', 'Target Kiln Head Pressure', 'Target Free Lime', 'PLC_KilnFeed_LL']

print("--- NEW INDICATOR VARIABLES DETAILS ---")
inds = data.get("indicator_variables", {})
for k in added_keys:
    print(f"Key: {repr(k)}")
    if k in inds:
        print(f"  details: {inds[k]}")
    else:
        print("  Not found in indicator_variables.")
