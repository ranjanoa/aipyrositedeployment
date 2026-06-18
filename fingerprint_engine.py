import pandas as pd
import numpy as np
import logging
from logging.handlers import RotatingFileHandler
import os
import json
from datetime import datetime, timedelta
import process_model
from process_model import apply_industrial_nudge

# ADVANCED MATH IMPORTS
try:
    from scipy.spatial.distance import mahalanobis
    from scipy.linalg import pinv
except ImportError:
    mahalanobis = None
    pinv = None

# LOCAL IMPORTS
try:
    import config
except ImportError:
    config = None

# ==============================================================================
# 0. ENHANCED LOGGING SETUP
# ==============================================================================
def setup_logging():
    """Sets up a specific logger for the Fingerprint Engine."""
    _logger = logging.getLogger("FingerprintEngine")
    _logger.setLevel(logging.INFO)

    if not _logger.handlers:
        if not os.path.exists("logs"):
            os.makedirs("logs", exist_ok=True)
        fh = RotatingFileHandler("logs/fingerprint_debug.log", maxBytes=5 * 1024 * 1024, backupCount=5,
                                 encoding='utf-8')
        fh.setLevel(logging.INFO)
        import sys
        if hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(funcName)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        _logger.addHandler(fh)
        _logger.addHandler(ch)
    return _logger


engine_logger = setup_logging()

# GLOBAL PROCESS MODEL INIT
process_model = None
try:
    import process_model
    HAS_PROCESS_MODEL = True
except ImportError:
    HAS_PROCESS_MODEL = False

# ==============================================================================
# 1. GLOBAL CACHE & CONFIG
# ==============================================================================
CACHE_DF = None
CACHE_COV = None
CACHE_MTIME = 0.0

STATE_FILE = os.path.join(getattr(config, 'JSON_DIR', 'files/json'), "engine_state.json")

def get_config_path():
    if config:
        default_path = os.path.join(getattr(config, 'DATA_DIR', 'files/data'), "fingerprint4.csv")
        return getattr(config, 'HISTORICAL_DATA_CSV_PATH', default_path)
    return "files/data/fingerprint4.csv"

def get_timestamp_col():
    if config:
        return getattr(config, 'TIMESTAMP_COLUMN', "1_timestamp")
    return "1_timestamp"

def load_engine_state():
    if not os.path.exists(STATE_FILE): return {}
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_engine_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        engine_logger.error(f"State Save Error: {e}")

def get_model_config_safe():
    if HAS_PROCESS_MODEL and process_model:
        try:
            return process_model.load_model_config()
        except Exception:
            pass
    return {}

def get_active_strategy(conf=None):
    if conf is None:
        conf = get_model_config_safe()
    strategy_name = conf.get('active_strategy', None)
    strategies = conf.get('strategies', {})
    if strategy_name and strategy_name in strategies:
        strat = strategies[strategy_name]
        engine_logger.info(f"[STRATEGY] Active: {strategy_name} - {strat.get('description', '')}")
        return strategy_name, strat
    return 'DEFAULT', {}

# ==============================================================================
# 2. LOW-LEVEL HELPERS
# ==============================================================================
def ensure_calculated_columns(df):
    if df is None or df.empty: return df
    conf = get_model_config_safe()
    calc_cfg = conf.get('calculated_variables', {})
    if not calc_cfg: return df
    missing = [cfg.get('friendly_name') for k, cfg in calc_cfg.items()
               if cfg.get('friendly_name') not in df.columns and cfg.get('friendly_name')]

    if missing:
        engine_logger.info(f"[INIT] Missing calculated columns in history: {missing}. Materializing...")
        controls_cfg = conf.get('control_variables', {})
        indicators_cfg = conf.get('indicator_variables', {})
        enriched_df = process_model.materialize_df(df, controls_cfg, indicators_cfg, calc_cfg)
        csv_path = get_config_path()
        parquet_path = csv_path.replace('.csv', '.parquet')
        try:
            enriched_df.to_csv(csv_path, index=False)
            engine_logger.info(f"[OK] CSV enriched and saved: {csv_path}")
            enriched_df.to_parquet(parquet_path, engine='pyarrow')
            engine_logger.info(f"[OK] Parquet cache updated: {parquet_path}")
        except Exception as e:
            engine_logger.error(f"[ERR] Failed to save enriched dataset: {e}")
        return enriched_df
    return df

def robust_read_csv(file_path):
    parquet_path = file_path.replace('.csv', '.parquet')
    try:
        if os.path.exists(parquet_path):
            csv_mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else 0
            parquet_mtime = os.path.getmtime(parquet_path)
            if csv_mtime <= parquet_mtime:
                df = pd.read_parquet(parquet_path)
                engine_logger.info(f"Loaded Parquet file instantly with {len(df)} rows.")
                conf = get_model_config_safe()
                df = map_csv_headers(df, conf.get('control_variables', {}), conf.get('indicator_variables', {}))
                enriched_df = ensure_calculated_columns(df)
                return enriched_df

        if not os.path.exists(file_path):
            engine_logger.warning(f"Data file not found at: {file_path} or {parquet_path}")
            return pd.DataFrame()

        engine_logger.info("Reading raw CSV. This will take a moment before optimizing...")
        df = pd.read_csv(file_path)
        df.columns = [str(c).strip() for c in df.columns]
        conf = get_model_config_safe()
        df = map_csv_headers(df, conf.get('control_variables', {}), conf.get('indicator_variables', {}))
        df = ensure_calculated_columns(df)
        try:
            df.to_parquet(parquet_path, engine='pyarrow')
            engine_logger.info(f"Optimized history and saved Parquet cache to {parquet_path}")
        except Exception as pe:
            engine_logger.warning(f"Could not save Parquet file: {pe} (Install pyarrow to enable caching).")
        return df
    except Exception as e:
        engine_logger.error(f"Data Read Error: {e}")
        return pd.DataFrame()

def map_csv_headers(hist_df, controls_cfg, indicators_cfg):
    if hist_df.empty: return hist_df
    df = hist_df.copy()
    rename_map = {}
    all_vars = {}
    if controls_cfg: all_vars.update(controls_cfg)
    if indicators_cfg: all_vars.update(indicators_cfg)

    for friendly, cfg in all_vars.items():
        opc = cfg.get('tag_name')
        if opc and opc in df.columns:
            rename_map[opc] = friendly

    if rename_map:
        df = df.rename(columns=rename_map)
    return df

def map_tags_to_friendly_names(current_state_map, controls_cfg, indicators_cfg, calc_vars_cfg=None):
    mapped_state = current_state_map.copy()
    all_vars = {}
    if controls_cfg: all_vars.update(controls_cfg)
    if indicators_cfg: all_vars.update(indicators_cfg)
    opc_lookup = {}
    for friendly_name, cfg in all_vars.items():
        if 'tag_name' in cfg: opc_lookup[cfg['tag_name']] = friendly_name
    for key, value in current_state_map.items():
        if key in opc_lookup: mapped_state[opc_lookup[key]] = value

    if calc_vars_cfg:
        mapped_state.update(process_model.evaluate_formulas(mapped_state, controls_cfg, indicators_cfg, calc_vars_cfg))
    return mapped_state

def align_magnitude(target_val, current_val):
    try:
        if target_val == 0 or current_val == 0: return target_val
        ratio = abs(current_val / target_val)
        if 800 < ratio < 1200: return target_val * 1000.0
        if 0.0008 < ratio < 0.0012: return target_val / 1000.0
        if 80 < ratio < 120: return target_val * 100.0
        return target_val
    except Exception:
        return target_val

def pre_calculate_slopes(df, controls_cfg):
    df_slopes = df.copy()
    if controls_cfg:
        for tag_key in controls_cfg.keys():
            if tag_key in df.columns:
                df_slopes[f"{tag_key}_slope"] = df[tag_key].diff().fillna(0)
    return df_slopes

def get_heat_input(fuel_tag, flow_value, current_state, conf):
    pairing = conf.get('fuel_calorific_pairing', {})
    cv_tag = pairing.get(fuel_tag)
    if cv_tag:
        cv_value = float(current_state.get(cv_tag, 0))
        if cv_value > 0:
            return flow_value * cv_value
    return flow_value

def check_future_stability(historical_df, candidate_ts):
    ts_col = get_timestamp_col()
    if ts_col not in historical_df.columns: return False
    try:
        conf = get_model_config_safe()
        strategy_name, strat = get_active_strategy(conf)
        lookahead = conf.get('logic_tags', {}).get('stability_lookahead', 30)

        stability_tag_list = strat.get('stability_tags', [])
        if not stability_tag_list:
            stability_tag_list = conf.get('logic_tags', {}).get('stability_tags', [])

        if not stability_tag_list:
            legacy_tag = conf.get('logic_tags', {}).get('primary_stability_tag')
            if legacy_tag:
                threshold_pct = conf.get('logic_tags', {}).get('stability_threshold_pct', 0.05)
                stability_tag_list = [{'tag': legacy_tag, 'threshold_pct': threshold_pct}]

        if not stability_tag_list: return True

        match_idx = historical_df.index[historical_df[ts_col] == candidate_ts].tolist()
        if not match_idx: return False
        idx = match_idx[0]
        if idx + 1 + lookahead >= len(historical_df): return False

        future_slice = historical_df.iloc[idx + 1: idx + 1 + lookahead]
        if future_slice.empty: return False

        for entry in stability_tag_list:
            tag_name = entry.get('tag') if isinstance(entry, dict) else entry
            threshold_pct = entry.get('threshold_pct', 0.05) if isinstance(entry, dict) else 0.05

            if tag_name in future_slice.columns:
                std_dev = future_slice[tag_name].std()
                mean_val = future_slice[tag_name].mean()
                if mean_val != 0 and (std_dev / abs(mean_val)) > threshold_pct:
                    return False
        return True
    except Exception:
        return True

def get_cached_dataframe(controls_cfg, indicators_cfg):
    global CACHE_DF, CACHE_MTIME, CACHE_COV
    csv_path = get_config_path()
    try:
        if not os.path.exists(csv_path): return pd.DataFrame()
        current_mtime = float(os.path.getmtime(csv_path))
        if CACHE_DF is not None and CACHE_MTIME == current_mtime: return CACHE_DF

        engine_logger.info("Reloading dataframe from disk (cache miss or update)...")
        hist_df = robust_read_csv(csv_path)
        hist_df = map_csv_headers(hist_df, controls_cfg, indicators_cfg)
        ts_col = get_timestamp_col()
        if ts_col in hist_df.columns:
            hist_df[ts_col] = pd.to_datetime(hist_df[ts_col], format="%Y-%m-%d %H:%M:%S", errors='coerce')
        CACHE_DF = hist_df
        CACHE_MTIME = current_mtime
        CACHE_COV = None
        return hist_df
    except Exception as e:
        engine_logger.error(f"Cache Error: {e}")
        return pd.DataFrame()

# ==============================================================================
# 3. DYNAMIC WEIGHT BIAS (OPERATIONAL MATRIX)
# ==============================================================================
def calculate_dynamic_weights(current_state, base_weights):
    if not HAS_PROCESS_MODEL or not process_model: return base_weights
    new_weights = base_weights.copy()
    try:
        full_conf = process_model.load_model_config()
        matrix = full_conf.get('operational_matrix_settings', {})
        if not matrix.get('enabled', False): return base_weights

        tags = matrix.get('tags', {})
        lim = matrix.get('limits', {})
        bias = matrix.get('matrix_bias', {})
        actuators = matrix.get('actuators', {})
        rules_enabled = matrix.get('matrix_rules', {})
        hot_kiln_rule = matrix.get('hot_kiln_rule', {})

        bzt = float(current_state.get(tags.get('bzt'), 0))
        o2 = float(current_state.get(tags.get('o2_inlet'), 0))

        fuel_tag = actuators.get('fuel_main')
        feed_tag = actuators.get('feed')
        fan_tag = actuators.get('id_fan')

        if rules_enabled.get('hot_kiln_enabled', True):
            if bzt > lim.get('bzt_hot', 9999):
                priority = hot_kiln_rule.get('priority_action', 'fuel_first')
                fuel_w = hot_kiln_rule.get('fuel_weight', bias.get('hot_kiln_fuel_weight', -15.0))
                feed_w = hot_kiln_rule.get('feed_weight', bias.get('hot_kiln_feed_weight', 10.0))
                fuel_first_only = hot_kiln_rule.get('apply_feed_only_if_fuel_already_reduced', True)

                if fuel_tag: new_weights[fuel_tag] = fuel_w
                if feed_tag and priority == 'fuel_first' and not fuel_first_only:
                    new_weights[feed_tag] = feed_w
                elif feed_tag and priority != 'fuel_first':
                    new_weights[feed_tag] = feed_w

        if rules_enabled.get('cold_kiln_enabled', True):
            if lim.get('bzt_cold', 0) > bzt > 500:
                if fuel_tag: new_weights[fuel_tag] = bias.get('cold_kiln_fuel_weight', 15.0)

        if rules_enabled.get('low_o2_id_fan_enabled', False):
            if o2 < lim.get('o2_min', 9999) and o2 > 0.1:
                if fan_tag: new_weights[fan_tag] = bias.get('low_o2_fan_weight', 0)

        strategy_name, strat = get_active_strategy(full_conf)
        opt_cfg = strat.get('optimisation_target', {})
        if opt_cfg:
            primary = opt_cfg.get('primary_tag')
            if primary:
                new_weights[primary] = opt_cfg.get('primary_weight', 5.0)
            for ct in opt_cfg.get('co_targets', []):
                if not isinstance(ct, dict): continue
                ctag = ct.get('tag')
                if not ctag or ctag.startswith('_'): continue
                new_weights[ctag] = ct.get('weight', 0.0)
    except Exception as e:
        engine_logger.error(f"Weight Bias Error: {e}")
        return base_weights
    return new_weights

# ==============================================================================
# 4. CORE SCORING ENGINE & MATCH CALCULATION
# ==============================================================================
def calculate_match_percentage(current_state, row, controls_cfg, indicators_cfg=None):
    if not isinstance(current_state, dict) or not controls_cfg: return 0.0
    conf = get_model_config_safe()
    fuel_pairing = conf.get('fuel_calorific_pairing', {})

    eval_vars = {}
    eval_vars.update(controls_cfg)
    if indicators_cfg: eval_vars.update(indicators_cfg)

    scoring_cfg = conf.get('scoring_settings', {})
    raw_multipliers = scoring_cfg.get('priority_multipliers', {})
    prio_multipliers = {int(k): float(v) for k, v in raw_multipliers.items()} if raw_multipliers else {1: 8.0, 2: 4.0, 3: 1.0, 4: 0.5, 5: 0.2}

    weighted_dist_sum, total_weight = 0.0, 0.0
    tag_contributions, skipped_tags = [], []

    for tag, props in eval_vars.items():
        if tag in row:
            if tag not in current_state:
                skipped_tags.append(tag)
                continue
            curr_val = float(current_state.get(tag, 0))
            hist_val = float(row.get(tag, 0))

            if np.isnan(curr_val): curr_val = 0.0
            if np.isnan(hist_val): hist_val = 0.0

            hist_val = align_magnitude(hist_val, curr_val)

            if tag in fuel_pairing:
                curr_val = get_heat_input(tag, curr_val, current_state, conf)
                hist_cv_tag = fuel_pairing[tag]
                hist_cv = float(row.get(hist_cv_tag, 0))
                if hist_cv > 0: hist_val = hist_val * hist_cv

            prio = int(props.get('priority', 3))
            w = prio_multipliers.get(prio, 1.0)

            if abs(curr_val) < 1e-6 and abs(hist_val) < 1e-6:
                d_sq = 0.0
            elif abs(curr_val) > 1e-6:
                raw_delta = abs(curr_val - hist_val) / abs(curr_val)
                d_sq = min(raw_delta, 2.0) ** 2
            else:
                v_min = float(props.get('default_min', props.get('min', 0)))
                v_max = float(props.get('default_max', props.get('max', 100)))
                v_range = abs(v_max - v_min)
                if v_range > 1e-6:
                    raw_delta = abs(curr_val - hist_val) / v_range
                    d_sq = min(raw_delta, 2.0) ** 2
                else:
                    d_sq = 1.0

            weighted_penalty = d_sq * w
            weighted_dist_sum += weighted_penalty
            total_weight += w
            tag_contributions.append((tag, curr_val, hist_val, prio, weighted_penalty))

    if total_weight == 0 or np.isnan(weighted_dist_sum): return 0.0
    avg_weighted_dist_sq = weighted_dist_sum / total_weight
    if np.isnan(avg_weighted_dist_sq): return 0.0

    similarity = np.exp(-0.5 * avg_weighted_dist_sq) * 100.0
    final_score = max(0, min(100, round(float(similarity), 1)))
    return final_score

def _calculate_core_score(row, current_state, controls_cfg, weights=None, active_constraints=None, inv_cov=None,
                          live_slopes=None, penalty_weight=1000.0, is_advanced=False, active_tags_ordered=None,
                          past_row=None):
    score = 0.0
    now = pd.Timestamp.now()
    ts_col = get_timestamp_col()
    conf = get_model_config_safe()
    scoring_cfg = conf.get('scoring_settings', {})
    aggression = float(scoring_cfg.get('search_aggression', 1.0))
    fuel_pairing = conf.get('fuel_calorific_pairing', {})

    if weights:
        for tag, w in weights.items():
            if tag in fuel_pairing:
                cv_tag = fuel_pairing[tag]
                hist_cv = float(row.get(cv_tag, 0))
                hist_flow = float(row.get(tag, 0))
                tag_val = hist_flow * hist_cv if hist_cv > 0 else hist_flow
            else:
                tag_val = float(row.get(tag, 0))
            score += tag_val * w * aggression

    if isinstance(current_state, dict):
        dist_sum = 0.0
        if active_constraints and hasattr(active_constraints, 'items'):
            source_items = active_constraints.items()
        elif controls_cfg and hasattr(controls_cfg, 'items'):
            source_items = controls_cfg.items()
        else:
            source_items = []

        use_mahalanobis = is_advanced and inv_cov is not None and mahalanobis is not None
        mahal_tags = active_tags_ordered if active_tags_ordered else []

        if use_mahalanobis and mahal_tags:
            u_vec, v_vec = [], []
            for tag in mahal_tags:
                curr_val = float(current_state.get(tag, 0))
                hist_val = align_magnitude(row.get(tag, 0), curr_val)
                if tag in fuel_pairing:
                    curr_val = get_heat_input(tag, curr_val, current_state, conf)
                    hist_cv_tag = fuel_pairing[tag]
                    hist_cv = float(row.get(hist_cv_tag, 0))
                    if hist_cv > 0: hist_val = float(row.get(tag, 0)) * hist_cv
                u_vec.append(curr_val)
                v_vec.append(hist_val)
            try:
                m_dist = mahalanobis(u_vec, v_vec, inv_cov)
                if np.isnan(m_dist) or m_dist > 500:
                    use_mahalanobis = False
                else:
                    dist_sum = m_dist ** 2
            except Exception:
                use_mahalanobis = False

        if not use_mahalanobis or dist_sum == 0.0:
            for tag, props in source_items:
                prio = int(props.get('priority', 3))
                if not is_advanced and prio != 1: continue
                if prio == 0 or props.get('is_calculated', False) or 'formula' in props: continue

                curr_val = float(current_state.get(tag, 0))
                hist_val = align_magnitude(row.get(tag, 0), curr_val)

                if tag in fuel_pairing:
                    curr_val = get_heat_input(tag, curr_val, current_state, conf)
                    hist_cv_tag = fuel_pairing[tag]
                    hist_cv = float(row.get(hist_cv_tag, 0))
                    if hist_cv > 0: hist_val = float(row.get(tag, 0)) * hist_cv

                if curr_val != 0:
                    multipliers = scoring_cfg.get('priority_multipliers', {'1': 10.0, '2': 5.0})
                    weight = float(multipliers.get(str(prio), 1.0)) if is_advanced else 1.0
                    raw_delta = abs(curr_val - hist_val) / abs(curr_val)
                    normalised_delta = min(raw_delta, 3.0)
                    dist_sum += (normalised_delta ** 2) * weight

        p_weight = scoring_cfg.get('distance_penalty_weight', penalty_weight)
        total_penalty = dist_sum * p_weight
        if total_penalty > 800000: total_penalty = 800000
        score -= total_penalty

    if live_slopes and is_advanced and past_row is not None:
        slope_cfg = conf.get('scoring_settings', {})
        slope_bonus = float(slope_cfg.get('trend_match_bonus', 50.0))
        slope_penalty = float(slope_cfg.get('trend_mismatch_penalty', 200.0))
        slope_bonus_total = 0.0
        slope_penalty_total = 0.0
        for tag, live_slope in live_slopes.items():
            if tag in row and tag in past_row:
                hist_val_now = float(row.get(tag, 0))
                hist_val_past = float(past_row.get(tag, hist_val_now))
                hist_direction = hist_val_now - hist_val_past

                if abs(live_slope) > 1e-4 and abs(hist_direction) > 1e-4:
                    if (live_slope > 0) == (hist_direction > 0):
                        slope_bonus_total += slope_bonus
                    else:
                        slope_penalty_total += slope_penalty
        score += slope_bonus_total - slope_penalty_total

    if ts_col in row and pd.notnull(row[ts_col]):
        try:
            age_days = (now - row[ts_col]).total_seconds() / 86400.0
            age_penalty = scoring_cfg.get('age_penalty_per_day', 0.5)
            score -= (age_days * age_penalty)
            recency_days = float(scoring_cfg.get('recency_boost_days', 14))
            recency_bonus = float(scoring_cfg.get('recency_boost_value', 200))
            if age_days <= recency_days:
                score += recency_bonus
        except: pass
    return score

# ==============================================================================
# 5. SEARCH & OPTIMIZATION
# ==============================================================================
def apply_golden_filter(hist_df):
    if hist_df.empty: return hist_df
    conf = get_model_config_safe()
    logic = conf.get('logic_tags', {})
    strategy_name, strat = get_active_strategy(conf)

    filter_tag = logic.get('golden_filter_tag')
    filter_limit = logic.get('golden_filter_max', 850.0)
    if filter_tag and filter_tag in hist_df.columns:
        hist_df = hist_df[hist_df[filter_tag] <= filter_limit]

    prefilter = strat.get('golden_prefilter', conf.get('golden_prefilter', {}))
    for tag, limits in (prefilter or {}).items():
        if tag.startswith('_') or tag == 'comment' or tag not in hist_df.columns or not isinstance(limits, dict): continue
        lo = limits.get('min', None)
        hi = limits.get('max', None)
        if lo is not None and hi is not None:
            hist_df = hist_df[hist_df[tag].between(float(lo), float(hi))]
        elif lo is not None:
            hist_df = hist_df[hist_df[tag] >= float(lo)]
        elif hi is not None:
            hist_df = hist_df[hist_df[tag] <= float(hi)]
    return hist_df

def get_mahalanobis_matrix(hist_df, active_cols):
    global CACHE_COV
    if mahalanobis is None or pinv is None: return None
    try:
        cache_key = hash(tuple(sorted(active_cols)))
        if CACHE_COV is not None and isinstance(CACHE_COV, tuple) and CACHE_COV[0] == cache_key:
            return CACHE_COV[1]
        sub_df = hist_df[active_cols].dropna()
        if sub_df.empty: return None
        cov_matrix = np.cov(sub_df.values.T)
        if cov_matrix.ndim == 2:
            np.fill_diagonal(cov_matrix, cov_matrix.diagonal() + 1e-6)
        inv_cov = pinv(cov_matrix)
        CACHE_COV = (cache_key, inv_cov)
        return inv_cov
    except Exception:
        return None

def find_closest_historical_batches(historical_df, current_state, filter_tags, limit=50):
    if historical_df.empty: return pd.DataFrame()
    temp_df = historical_df.copy()
    total_dist_sq = pd.Series(0.0, index=temp_df.index)

    valid_tags = [t for t in filter_tags if t in temp_df.columns and t in current_state]
    if not valid_tags:
        return temp_df.tail(limit)

    for tag in valid_tags:
        curr_val = float(current_state[tag])
        std = temp_df[tag].std()
        if std == 0 or np.isnan(std): std = 1.0
        tag_dist_sq = ((temp_df[tag] - curr_val) / std) ** 2
        total_dist_sq += tag_dist_sq

    temp_df['_proximity_error'] = np.sqrt(total_dist_sq)
    temp_df = temp_df.sort_values('_proximity_error')

    diverse_results = []
    diversity_minutes = 120
    ts_col = get_timestamp_col()

    for _, row in temp_df.iterrows():
        ts = row[ts_col]
        is_diverse = True
        for existing_ts in diverse_results:
            if abs((ts - existing_ts).total_seconds()) < (diversity_minutes * 60):
                is_diverse = False
                break
        if is_diverse: diverse_results.append(ts)
        if len(diverse_results) >= limit: break

    return temp_df[temp_df[ts_col].isin(diverse_results)].drop(columns=['_proximity_error'])


def find_best_fingerprint_advanced(current_real_df_window, historical_df, frontend_strategy, current_state,
                                   weights=None):
    if historical_df.empty: return [], False

    # Normalize frontend_strategy: convert any string values or non-dict objects into dictionaries
    # with default boundaries to prevent downstream AttributeError/TypeError
    normalized_strategy = {}
    if isinstance(frontend_strategy, dict):
        for k, v in frontend_strategy.items():
            if isinstance(v, dict):
                normalized_strategy[k] = v.copy()
            else:
                normalized_strategy[k] = {
                    "priority": 3,
                    "min": -9e9,
                    "max": 9e9,
                    "custom_min": -9e9,
                    "custom_max": 9e9,
                    "value": str(v)
                }
    frontend_strategy = normalized_strategy

    initial_count = len(historical_df)
    conf = get_model_config_safe()
    if HAS_PROCESS_MODEL and process_model:
        all_vars_cfg = {**process_model.get_control_variables(), **process_model.get_indicator_variables()}
    else:
        all_vars_cfg = {**conf.get('control_variables', {}), **conf.get('indicator_variables', {})}

    valid_history = apply_golden_filter(historical_df.copy())
    ts_col = get_timestamp_col()
    active_constraints = {}
    active_tags = []

    logic_cfg = conf.get('logic_tags', {})
    std_tol = float(logic_cfg.get('std_search_tolerance', 0.25))

    search_phases = [
        {'name': 'Standard', 'tol': std_tol},
        {'name': 'Steering (Relaxed)', 'tol': 1.0}
    ]

    working_history = valid_history.copy()
    final_matches = pd.DataFrame()

    core_tags = conf.get('logic_tags', {}).get('deviation_filter_tags', [])
    if not core_tags:
        core_tags = [t for t, c in all_vars_cfg.items() if int(c.get('priority', 3)) == 1]

    # Automatically force any variable with a dynamic target into the strict filtering phase
    for t, c in all_vars_cfg.items():
        if c.get('enable_dynamic_limits', False) and ('dynamic_sp_tag' in c or 'dynamic_min_tag' in c):
            if t not in core_tags: core_tags.append(t)

    for phase in search_phases:
        phase_history = working_history.copy()
        tol_pct = phase['tol']

        for tag, strategy in frontend_strategy.items():
            actual_col = tag
            if tag not in phase_history.columns:
                cfg_match = all_vars_cfg.get(tag, {})
                tag_name = cfg_match.get('tag_name')
                if tag_name and tag_name in phase_history.columns:
                    actual_col = tag_name
                else:
                    continue

            is_manual = any(k in strategy for k in ['custom_min', 'custom_max', 'min', 'max', 'Higher', 'Lower'])
            if not is_manual and tag not in core_tags:
                continue

            try:
                cfg_var = all_vars_cfg.get(tag, {})
                prio = int(cfg_var.get('priority', 3))
                
                # --- NEW: DYNAMIC LIMIT CHECK ---
                is_enabled = cfg_var.get('enable_dynamic_limits', False)
                has_configured_tags = 'dynamic_sp_tag' in cfg_var or 'dynamic_min_tag' in cfg_var
                has_dynamic_target = is_enabled and has_configured_tags

                # Do NOT skip calculated variables if they are acting as dynamic external targets!
                if not has_dynamic_target and (prio == 0 or cfg_var.get('is_calculated', False) or 'formula' in cfg_var):
                    continue

                # Fetch Dynamic Limits (falls back to static defaults if not present)
                dyn_min, dyn_max = process_model.get_dynamic_limits(cfg_var, current_state)
                
                abs_min = float(strategy.get('custom_min', strategy.get('min', strategy.get('Min', dyn_min))))
                abs_max = float(strategy.get('custom_max', strategy.get('max', strategy.get('Max', dyn_max))))
                
                cur_val = float(current_state.get(tag, 0))
                abs_band = float(strategy.get('tolerance_abs', cfg_var.get('tolerance_abs', 9e9)))

                # If dynamic limits are active, ignore the +/- 15% live-value rule completely
                if has_dynamic_target:
                    eff_min = abs_min
                    eff_max = abs_max
                else:
                    if cur_val != 0:
                        delta_pct = abs(cur_val * tol_pct)
                        eff_delta = min(delta_pct, abs_band)
                        tol_min = cur_val - eff_delta
                        tol_max = cur_val + eff_delta
                    else:
                        tol_min = -min(tol_pct, abs_band)
                        tol_max = min(tol_pct, abs_band)

                    eff_min = max(abs_min, tol_min)
                    eff_max = min(abs_max, tol_max)

                prev_len = len(phase_history)
                phase_history = phase_history[phase_history[actual_col].between(eff_min, eff_max)]

                if phase_history.empty:
                    break
            except (TypeError, ValueError, KeyError):
                continue

        if not phase_history.empty:
            final_matches = phase_history
            for tag, strategy in frontend_strategy.items():
                cfg_var = all_vars_cfg.get(tag, {})
                prio = int(cfg_var.get('priority', 3))
                has_dyn = cfg_var.get('enable_dynamic_limits', False) and ('dynamic_sp_tag' in cfg_var or 'dynamic_min_tag' in cfg_var)
                if not has_dyn and (prio == 0 or cfg_var.get('is_calculated', False) or 'formula' in cfg_var):
                    continue
                active_constraints[tag] = strategy.copy()
                active_constraints[tag]['eff_tol'] = tol_pct
            break

    is_fallback = False
    if final_matches.empty:
        is_fallback = True
        final_matches = find_closest_historical_batches(working_history, current_state, core_tags, limit=50)

        if not active_constraints:
            for tag, strategy in frontend_strategy.items():
                cfg_var = all_vars_cfg.get(tag, {})
                prio = int(cfg_var.get('priority', 3))
                has_dyn = cfg_var.get('enable_dynamic_limits', False) and ('dynamic_sp_tag' in cfg_var or 'dynamic_min_tag' in cfg_var)
                if not has_dyn and (prio == 0 or cfg_var.get('is_calculated', False) or 'formula' in cfg_var):
                    continue
                active_constraints[tag] = strategy.copy()
                active_constraints[tag]['eff_tol'] = 1.0

    valid_history = final_matches
    scoring_tags = []
    for t in frontend_strategy.keys():
        if t in valid_history.columns:
            cfg_var = all_vars_cfg.get(t, {})
            prio = int(cfg_var.get('priority', 3))
            is_calc = cfg_var.get('is_calculated', False) or 'formula' in cfg_var
            if prio == 0 or is_calc:
                continue
            scoring_tags.append(t)

    active_tags = scoring_tags
    inv_cov = get_mahalanobis_matrix(valid_history, active_tags)

    if ts_col in valid_history.columns:
        valid_history[ts_col] = pd.to_datetime(valid_history[ts_col], errors='coerce')

    live_slopes = {}
    try:
        if current_real_df_window is not None and not current_real_df_window.empty:
            for tag in active_tags:
                if tag in current_real_df_window.columns:
                    tail = current_real_df_window[tag].dropna().tail(10)
                    if len(tail) >= 2:
                        live_slopes[tag] = float(tail.iloc[-1] - tail.iloc[0])
    except Exception: pass

    try:
        conf_tmp = get_model_config_safe()
        strategy_name_tmp, strat_tmp = get_active_strategy(conf_tmp)
        opt_tmp = strat_tmp.get('optimisation_target', {})
        primary_tag_tmp = opt_tmp.get('primary_tag')
        primary_direction = opt_tmp.get('primary_direction', 'maximize').lower()
        if primary_tag_tmp and primary_tag_tmp in valid_history.columns:
            curr_primary = float(current_state.get(primary_tag_tmp, 0))
            if primary_direction == 'minimize':
                target_percentile = float(valid_history[primary_tag_tmp].quantile(0.10))
                gap_to_target = max(0.0, curr_primary - target_percentile)
            else:
                target_percentile = float(valid_history[primary_tag_tmp].quantile(0.90))
                gap_to_target = max(0.0, target_percentile - curr_primary)
            if gap_to_target > 0 and primary_tag_tmp in weights:
                weights[primary_tag_tmp] = weights[primary_tag_tmp] + gap_to_target * 0.1
    except Exception: pass

    def _adv_score_wrapper(row):
        try:
            r_idx = int(row.name)
            past_row = historical_df.loc[r_idx - 10] if r_idx > 10 and (r_idx - 10) in historical_df.index else row
        except Exception:
            past_row = row
        return _calculate_core_score(
            row, current_state, None, weights,
            active_constraints=active_constraints,
            inv_cov=inv_cov, live_slopes=live_slopes,
            active_tags_ordered=active_tags, is_advanced=True, past_row=past_row
        )

    final_matches = final_matches.copy()
    final_matches['score'] = final_matches.apply(_adv_score_wrapper, axis=1)
    df_sorted = final_matches.sort_values(by='score', ascending=False)
    df_sorted = df_sorted[df_sorted['score'] > -900000]

    stable_rows = []
    for _, r in df_sorted.iterrows():
        match_ts = r.get(ts_col)
        if any(abs((match_ts - ext.get(ts_col)).total_seconds()) < 7200 for ext in stable_rows): continue
        if check_future_stability(historical_df, match_ts): stable_rows.append(r)
        if len(stable_rows) >= 5: break

    return [dict(r) for r in stable_rows], is_fallback

# ==============================================================================
# 6. MAIN CONTROLLER
# ==============================================================================
LAST_AUTO_SCAN_TIME = None
CACHED_AUTO_RESULT = None

def get_scan_interval(): return getattr(config, 'SCAN_INTERVAL_SECONDS', 300)

def calculate_kpis(current_state):
    try:
        conf = get_model_config_safe()
        strategy_name, _ = get_active_strategy(conf)
        kpi_definitions = conf.get('kpi_tags', {})
        results = {'ActiveStrategy': strategy_name}
        for kpi_name, defn in kpi_definitions.items():
            tag = defn.get('tag')
            dec = defn.get('decimals', 1)
            if tag:
                try: results[kpi_name] = round(float(current_state.get(tag, 0)), dec)
                except (ValueError, TypeError): results[kpi_name] = 0.0
            else: results[kpi_name] = 0.0
        return results
    except Exception: return {}

def check_disturbance_rules(current_state):
    if not HAS_PROCESS_MODEL or not process_model: return None
    try:
        conf = process_model.load_model_config()
        nudge = conf.get('nudge_settings', {})
        default_ramp_rate = nudge.get('min_step_fraction', 0.005)

        for rule in conf.get('safety_rules', []):
            if not rule.get('enabled', True): continue
            live = float(current_state.get(rule['condition_var'], 9999))
            op = rule.get('operator')
            thresh = rule.get('threshold')

            if (op == '>' and live > thresh) or (op == '<' and live < thresh):
                tgt = rule['action_var']
                action_type = rule.get('action_type', 'offset')
                raw_value = rule['action_value']
                ramp_rate = rule.get('ramp_rate', None)
                curr = float(current_state.get(tgt, 0))

                if action_type == 'offset':
                    if ramp_rate is not None:
                        capped_value = max(-abs(ramp_rate), min(abs(ramp_rate), raw_value))
                    else:
                        capped_value = raw_value * default_ramp_rate if curr != 0 else raw_value
                    new_v = curr + capped_value
                elif action_type == 'min_clamp':
                    target_clamped = float(raw_value)
                    diff = target_clamped - curr
                    if ramp_rate is not None: step = max(-abs(ramp_rate), min(abs(ramp_rate), diff))
                    else: step = diff * default_ramp_rate
                    new_v = curr + step
                else: new_v = curr + raw_value

                return {
                    "match_score": "SAFETY-CLAMP",
                    "timestamp": str(pd.Timestamp.now()),
                    "actions": [{"var_name": tgt, "fingerprint_set_point": new_v,
                                 "current_setpoint": str(curr),
                                 "reason": f"SAFETY: {rule['name']} (gradual)"}]
                }
    except Exception: pass
    return None

def get_live_fingerprint_action(current_real_df_window, frontend_strategy=None):
    global LAST_AUTO_SCAN_TIME, CACHED_AUTO_RESULT
    if current_real_df_window.empty: return None

    sim_pct = 0.0
    is_fallback = False
    match_meta = {}
    reason = "Initial Search"

    try:
        raw_state = current_real_df_window.iloc[-1].to_dict()
        now = pd.Timestamp.now()
        mode = getattr(config, 'FINGERPRINT_MODE_TYPE', 'AUTO') if config else "AUTO"

        if HAS_PROCESS_MODEL and process_model:
            controls_cfg = process_model.get_control_variables()
            indicators_cfg = process_model.get_indicator_variables()
            base_weights = process_model.get_optimization_weights()

            if not frontend_strategy:
                frontend_strategy = {}
                for k, v in controls_cfg.items():
                    frontend_strategy[k] = {
                        "priority": int(v.get('priority', 3)),
                        "min": float(v.get('default_min', -9e9)),
                        "max": float(v.get('default_max', 9e9)),
                        "tolerance_pct": 25
                    }
                for k, v in indicators_cfg.items():
                    if int(v.get('priority', 3)) == 1:
                        conf_tmp = get_model_config_safe()
                        strict_tol_pct = float(conf_tmp.get('logic_tags', {}).get('strict_search_tolerance', 0.1)) * 100
                        frontend_strategy[k] = {
                            "priority": 1,
                            "min": float(v.get('default_min', -9e9)),
                            "max": float(v.get('default_max', 9e9)),
                            "tolerance_pct": strict_tol_pct
                        }
        else:
            controls_cfg = {}
            indicators_cfg = {}
            base_weights = {}
            frontend_strategy = frontend_strategy or {}

        full_conf = get_model_config_safe()
        calc_vars_cfg = full_conf.get('calculated_variables', {})
        strategy_name, strat = get_active_strategy(full_conf)
        nudge_cfg = full_conf.get('nudge_settings', {})
        step_fraction = nudge_cfg.get('step_fraction', 0.15)

        current_state = map_tags_to_friendly_names(raw_state, controls_cfg, indicators_cfg, calc_vars_cfg)
        if (d := check_disturbance_rules(current_state)): return d
        dynamic_weights = calculate_dynamic_weights(current_state, base_weights)

        target_vals, target_disp = {}, "Searching..."
        top_matches = []

        if mode == 'MANUAL':
            try:
                state_dir = getattr(config, 'JSON_DIR', 'files/json')
                with open(os.path.join(state_dir, "current_target.json"), 'r') as f:
                    data = json.load(f)
                    target_disp = data.get("fingerprint_timestamp", "Manual")
                    is_fallback = data.get("is_fallback", False)
                    hist_df = get_cached_dataframe(controls_cfg, indicators_cfg)
                    ts_col = get_timestamp_col()

                    matched_rows = hist_df[hist_df[ts_col].astype(str) == str(target_disp)]
                    if not matched_rows.empty:
                        target_vals = matched_rows.iloc[0].to_dict()
                        pure_historical_row = dict(target_vals)

                    for a in data.get('actions', []):
                        target_vals[a['var_name']] = float(a['fingerprint_set_point'])
                    reason = "Manual Target"
            except Exception:
                mode = 'AUTO'

        if mode != 'MANUAL':
            time_since_last = (now - LAST_AUTO_SCAN_TIME).total_seconds() if LAST_AUTO_SCAN_TIME else 99999

            if time_since_last >= get_scan_interval() or CACHED_AUTO_RESULT is None:
                hist_df = get_cached_dataframe(controls_cfg, indicators_cfg)
                best_rows, is_fallback = find_best_fingerprint_advanced(
                    current_real_df_window, hist_df, frontend_strategy, current_state, weights=dynamic_weights
                )

                if best_rows:
                    best = best_rows[0]
                    ts_col = get_timestamp_col()
                    sim_pct = calculate_match_percentage(current_state, best, controls_cfg, indicators_cfg)

                    match_meta = {
                        'strategy': strategy_name,
                        'similarity_score': round(sim_pct, 1),
                        'is_fallback': is_fallback
                    }
                    opt_conf = strat.get('optimisation_target', full_conf.get('optimisation_target', {}))
                    
                    primary_tag = opt_conf.get('primary_tag')
                    if primary_tag and primary_tag in best:
                        match_meta['primary_tag'] = primary_tag
                        match_meta['primary_value_at_match'] = round(float(best.get(primary_tag, 0)), 2)

                    motor_tag = full_conf.get('optimisation_target', {}).get('primary_tag', 'Kiln motor 1 Amps')
                    if motor_tag in best: match_meta['motor_current_at_match'] = round(float(best.get(motor_tag, 0)), 1)
                    for kpi_tag, kpi_key in [('% TSR (Kiln)', 'tsr_at_match'), ('SHC', 'shc_at_match')]:
                        if kpi_tag in best: match_meta[kpi_key] = round(float(best.get(kpi_tag, 0)), 2)

                    pure_historical_row = dict(best)
                    target_vals_dict = dict(best)
                    try:
                        top_5 = pd.DataFrame(best_rows[:5])
                        for ctrl_tag in controls_cfg.keys():
                            if ctrl_tag in top_5.columns:
                                valid_ctrls = top_5[ctrl_tag].replace(0, np.nan).dropna()
                                if not valid_ctrls.empty:
                                    target_vals_dict[ctrl_tag] = float(valid_ctrls.median())
                    except Exception: pass

                    enriched_matches = []
                    for match_row in best_rows[:5]:
                        ts = match_row.get(ts_col)
                        s = calculate_match_percentage(current_state, dict(match_row), controls_cfg, indicators_cfg)
                        enriched_matches.append({"timestamp": str(ts), "similarity": round(s, 1)})

                    CACHED_AUTO_RESULT = {
                        'target_vals': target_vals_dict, 'pure_historical_row': pure_historical_row,
                        'target_disp': str(best.get(ts_col)), 'top_matches': enriched_matches,
                        'match_meta': match_meta, 'is_fallback': is_fallback
                    }
                    LAST_AUTO_SCAN_TIME = now
                else: LAST_AUTO_SCAN_TIME = now

            if CACHED_AUTO_RESULT:
                target_vals = CACHED_AUTO_RESULT["target_vals"]
                pure_historical_row = CACHED_AUTO_RESULT.get("pure_historical_row", target_vals)
                target_disp = CACHED_AUTO_RESULT["target_disp"]
                top_matches = CACHED_AUTO_RESULT.get("top_matches", [])
                match_meta = CACHED_AUTO_RESULT.get("match_meta", {})
                sim_pct = match_meta.get('similarity_score', 0.0)
                is_fallback = CACHED_AUTO_RESULT.get("is_fallback", False)
                reason = "Best Match (Cached)"

        if mode != 'AUTO':
            if target_vals and 'pure_historical_row' in locals():
                sim_pct = calculate_match_percentage(current_state, pure_historical_row, controls_cfg, indicators_cfg)
                if match_meta is not None: match_meta['is_fallback'] = is_fallback
            elif target_vals:
                sim_pct = calculate_match_percentage(current_state, target_vals, controls_cfg, indicators_cfg)
                if match_meta is not None:
                    match_meta['similarity_score'] = round(sim_pct, 1)
                    match_meta['is_fallback'] = is_fallback

        ui_actions = []
        for tag, cfg_var in controls_cfg.items():
            if not cfg_var.get('aipc', True): continue
            if not cfg_var.get('is_setpoint', True): continue

            curr = float(current_state.get(tag, 0))
            tgt = align_magnitude(float(target_vals.get(tag, curr)), curr)

            # --- NEW: DYNAMIC LIMIT CHECK FOR NUDGING ---
            gain = abs(float(cfg_var.get('nudge_speed', step_fraction)))
            def_min, def_max = process_model.get_dynamic_limits(cfg_var, current_state)

            nudged_target = process_model.apply_industrial_nudge(curr, tgt, gain, def_min, def_max)

            if abs(nudged_target - tgt) < 0.001: reason_final = f"{reason} (Synced)"
            else: reason_final = f"{reason} (Nudge Applied)"

            ui_actions.append({
                "var_name": tag,
                "fingerprint_set_point": tgt,
                "nudge_target": nudged_target,
                "final_target": tgt,
                "current_setpoint": str(curr),
                "reason": reason_final
            })

        calc_actions = process_model.generate_calculated_actions(
            ui_actions, current_state, controls_cfg, indicators_cfg, calc_vars_cfg
        )
        
        calc_names = {c['var_name'] for c in calc_actions}
        ui_actions = [a for a in ui_actions if a.get('var_name') not in calc_names]
        ui_actions.extend(calc_actions)

        match_meta['similarity_score'] = round(sim_pct, 1)
        match_meta['is_fallback'] = is_fallback

        return {
            "match_score": sim_pct,
            "status": f"ACTIVE-{mode}",
            "timestamp": str(now),
            "target_timestamp": target_disp, "top_matches": top_matches,
            "fingerprint_prediction": process_model.extract_future_from_history(hist_df, target_disp, window_min=15) if 'hist_df' in locals() and target_disp else {},
            "match_meta": match_meta,
            "calculated_metrics": calculate_kpis(current_state),
            "actions": ui_actions
        }
    except Exception as e:
        engine_logger.error(f"Runtime Error: {e}", exc_info=True)
        return None