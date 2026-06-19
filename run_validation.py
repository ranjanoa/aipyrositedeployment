import os
import sys
import pandas as pd
import numpy as np
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(BASE_DIR, 'modules'))

import config
import process_model
import fingerprint_engine

def main():
    print("Initializing system config paths...")
    target_config_path = os.path.join(BASE_DIR, 'files', 'json', 'model_confignew.json')
    config.MODEL_CONFIG_PATH = target_config_path
    
    csv_dir = os.path.join(BASE_DIR, 'files', 'data')
    os.makedirs(csv_dir, exist_ok=True)
    csv_path = os.path.join(csv_dir, "fingerprint4.csv")
    config.HISTORICAL_DATA_CSV_PATH = csv_path
    
    print(f"Loading model config from {target_config_path}...")
    conf = process_model.load_model_config()
    print(f"Loaded config: model_name = {conf.get('model_name')}")
    
    # Extract columns to mock
    controls = conf.get('control_variables', {})
    indicators = conf.get('indicator_variables', {})
    calculated = conf.get('calculated_variables', {})
    
    # We need the tag_name of variables, or the variable key itself
    all_columns = ["1_timeStamp"]
    
    # Add control tags
    for name, data in controls.items():
        tag = data.get('tag_name', name)
        if tag not in all_columns:
            all_columns.append(tag)
            
    # Add indicator tags
    for name, data in indicators.items():
        tag = data.get('tag_name', name)
        if tag not in all_columns:
            all_columns.append(tag)
            
    # Add calculated tags
    for name, data in calculated.items():
        tag = data.get('tag_name', name)
        if tag not in all_columns:
            all_columns.append(tag)
            
    print(f"Generating dummy CSV with {len(all_columns)} columns...")
    
    # Create 50 rows of dummy data
    num_rows = 50
    dummy_data = {}
    
    # Generate timestamp column
    start_time = pd.Timestamp.now() - pd.Timedelta(hours=10)
    timestamps = [str(start_time + pd.Timedelta(minutes=5*i)) for i in range(num_rows)]
    dummy_data["1_timeStamp"] = timestamps
    
    for col in all_columns:
        if col == "1_timeStamp":
            continue
        # Fill with random values between 10 and 100
        dummy_data[col] = np.random.uniform(10.0, 100.0, size=num_rows)
        
    df_dummy = pd.DataFrame(dummy_data)
    df_dummy.to_csv(csv_path, index=False)
    
    # Clean up parquet file if it exists so robust_read_csv loads the new CSV
    parquet_path = csv_path.replace('.csv', '.parquet')
    if os.path.exists(parquet_path):
        os.remove(parquet_path)
        
    print(f"Dummy dataset written to {csv_path}")
    
    print(f"Loading historical data from {csv_path}...")
    df = fingerprint_engine.robust_read_csv(csv_path)
    print(f"Historical data loaded. Shape: {df.shape}")
    
    # Create a dummy window of 30 rows from the end of the history
    real_df = df.tail(30).copy()
    print(f"Real-time data window shape: {real_df.shape}")
    
    print("\nRunning get_live_fingerprint_action...")
    fp_rec = None
    try:
        fp_rec = fingerprint_engine.get_live_fingerprint_action(real_df)
        print("✅ get_live_fingerprint_action ran successfully!")
        if fp_rec:
            print(f"Match score: {fp_rec.get('match_score')}")
            print(f"Actions count: {len(fp_rec.get('actions', []))}")
    except Exception as e:
        print("❌ get_live_fingerprint_action FAILED!")
        traceback.print_exc()
        
    print("\nRunning finalize_setpoints_for_db...")
    try:
        raw_latest = real_df.iloc[-1].to_dict()
        tag_map = process_model.get_tag_to_name_map()
        mapped_state = {tag_map.get(k, k): v for k, v in raw_latest.items()}
        
        # Call finalize_setpoints_for_db
        if fp_rec:
            setpoints = process_model.finalize_setpoints_for_db(fp_rec, mapped_state, conf)
            print("✅ finalize_setpoints_for_db ran successfully!")
            print(f"Generated setpoints count: {len(setpoints)}")
    except Exception as e:
        print("❌ finalize_setpoints_for_db FAILED!")
        traceback.print_exc()

if __name__ == "__main__":
    main()
