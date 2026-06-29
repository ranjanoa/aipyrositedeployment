# database.py - Updated for Pandas 3.0 & InfluxDB _time mapping
# Triggering a new GitHub Actions build run to verify CimporApp executable compilation
import config
import pandas as pd
import numpy as np
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from urllib3.util.retry import Retry


def get_db_client(timeout=10000): # INCREASED FROM 2000 to 10000
    try:
        # Fail fast if database is offline, but wait in line gracefully if busy
        client = InfluxDBClient(url=config.DB_URL, token=config.DB_TOKEN, org=config.DB_ORG, timeout=timeout, retries=0)
        return client
    except Exception as e:
        print(f"Error connecting to InfluxDB: {e}")
        return None

def get_heavy_analytics_client(timeout_ms=600000): # 10 Minutes
    """
    Dedicated client for massive historical queries (months/years).
    Includes extreme timeouts and automatic network retries.
    """
    try:
        # Native urllib3 Retry logic (Safe across all InfluxDB client versions)
        retries = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        
        client = InfluxDBClient(
            url=config.DB_URL, 
            token=config.DB_TOKEN, 
            org=config.DB_ORG, 
            timeout=timeout_ms, 
            retries=retries
        )
        return client
    except Exception as e:
        print(f"Error connecting to InfluxDB for Heavy Analytics: {e}")
        return None

def _rename_and_format_df(df, tag_map, skip_resample=False):
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

        # Resolve duplicate column names
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
        for friendly_name in tag_map.values():
            if friendly_name not in df.columns:
                df[friendly_name] = np.nan
            else:
                if isinstance(df[friendly_name], pd.DataFrame):
                    df[friendly_name] = df[friendly_name].ffill(axis=1).iloc[:, -1]
                df[friendly_name] = pd.to_numeric(df[friendly_name], errors='coerce')

        # Check timestamp column safety
        if isinstance(df[config.TIMESTAMP_COLUMN], pd.DataFrame):
            df[config.TIMESTAMP_COLUMN] = df[config.TIMESTAMP_COLUMN].ffill(axis=1).iloc[:, -1]

        df[config.TIMESTAMP_COLUMN] = pd.to_datetime(df[config.TIMESTAMP_COLUMN])

        # Set index, sort, and merge exact duplicate timestamps
        df = df.set_index(config.TIMESTAMP_COLUMN).sort_index()
        if df.index.duplicated().any():
            df = df.groupby(level=0).first()

        try:
            import process_model
            df = process_model.apply_signal_filters(df)
        except Exception as e:
            print(f"Error applying signal filters: {e}")

        # 5. Resample and Fill:
        # SKIP RESAMPLING FOR MASSIVE HISTORY to prevent Pandas from exploding 
        # 1-hour downsampled data back into 1-second chunks (OOM Crash Prevention)
        if not skip_resample:
            resampled = df.resample(config.RESAMPLE_INTERVAL)
            numeric_df = resampled.mean(numeric_only=True)
            non_numeric_cols = df.select_dtypes(exclude=[np.number]).columns
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

        df = df.fillna(0.0)

        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if not numeric_cols.empty:
            for col in numeric_cols:
                if isinstance(df[col], pd.DataFrame):
                     combined = df[col].ffill(axis=1).iloc[:, -1]
                     df = df.drop(columns=[col])
                     df[col] = combined
                df[col] = np.where(np.abs(df[col]) < 1e-10, 0.0, df[col])

        df = df.reset_index()
        return df

    except Exception as e:
        import traceback
        print(f"[DIAGNOSTICS] CRITICAL Exception in _rename_and_format_df: {e}")
        traceback.print_exc()
        raise e

    return df

def fetch_massive_history(start_time, end_time, process_tags, tag_map):
    """
    Safely retrieves months/years of data using the heavy client. 
    Applies strict 1-hour downsampling and breaks query into chunks.
    """
    if not process_tags:
        return pd.DataFrame()
        
    client = get_heavy_analytics_client()
    if not client: 
        return pd.DataFrame()

    try:
        chunk_size = pd.Timedelta(days=14)
        current_start = start_time
        all_data_chunks = []
        
        measurements = [
            config.DB_MEASUREMENT,
            config.DB_MEASUREMENT_OPC,
            config.DB_MEASUREMENT_PI
        ]
        measurement_filter = " or ".join(f'r["_measurement"] == "{m}"' for m in measurements if m)

        # Chunk tags to avoid Flux limitations
        tag_chunks = [process_tags[i:i + 40] for i in range(0, len(process_tags), 40)]

        while current_start < end_time:
            current_end = min(current_start + chunk_size, end_time)
            
            start_fmt = current_start.strftime('%Y-%m-%dT%H:%M:%SZ')
            end_fmt = current_end.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            print(f"Fetching analytics chunk: {start_fmt} to {end_fmt}...")
            
            dfs = []
            for chunk in tag_chunks:
                field_filters = ' or '.join([f'r["_field"] == "{str(tag).replace(chr(34), chr(92) + chr(34))}"' for tag in chunk])
                
                # STRICT HOURLY DOWNSAMPLING
                query = f'''
                from(bucket: "{config.DB_BUCKET}")
                  |> range(start: {start_fmt}, stop: {end_fmt})
                  |> filter(fn: (r) => {measurement_filter})
                  |> filter(fn: (r) => {field_filters})
                  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
                '''
                df_chunk = client.query_api().query_data_frame(org=config.DB_ORG, query=query)
                
                if isinstance(df_chunk, list):
                    df_chunk = pd.concat(df_chunk) if df_chunk else pd.DataFrame()
                    
                if df_chunk is not None and not df_chunk.empty:
                    if '_time' in df_chunk.columns and '_field' in df_chunk.columns and '_value' in df_chunk.columns:
                        df_chunk = df_chunk.pivot_table(index='_time', columns='_field', values='_value', aggfunc='first').reset_index()
                        df_chunk.columns.name = None
                    dfs.append(df_chunk)
                    
            if dfs:
                merged_chunk = dfs[0]
                for next_df in dfs[1:]:
                    merged_chunk = pd.merge(merged_chunk, next_df, on='_time', how='outer')
                all_data_chunks.append(merged_chunk)
                
            current_start = current_end

        if not all_data_chunks:
            return pd.DataFrame()
            
        final_df = pd.concat(all_data_chunks, ignore_index=True)
        # Process data but SKIP 1-second resampling so it doesn't crash Pandas
        return _rename_and_format_df(final_df, tag_map, skip_resample=True) if not final_df.empty else pd.DataFrame()
        
    except Exception as e:
        import traceback
        print(f"Error in fetch_massive_history: {e}")
        traceback.print_exc()
        return pd.DataFrame()
    finally:
        client.close()

def get_realtime_data_window(start_time, end_time, process_tags, tag_map):
    if not process_tags:
        return pd.DataFrame()
    client = get_db_client(timeout=20000)
    if not client: return pd.DataFrame()

    try:
        chunk_size = 40
        tag_chunks = [process_tags[i:i + chunk_size] for i in range(0, len(process_tags), chunk_size)]
        
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
            '''
            df_chunk = client.query_api().query_data_frame(org=config.DB_ORG, query=query)
            if isinstance(df_chunk, list):
                df_chunk = pd.concat(df_chunk) if df_chunk else pd.DataFrame()
            if df_chunk is not None and not df_chunk.empty:
                if '_time' in df_chunk.columns and '_field' in df_chunk.columns and '_value' in df_chunk.columns:
                    df_chunk = df_chunk.pivot_table(index='_time', columns='_field', values='_value', aggfunc='first').reset_index()
                    df_chunk.columns.name = None
                dfs.append(df_chunk)
                
        if not dfs:
            return pd.DataFrame()
            
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
                val = float(v)
                if np.isnan(val) or np.isinf(val):
                    out[k] = None
                else:
                    out[k] = val
            except (TypeError, ValueError):
                continue
        return out
    except Exception as e:
        print(f"get_aimnm_results error: {e}")
        return {}
    finally:
        client.close()


def get_live_current_values(field_names, window_minutes=5):
    if not field_names:
        return {}
    client = get_db_client(timeout=5000)
    if not client:
        return {}
    try:
        measurements = [
            config.DB_MEASUREMENT,
            config.DB_MEASUREMENT_OPC,
            config.DB_MEASUREMENT_PI
        ]
        measurement_filter = " or ".join(f'r["_measurement"] == "{m}"' for m in measurements if m)
        
        chunk_size = 40
        field_chunks = [field_names[i:i + chunk_size] for i in range(0, len(field_names), chunk_size)]
        
        dfs = []
        for chunk in field_chunks:
            filter_clause = " or ".join(
                f'r["_field"] == "{str(fn).replace(chr(34), chr(92) + chr(34))}"'
                for fn in chunk
            )
            
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
                    fval = float(val)
                    if np.isnan(fval) or np.isinf(fval):
                        out[field] = None
                    else:
                        out[field] = fval
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
    flat = ''.join(ch for ch in str(param) if ch.isalnum())
    return f"aimnm_{flat.lower()}"


def mirror_aimnm_cv_to_kiln2(cv_pairs):
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
    return True


def get_tag_value_at_time(timestamp, tag_name):
    client = get_db_client(timeout=6000)
    if not client:
        return None
    try:
        import datetime as dt
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(dt.timezone.utc).replace(tzinfo=None)
        ts_str = timestamp.isoformat() + 'Z'
        
        measurements = [
            config.DB_MEASUREMENT,
            config.DB_MEASUREMENT_OPC,
            config.DB_MEASUREMENT_PI,
            getattr(config, 'DB_MEASUREMENT_SETPOINTS', 'kiln2')
        ]
        measurement_filter = " or ".join(f'r["_measurement"] == "{m}"' for m in measurements if m)

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


def get_first_tag_value(tag_name):
    client = get_db_client(timeout=6000)
    if not client:
        return None
    try:
        measurements = [
            config.DB_MEASUREMENT,
            config.DB_MEASUREMENT_OPC,
            config.DB_MEASUREMENT_PI,
            getattr(config, 'DB_MEASUREMENT_SETPOINTS', 'kiln2')
        ]
        measurement_filter = " or ".join(f'r["_measurement"] == "{m}"' for m in measurements if m)

        query = f'''
        from(bucket: "{config.DB_BUCKET}")
          |> range(start: 0)
          |> filter(fn: (r) => {measurement_filter})
          |> filter(fn: (r) => r["_field"] == "{str(tag_name).replace(chr(34), chr(92) + chr(34))}")
          |> first()
        '''
        tables = client.query_api().query(query, org=config.DB_ORG)
        for table in tables:
            for record in table.records:
                val = record.get_value()
                if val is not None:
                    return float(val)
        return None
    except Exception as e:
        print(f"Error getting first tag value for {tag_name}: {e}")
        return None
    finally:
        client.close()


def get_tags_values_at_time(timestamp, tag_names):
    if not tag_names:
        return {}
    client = get_db_client(timeout=15000)
    if not client:
        return {}
    
    results = {}
    remaining_tags = set(tag_names)
    
    try:
        import datetime as dt
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(dt.timezone.utc).replace(tzinfo=None)
        ts_str = timestamp.isoformat() + 'Z'
        
        measurements = [
            config.DB_MEASUREMENT,
            config.DB_MEASUREMENT_OPC,
            config.DB_MEASUREMENT_PI,
            getattr(config, 'DB_MEASUREMENT_SETPOINTS', 'kiln2')
        ]
        measurement_filter = " or ".join(f'r["_measurement"] == "{m}"' for m in measurements if m)

        for days in [7, 30, 0]:
            if not remaining_tags:
                break
            if days == 0:
                range_start = "0"
            else:
                range_start = (timestamp - dt.timedelta(days=days)).isoformat() + 'Z'

            field_filter = " or ".join([f'r["_field"] == "{str(t).replace(chr(34), chr(92) + chr(34))}"' for t in remaining_tags])
            
            query = f'''
            from(bucket: "{config.DB_BUCKET}")
              |> range(start: {range_start}, stop: {ts_str})
              |> filter(fn: (r) => {measurement_filter})
              |> filter(fn: (r) => {field_filter})
              |> last()
            '''
            tables = client.query_api().query(query, org=config.DB_ORG)
            for table in tables:
                for record in table.records:
                    tag = record.get_field()
                    val = record.get_value()
                    if tag in remaining_tags and val is not None:
                        results[tag] = float(val)
                        
            for tag in list(remaining_tags):
                if tag in results:
                    remaining_tags.remove(tag)
                    
        return results
    except Exception as e:
        print(f"Error getting tags values at time {timestamp}: {e}")
        return results
    finally:
        client.close()


def get_first_tags_values(tag_names):
    if not tag_names:
        return {}
    client = get_db_client(timeout=15000)
    if not client:
        return {}
    results = {}
    try:
        measurements = [
            config.DB_MEASUREMENT,
            config.DB_MEASUREMENT_OPC,
            config.DB_MEASUREMENT_PI,
            getattr(config, 'DB_MEASUREMENT_SETPOINTS', 'kiln2')
        ]
        measurement_filter = " or ".join(f'r["_measurement"] == "{m}"' for m in measurements if m)
        
        field_filter = " or ".join([f'r["_field"] == "{str(t).replace(chr(34), chr(92) + chr(34))}"' for t in tag_names])

        query = f'''
        from(bucket: "{config.DB_BUCKET}")
          |> range(start: 0)
          |> filter(fn: (r) => {measurement_filter})
          |> filter(fn: (r) => {field_filter})
          |> first()
        '''
        tables = client.query_api().query(query, org=config.DB_ORG)
        for table in tables:
            for record in table.records:
                tag = record.get_field()
                val = record.get_value()
                if val is not None:
                    results[tag] = float(val)
        return results
    except Exception as e:
        print(f"Error getting first tags values: {e}")
        return results
    finally:
        client.close()
