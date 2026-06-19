import json
import os

json_dir = r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master\files\json"

def check_file(filename):
    fpath = os.path.join(json_dir, filename)
    print(f"\n===== Checking duplicates in {filename} =====")
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    tag_to_friendly = {}
    friendly_names = set()
    
    sections = ['control_variables', 'indicator_variables', 'calculated_variables']
    for section in sections:
        items = data.get(section, {})
        for friendly_name, item_data in items.items():
            tag_name = item_data.get('tag_name', friendly_name)
            
            # Check for duplicate friendly names
            if friendly_name in friendly_names:
                print(f"  WARNING: Duplicate friendly name '{friendly_name}' found in section '{section}'")
            friendly_names.add(friendly_name)
            
            # Check for duplicate tag_names (many-to-one or mapping issues)
            if tag_name in tag_to_friendly:
                print(f"  WARNING: Tag name '{tag_name}' maps to multiple friendly names: '{tag_to_friendly[tag_name]}' and '{friendly_name}'")
            else:
                tag_to_friendly[tag_name] = friendly_name

check_file("model_config.json")
check_file("model_confignew.json")
check_file("model_configorig.json")
