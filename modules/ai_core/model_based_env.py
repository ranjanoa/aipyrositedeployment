import numpy as np
import torch
import sys
import os

# --- PATH SETUP ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
import process_model


# ==============================================================================
# PURE REWARD TERM DISPATCHER
# No state, no side effects — easy to unit-test independently.
# Supported types:
#   target_deviation  : -w * |value - target|
#   range_keep        : 0 if in [min, max], else -w * overshoot
#   upper_limit       : -w * max(0, value - limit)
#   lower_limit       : -w * max(0, floor  - value)
#   maximize          : +w * (value / scale)
#   minimize          : -w * (value / scale)
# ==============================================================================
def _compute_term(term, value):
    """Compute a single reward term. Returns 0.0 on any config error."""
    t = term.get('type', '')
    w = float(term.get('weight', 0.0))
    try:
        if t == 'target_deviation':
            return -w * abs(value - float(term['target']))

        elif t == 'range_keep':
            lo, hi = float(term['min']), float(term['max'])
            if lo <= value <= hi:
                return 0.0
            overshoot = max(0.0, value - hi) + max(0.0, lo - value)
            return -w * overshoot

        elif t == 'upper_limit':
            return -w * max(0.0, value - float(term['limit']))

        elif t == 'lower_limit':
            return -w * max(0.0, float(term['floor']) - value)

        elif t == 'maximize':
            scale = float(term.get('scale', 1.0))
            return (w * value / scale) if scale != 0.0 else 0.0

        elif t == 'minimize':
            scale = float(term.get('scale', 1.0))
            return (-w * value / scale) if scale != 0.0 else 0.0

    except (KeyError, TypeError, ValueError):
        pass

    return 0.0


class PessimisticVirtualEnv:
    """
    A Virtual Environment that uses the trained World Model to simulate the plant.
    It allows the SAC Agent to learn 'Offline' without touching the real plant.

    Reward is fully config-driven via `reward_components` in model_config.json.
    Each strategy can define its own reward terms. Falls back to the legacy
    single-target deviation penalty if no reward_components are configured.
    """

    def __init__(self, world_model, history_df, env_params, history_window=5, strategy_name=None):
        self.wm = world_model
        self.df = history_df
        self.hw = history_window

        # --- UNPACK PARAMS ---
        self.stats = env_params
        self.s_cols = env_params['s_cols']
        self.a_cols = env_params['a_cols']

        self.s_dim = len(self.s_cols)
        self.a_dim = len(self.a_cols)

        # --- LOAD OPTIMIZATION GOALS FROM CONFIG ---
        config = process_model.load_model_config()
        self.opt_settings = config.get('optimization_settings', {})

        # Strategy config takes precedence over global optimization_settings
        if strategy_name is None:
            strategy_name = config.get('active_strategy', 'BALANCED')
        self.strategy_cfg = config.get('strategies', {}).get(strategy_name, {})

        # Action-level bias weights (unchanged — kept for strategy fuel preference)
        self.weights = self.strategy_cfg.get('weights', self.opt_settings.get('weights', {}))

        # Legacy fallback fields (used only when reward_components is empty)
        self.target_setpoint = self.strategy_cfg.get(
            'target_setpoint', self.opt_settings.get('target_setpoint', 1450.0)
        )
        self.deviation_penalty = self.strategy_cfg.get(
            'deviation_penalty', self.opt_settings.get('deviation_penalty', 0.1)
        )
        bindings = config.get('ai_bindings', {})
        self.target_var = bindings.get('primary_prediction_target', 'sinteringZoneTemp')

        # --- LOAD MODULAR REWARD COMPONENTS ---
        # Strategy-level components take precedence; fall back to global; then empty list.
        strat_rewards  = self.strategy_cfg.get('reward_components', [])
        global_rewards = self.opt_settings.get('reward_components', [])
        self.reward_components = strat_rewards if strat_rewards else global_rewards

        # Pre-build tag → s_cols index map for O(1) lookup inside step()
        self.tag_index_map = {}
        for term in self.reward_components:
            tag = term.get('tag', '')
            if not tag:
                continue
            if tag in self.s_cols:
                self.tag_index_map[tag] = self.s_cols.index(tag)
            else:
                print(
                    f"⚠️ [RewardConfig] Tag '{tag}' in reward_components "
                    f"not found in state space (s_cols) — term will be skipped."
                )

        # Internal State
        self.current_obs = None
        self.last_norm_s = None
        self.steps = 0
        self.max_steps = 100
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def reset(self):
        idx = np.random.randint(self.hw, len(self.df) - 1)

        def norm(vals, vtype):
            mn = self.stats[vtype]['min']
            rng = self.stats[vtype]['range']
            return (vals - mn) / rng

        raw_s = self.df[self.s_cols].iloc[idx - self.hw: idx].values
        raw_a = self.df[self.a_cols].iloc[idx - self.hw: idx].values

        norm_s = norm(raw_s, 'state')
        norm_a = norm(raw_a, 'action')

        self.current_obs = np.concatenate([norm_s, norm_a], axis=1).flatten()

        # Sanitize initial state and observation
        self.current_obs = np.nan_to_num(self.current_obs, nan=0.0)
        self.last_norm_s = np.nan_to_num(norm_s[-1], nan=0.0)

        self.steps = 0
        return self.current_obs

    def sample_random_action(self):
        return np.random.uniform(0, 1, size=self.a_dim)

    def step(self, action):
        self.steps += 1

        # 1. PREDICT NEXT STATE via World Model
        inp_tensor = torch.FloatTensor(self.current_obs).unsqueeze(0).to(self.device)
        with torch.no_grad():
            mean_delta, _ = self.wm.predict(inp_tensor)

        delta = mean_delta.cpu().numpy()[0]
        # World Model was trained on delta * 100.0 — undo scaling
        next_norm_s = self.last_norm_s + (delta / 100.0)

        # Sanitize and clip the dream state
        next_norm_s = np.nan_to_num(next_norm_s, nan=0.0)
        next_norm_s = np.clip(next_norm_s, -5.0, 5.0)

        def denorm(val, idx, vtype='state'):
            mn  = self.stats[vtype]['min'][idx]
            rng = self.stats[vtype]['range'][idx]
            return (val * rng) + mn

        # 2. COMPUTE REWARD
        reward = 0.0
        try:
            if self.reward_components:
                # -------------------------------------------------------
                # CONFIG-DRIVEN MULTI-TERM REWARD
                # Each term in reward_components contributes independently.
                # Missing tags are silently skipped (warned at init).
                # -------------------------------------------------------
                for term in self.reward_components:
                    tag = term.get('tag', '')
                    if tag not in self.tag_index_map:
                        continue
                    idx = self.tag_index_map[tag]
                    value = denorm(next_norm_s[idx], idx)
                    r_term = _compute_term(term, value)
                    # Guard individual term against NaN/Inf
                    r_term = float(np.nan_to_num(r_term, nan=0.0, posinf=0.0, neginf=0.0))
                    reward += r_term

            else:
                # -------------------------------------------------------
                # LEGACY FALLBACK: single target-deviation penalty
                # Used when no reward_components are configured.
                # -------------------------------------------------------
                if self.target_var in self.s_cols:
                    t_idx = self.s_cols.index(self.target_var)
                    pred_val = denorm(next_norm_s[t_idx], t_idx)
                    diff = abs(float(pred_val) - float(self.target_setpoint))
                    reward -= min(diff * self.deviation_penalty, 500.0)

            # Action-level strategy bias weights (unchanged from original)
            for i, tag in enumerate(self.a_cols):
                if tag in self.weights:
                    reward += float(action[i]) * self.weights[tag]

            # Final reward sanity check
            if np.isnan(reward) or np.isinf(reward):
                print(f"⚠️ Warning: NaN/Inf in total reward. Clipping to -10.")
                reward = -10.0

        except Exception as e:
            print(f"⚠️ Reward Error: {e}")
            reward = -10.0

        # 3. UPDATE OBSERVATION BUFFER  [s0, a0, s1, a1, ...]
        new_step = np.concatenate([next_norm_s, action])
        self.current_obs = np.concatenate([self.current_obs[self.s_dim + self.a_dim:], new_step])
        self.last_norm_s = next_norm_s
        self.steps += 1
        done = self.steps >= self.max_steps

        # Final sanitization of all environment outputs
        obs    = np.nan_to_num(self.current_obs)
        reward = float(np.nan_to_num(reward))

        return obs, reward, done, {}