# database.py - Updated for Pandas 3.0 & InfluxDB _time mapping
# Triggering a new GitHub Actions build run to verify CimporApp executable compilation
import config
import pandas as pd
import numpy as np
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS


def get_db_client(timeout=2000):
    try:
        # Fail fast if database is offline (default 2s timeout, 0 retries)
        client = InfluxDBClient(url=config.DB_URL, token=config.DB_TOKEN, org=config.DB_ORG, timeout=timeout, retries=0)
        return client
    except Exception as e:
        print(f"Error connecting to InfluxDB: {e}")
        return None


def _rename_and_format_df(df, tag_map):
    try:
        if df.empty: return df

        # 1. Drop internal Influx columns
        cols_to_drop = ['result', 'table', '_start', '_stop', '_measurement']
        df = df.drop(columns=[c for c in cols_to_drop if c in df.columns])

        # 2. RENAME _time to config.TIMESTAMP_COLUMN before any operations
        if '_time' in df.columns:
            df = df.rename(columns={'_time': config.TIMESTAMP_COLUMN})

        # 3. Pivot if necessary
        if '_field' in df.columns and '_value' in df.columns:
            df = df.pivot_table(index=config.TIMESTAMP_COLUMN, columns='_field', values='_value').reset_index()

        # 4. Apply User Tag Mapping
        df = df.rename(columns=tag_map)

        # Resolve duplicate column names (e.g. if a tag exists in multiple source measurements or is already named as friendly)
        if df.columns.duplicated().any():
            cols_to_resolve = df.columns[df.columns.duplicated()].unique()
            print(f"[DIAGNOSTICS] Duplicate columns detected in raw data: {list(cols_to_resolve)}")
            for col in cols_to_resolve:
                col_df = df[col]
                if isinstance(col_df, pd.DataFrame):
                    print(f"[DIAGNOSTICS] Resolving duplicated column '{col}' with shape {col_df.shape}")
                    combined = col_df.ffill(axis=1).iloc[:, -1]
                    df = df.drop(columns=[col])
                    df[col] = combined

        # Ensure all expected friendly name columns from tag_map are present
        # and cast them to numeric type so missing/bad values are coerced to float NaNs
        for friendly_name in tag_map.values():
            if friendly_name not in df.columns:
                df[friendly_name] = np.nan
            else:
                # Coerce any string placeholders (like "Bad" or "Comm Error") to NaN
                if isinstance(df[friendly_name], pd.DataFrame):
                    print(f"[DIAGNOSTICS] WARNING: '{friendly_name}' is still a DataFrame with columns: {list(df[friendly_name].columns)}")
                    # Force combine
                    df[friendly_name] = df[friendly_name].ffill(axis=1).iloc[:, -1]
                df[friendly_name] = pd.to_numeric(df[friendly_name], errors='coerce')

        # Check timestamp column safety
        if isinstance(df[config.TIMESTAMP_COLUMN], pd.DataFrame):
            print(f"[DIAGNOSTICS] WARNING: timestamp column '{config.TIMESTAMP_COLUMN}' is a DataFrame with columns: {list(df[config.TIMESTAMP_COLUMN].columns)}")
            df[config.TIMESTAMP_COLUMN] = df[config.TIMESTAMP_COLUMN].ffill(axis=1).iloc[:, -1]

        df[config.TIMESTAMP_COLUMN] = pd.to_datetime(df[config.TIMESTAMP_COLUMN])

        # Set index, sort, and merge exact duplicate timestamps from multiple tables before filtering
        df = df.set_index(config.TIMESTAMP_COLUMN).sort_index()
        if df.index.duplicated().any():
            df = df.groupby(level=0).first()

        # Apply configured signal filtering rules on RAW data BEFORE oversampling
        try:
            import process_model
            df = process_model.apply_signal_filters(df)
        except Exception as e:
            print(f"Error applying signal filters: {e}")

        # 5. Resample and Fill:
        # Use mean() for numeric columns to preserve high-frequency signal fidelity without 'flattening',
        # and use first() for categorical/string columns (like 'Coal Mill (ON/OFF)') to prevent dropping them.
        resampled = df.resample(config.RESAMPLE_INTERVAL)
        numeric_df = resampled.mean(numeric_only=True)
        non_numeric_cols = df.select_dtypes(exclude=[np.number]).columns
        
        # Filter out columns that are already present in numeric_df to prevent duplicates (e.g. boolean columns)
        non_numeric_cols = [c for c in non_numeric_cols if c not in numeric_df.columns]
        
        if non_numeric_cols:
            non_numeric_df = resampled.first()[non_numeric_cols]
            df = pd.concat([numeric_df, non_numeric_df], axis=1)
        else:
            df = numeric_df

        if config.FILL_METHOD == 'bfill':
            df = df.bfill().ffill()
        else:
            df = df.ffill().bfill()

        # Fill any remaining NaNs (e.g. from completely empty columns or start/end edges) with 0.0
        df = df.fillna(0.0)

        # Sanitize subnormal floats from disconnected PLCs (e.g., 1e-39) to exactly 0.0
        # This prevents the UI from rendering weird scientific notation characters (like â‚¬<39â‚¬<-)
        # and prevents the AI from calculating infinite uncertainties.
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if not numeric_cols.empty:
            for col in numeric_cols:
                if isinstance(df[col], pd.DataFrame):
                     print(f"[DIAGNOSTICS] WARNING: numeric col '{col}' is a DataFrame")
                     combined = df[col].ffill(axis=1).iloc[:, -1]
                     df = df.drop(columns=[col])
                     df[col] = combined
                df[col] = np.where(np.abs(df[col]) < 1e-10, 0.0, df[col])

        df = df.reset_index()
        return df

    except Exception as e:
        import traceback
        print(f"[DIAGNOSTICS] CRITICAL Exception in _rename_and_format_df: {e}")
        print(f"[DIAGNOSTICS] df shape: {df.shape if 'df' in locals() else 'unknown'}")
        if 'df' in locals() and hasattr(df, 'columns'):
            print(f"[DIAGNOSTICS] df columns: {list(df.columns)}")
            print(f"[DIAGNOSTICS] Duplicate columns in df: {list(df.columns[df.columns.duplicated()].unique())}")
        traceback.print_exc()
        raise e

    return df


def get_realtime_data_window(start_time, end_time, process_tags, tag_map):
    if not process_tags:
        return pd.DataFrame()
    # Use a longer timeout (10s) for window queries since pivoting and loading many tags takes time
    client = get_db_client(timeout=10000)
    if not client: return pd.DataFrame()

    try:
        # Split process_tags into chunks of 40 to avoid Flux nesting limits and ensure pushdown
        chunk_size = 40
        tag_chunks = [process_tags[i:i + chunk_size] for i in range(0, len(process_tags), chunk_size)]
        
        # Only query primary measurements for fast alignment and to avoid pivot timeouts
        measurements = [
            config.DB_MEASUREMENT,
            config.DB_MEASUREMENT_OPC,
            config.DB_MEASUREMENT_PI
        ]
        measurement_filter = " or ".join(f'r["_measurement"] == "{m}"' for m in measurements if m)

        dfs = []
        for chunk in tag_chunks:
            field_filters = ' or '.join([f'r["_field"] == "{str(tag).replace(chr(34), chr(92) + chr(34))}"' for tag in chunk])
            query = f'''
            from(bucket: "{config.DB_BUCKET}")
              |> range(start: {start_time.isoformat()}Z, stop: {end_time.isoformat()}Z)
              |> filter(fn: (r) => {measurement_filter})
              |> filter(fn: (r) => {field_filters})
              |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
            '''
            df_chunk = client.query_api().query_data_frame(org=config.DB_ORG, query=query)
            if isinstance(df_chunk, list):
                df_chunk = pd.concat(df_chunk) if df_chunk else pd.DataFrame()
            if df_chunk is not None and not df_chunk.empty:
                # Drop internal Influx columns except '_time' before merging to avoid duplicate columns
                cols_to_drop = [c for c in ['result', 'table', '_start', '_stop', '_measurement'] if c in df_chunk.columns]
                df_chunk = df_chunk.drop(columns=cols_to_drop)
                dfs.append(df_chunk)
                
        if not dfs:
            return pd.DataFrame()
            
        # Merge all chunks on '_time'
        df = dfs[0]
        for next_df in dfs[1:]:
            df = pd.merge(df, next_df, on='_time', how='outer')
            
        return _rename_and_format_df(df, tag_map) if not df.empty else pd.DataFrame()
    except Exception as e:
        import traceback
        print(f"Error in get_realtime_data_window: {e}")
        traceback.print_exc()
        return pd.DataFrame()
    finally:
        client.close()




def write_setpoints(timestamp, setpoints_dict, setpoint_tag_map, scale_factors):
    client = get_db_client()
    if not client: return False
    write_api = client.write_api(write_options=SYNCHRONOUS)
    try:
        point = Point(config.DB_MEASUREMENT_SETPOINTS).time(timestamp)
        for name, value in setpoints_dict.items():
            tag = setpoint_tag_map.get(name)
            if tag:
                point.field(tag, float(value * scale_factors.get(name, 1)))
        write_api.write(bucket=config.DB_BUCKET, org=config.DB_ORG, record=point)
        return True
    except Exception as e:
        print(f"Error writing setpoints: {e}")
        return False
    finally:
        write_api.close()
        client.close()


def get_aimnm_results(window_minutes=2, measurement_override=None):
    """
    Reads the latest record from `cimpor_data_result` (DB_MEASUREMENT_AI_MNM_RESULT).
    Returns a flat dict {field_name: float_value, _time: ISO} — frontend pairs
    `<param>_curr` with `<param>_sp` to render Curr/SP columns.
    """
    client = get_db_client()
    if not client:
        return {}
    try:
        measurement = measurement_override or config.DB_MEASUREMENT_AI_MNM_RESULT
        query = f'''
        from(bucket: "{config.DB_BUCKET}")
          |> range(start: -{int(window_minutes)}m)
          |> filter(fn: (r) => r["_measurement"] == "{measurement}")
          |> last()
          |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
        '''
        df = client.query_api().query_data_frame(org=config.DB_ORG, query=query)
        if isinstance(df, list):
            df = pd.concat(df) if df else pd.DataFrame()
        if df is None or df.empty:
            return {}

        cols_to_drop = [c for c in ['result', 'table', '_start', '_stop', '_measurement'] if c in df.columns]
        df = df.drop(columns=cols_to_drop)
        row = df.iloc[-1].to_dict()
        out = {}
        for k, v in row.items():
            if k == '_time':
                out['_time'] = str(v)
                continue
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                continue
        return out
    except Exception as e:
        print(f"get_aimnm_results error: {e}")
        return {}
    finally:
        client.close()


def get_live_current_values(field_names, window_minutes=5):
    """
    Reads the latest values for the given field_names by scanning multiple
    measurements: kiln1, kiln1_opc, kiln1_pi, and kiln2.
    
    Returns: { field_name: float_value } - returns the most recent point found
    across all sources.
    """
    if not field_names:
        return {}
    # Use 5s timeout for fetching current values
    client = get_db_client(timeout=5000)
    if not client:
        return {}
    try:
        # Only query primary measurements for fast alignment and to avoid timeouts
        measurements = [
            config.DB_MEASUREMENT,
            config.DB_MEASUREMENT_OPC,
            config.DB_MEASUREMENT_PI
        ]
        measurement_filter = " or ".join(f'r["_measurement"] == "{m}"' for m in measurements if m)
        
        # Split field_names into chunks of 40 to avoid Flux nesting limits and ensure pushdown
        chunk_size = 40
        field_chunks = [field_names[i:i + chunk_size] for i in range(0, len(field_names), chunk_size)]
        
        dfs = []
        for chunk in field_chunks:
            filter_clause = " or ".join(
                f'r["_field"] == "{str(fn).replace(chr(34), chr(92) + chr(34))}"'
                for fn in chunk
            )
            
            # We do not use pivot in Flux here because fields updating at different
            # timestamps will produce multiple rows, causing df.iloc[-1] to discard earlier ones.
            query = f'''
            from(bucket: "{config.DB_BUCKET}")
              |> range(start: -{int(window_minutes)}m)
              |> filter(fn: (r) => {measurement_filter})
              |> filter(fn: (r) => {filter_clause})
              |> last()
              |> group(columns: ["_field"])
              |> last()
            '''
            df_chunk = client.query_api().query_data_frame(org=config.DB_ORG, query=query)
            if isinstance(df_chunk, list):
                df_chunk = pd.concat(df_chunk) if df_chunk else pd.DataFrame()
            if df_chunk is not None and not df_chunk.empty:
                dfs.append(df_chunk)
                
        if not dfs:
            return {}
            
        df = pd.concat(dfs)
        if df.empty:
            return {}
            
        out = {}
        for _, r in df.iterrows():
            field = r.get('_field')
            val = r.get('_value')
            if field and val is not None:
                try:
                    out[field] = float(val)
                except (TypeError, ValueError):
                    continue
                    
        if '_time' in df.columns:
            out['_time'] = str(df['_time'].max())
            
        return out
    except Exception as e:
        print(f"get_live_current_values error: {e}")
        return {}
    finally:
        client.close()


def _aimnm_field_name(param):
    """
    Build the kiln2 field name for an AI_MNM CV SP.
    Flatten to `aimnm_<param>` with all underscores/spaces stripped, e.g.:
        kiln_feed             -> aimnm_kilnfeed
        main_firing_petcoke   -> aimnm_mainfiringpetcoke
    """
    flat = ''.join(ch for ch in str(param) if ch.isalnum())
    return f"aimnm_{flat.lower()}"


def mirror_aimnm_cv_to_kiln2(cv_pairs):
    """
    Mirrors AI_MNM CV setpoints into kiln2 (DB_MEASUREMENT_SETPOINTS) on every poll.
    ONLY the SP value is persisted to kiln2. Indicator values are NOT persisted.

    `cv_pairs` shape: { "<param>": {"curr": float|None, "sp": float|None} }
    """
    from datetime import datetime, timezone
    if not cv_pairs:
        return False
    client = get_db_client()
    if not client:
        return False
    write_api = client.write_api(write_options=SYNCHRONOUS)
    try:
        point = Point(config.DB_MEASUREMENT_SETPOINTS).time(datetime.now(timezone.utc))
        wrote_any = False
        for param, vals in cv_pairs.items():
            if not isinstance(vals, dict):
                continue
            v = vals.get('sp')
            if v is None:
                continue
            try:
                point.field(_aimnm_field_name(param), float(v))
                wrote_any = True
            except (TypeError, ValueError):
                continue
        if not wrote_any:
            return True
        write_api.write(bucket=config.DB_BUCKET, org=config.DB_ORG, record=point)
        return True
    except Exception as e:
        print(f"mirror_aimnm_cv_to_kiln2 error: {e}")
        return False
    finally:
        write_api.close()
        client.close()


def write_aimnm_setpoints(values_dict):
    """
    DEPRECATED — retained as a no-op for backward compatibility.
    AI_MNM setpoints are written via mirror_aimnm_cv_to_kiln2.
    Configuration lives in model_config.json only.
    """
    return True


def get_tag_value_at_time(timestamp, tag_name):
    # Use 6s timeout for historic value retrieval
    client = get_db_client(timeout=6000)
    if not client:
        return None
    try:
        import datetime as dt
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(dt.timezone.utc).replace(tzinfo=None)
        ts_str = timestamp.isoformat() + 'Z'
        
        # Include kiln2 (DB_MEASUREMENT_SETPOINTS) to fetch AI status tags like AI_SYSTEM_TRUST_RH
        measurements = [
            config.DB_MEASUREMENT,
            config.DB_MEASUREMENT_OPC,
            config.DB_MEASUREMENT_PI,
            getattr(config, 'DB_MEASUREMENT_SETPOINTS', 'kiln2')
        ]
        measurement_filter = " or ".join(f'r["_measurement"] == "{m}"' for m in measurements if m)

        # Tiered query: search the last 7 days first (fast), fall back to 30 days, then to all history (start: 0)
        # to avoid scanning the entire database from 1970 when not needed.
        for days in [7, 30, 0]:
            if days == 0:
                range_start = "0"
            else:
                range_start = (timestamp - dt.timedelta(days=days)).isoformat() + 'Z'

            query = f'''
            from(bucket: "{config.DB_BUCKET}")
              |> range(start: {range_start}, stop: {ts_str})
              |> filter(fn: (r) => {measurement_filter})
              |> filter(fn: (r) => r["_field"] == "{str(tag_name).replace(chr(34), chr(92) + chr(34))}")
              |> last()
            '''
            tables = client.query_api().query(query, org=config.DB_ORG)
            for table in tables:
                for record in table.records:
                    val = record.get_value()
                    if val is not None:
                        return float(val)
        return None
    except Exception as e:
        print(f"Error getting tag value at time {timestamp} for {tag_name}: {e}")
        return None
    finally:
        client.close()