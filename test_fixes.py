import sys
import os
import pandas as pd
import numpy as np

# Adjust path to import project modules
PROJECT_ROOT = r"c:\Users\z004n00r\Documents\AI sales\AG PROJECTS\AIPYRO_MULTINN-MODEL-master20052026 CODE FINAL (1)\AIPYRO_MULTINN-MODEL-master"
sys.path.append(PROJECT_ROOT)
sys.path.append(os.path.join(PROJECT_ROOT, "modules"))

import config
config.MODEL_CONFIG_PATH = os.path.join(PROJECT_ROOT, "files", "json", "model_config.json")
config.LOG_DIR = os.path.join(PROJECT_ROOT, "logs")

import database
import fingerprint_engine

def test_database_duplicate_resolution():
    print("Running database duplicate column resolution test...")
    
    # Create a DataFrame with duplicate columns
    # We include _time and some duplicate tag names
    df_raw = pd.DataFrame([
        ['2026-06-18 10:00:00', 1.0, 2.0, 'ON'],
        ['2026-06-18 10:00:02', 3.0, 4.0, 'OFF']
    ], columns=['_time', 'coalMainBurner', 'coalMainBurner', 'Coal Mill (ON/OFF)'])
    
    tag_map = {
        'coalMainBurner': 'coalMainBurner',
        'Coal Mill (ON/OFF)': 'Coal Mill (ON/OFF)'
    }
    
    # Run _rename_and_format_df
    df_processed = database._rename_and_format_df(df_raw, tag_map)
    
    print("Processed columns:", list(df_processed.columns))
    print("Processed dataframe:\n", df_processed)
    
    # Asserts
    assert not df_processed.columns.duplicated().any(), "Error: Duplicated columns remain in df!"
    assert 'coalMainBurner' in df_processed.columns, "Error: coalMainBurner is missing!"
    
    # Verify values are correctly preserved (last column values or horizontally filled)
    # Row 0: 2.0 (since horizontal fill of 1.0 and 2.0 -> 2.0)
    # Row 1: 4.0 (since horizontal fill of 3.0 and 4.0 -> 4.0)
    # Wait, the index of df_processed is sorted and resampled. Let's inspect rows.
    # We resampled to RESAMPLE_INTERVAL ('1s'), so there are 3 rows (10:00:00, 10:00:01, 10:00:02)
    # Row at 10:00:00 should have coalMainBurner value of 2.0
    val_first = df_processed.loc[df_processed[config.TIMESTAMP_COLUMN] == '2026-06-18 10:00:00', 'coalMainBurner'].values[0]
    val_last = df_processed.loc[df_processed[config.TIMESTAMP_COLUMN] == '2026-06-18 10:00:02', 'coalMainBurner'].values[0]
    
    assert val_first == 2.0, f"Expected 2.0, got {val_first}"
    assert val_last == 4.0, f"Expected 4.0, got {val_last}"
    
    print("Database duplicate column resolution test: PASSED")


def test_fingerprint_strategy_normalization():
    print("Running fingerprint strategy normalization test...")
    
    # Create mock inputs
    hist_df = pd.DataFrame([
        ['2026-06-18 09:00:00', 1000.0, 1400.0],
        ['2026-06-18 09:01:00', 1100.0, 1450.0]
    ], columns=[config.TIMESTAMP_COLUMN, 'coalMainBurner', 'sinteringZoneTemp'])
    hist_df[config.TIMESTAMP_COLUMN] = pd.to_datetime(hist_df[config.TIMESTAMP_COLUMN])
    
    current_real_df = hist_df.copy()
    current_state = current_real_df.iloc[-1]
    
    # Strategy containing a string value instead of a dictionary
    strategy = {
        'sinteringZoneTemp': 'Higher',
        'coalMainBurner': {
            'priority': 2,
            'min': 900.0,
            'max': 1200.0
        }
    }
    
    # Execute find_best_fingerprint_advanced
    best_rows, is_fallback = fingerprint_engine.find_best_fingerprint_advanced(
        current_real_df, hist_df, strategy, current_state, weights={}
    )
    
    print(f"Executed find_best_fingerprint_advanced successfully. Result size: {len(best_rows)}")
    
    # Verify fallback is not crashed
    print("Fingerprint strategy normalization test: PASSED")


def main():
    try:
        test_database_duplicate_resolution()
        print("-" * 50)
        test_fingerprint_strategy_normalization()
        print("-" * 50)
        print("ALL TESTS PASSED!")
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
