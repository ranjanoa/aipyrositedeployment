import json
import os

json_dir = r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master\files\json"

def check_dynamic_tags(filename):
    fpath = os.path.join(json_dir, filename)
    print(f"\n===== Checking Dynamic Reference Tags in {filename} =====")
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    controls = data.get("control_variables", {})
    indicators = data.get("indicator_variables", {})
    calculated = data.get("calculated_variables", {})
    
    # All defined friendly names
    all_friendly = set(controls.keys()) | set(indicators.keys()) | set(calculated.keys())
    # Also add the tag_names just in case they are referenced by tag_name
    all_tags = set()
    for sect in [controls, indicators, calculated]:
        for k, v in sect.items():
            all_tags.add(v.get('tag_name', k))
            
    all_defined = all_friendly | all_tags
    
    for section_name, section in [("control_variables", controls), ("indicator_variables", indicators), ("calculated_variables", calculated)]:
        for var_name, var_data in section.items():
            for attr in ['dynamic_sp_tag', 'dynamic_min_tag', 'dynamic_max_tag']:
                ref = var_data.get(attr)
                if ref:
                    if ref not in all_defined:
                        print(f"  [ERROR] {section_name} -> '{var_name}' references non-existent {attr}: '{ref}'")
                    else:
                        print(f"  [OK] {section_name} -> '{var_name}' references {attr}: '{ref}'")

check_dynamic_tags("model_config.json")
check_dynamic_tags("model_confignew.json")
