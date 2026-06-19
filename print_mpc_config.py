import json
import os

json_dir = r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master\files\json"

for f in ["model_config.json", "model_confignew.json"]:
    fpath = os.path.join(json_dir, f)
    with open(fpath, "r", encoding="utf-8") as file:
        data = json.load(file)
        print(f"\n--- {f} ---")
        print("pirl_mpc_config:", data.get("pirl_mpc_config"))
        print("ai_bindings:", data.get("ai_bindings"))
        ai_mnm = data.get("ai_mnm")
        if ai_mnm:
            print("ai_mnm cv_parameters keys:", list(ai_mnm.get("cv_parameters", {}).keys()))
            print("ai_mnm indicator_parameters keys:", list(ai_mnm.get("indicator_parameters", {}).keys()))
        else:
            print("ai_mnm: None")
