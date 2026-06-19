/**
 * initTargetVariables.js
 * ======================
 * Shared helper: populates a "Target Variables" table from
 * model_config.json → calculated_variables (where is_setpoint === true).
 *
 * Each row shows:
 *   Variable | Unit | Curr (colour-coded vs range) | Nudge (▲/▼) | Target
 *
 * Nudge and Target are filled by updateTargetVariables() when
 * autopilot_update actions arrive that reference a matching var_name.
 * Range is shown as a tooltip on the Curr cell (title attribute).
 */

import { state } from "../inits/state.js";

// ── internal registry ────────────────────────────────────────────────────────
// Maps pageId → [ { key, safeId, min, max } ]
const _tvRegistry = {};

/**
 * Build and insert target variable rows into a tbody.
 *
 * @param {object} opts
 * @param {string}   opts.tbodyId      - DOM id of the <tbody> to populate
 * @param {string[]} opts.pageKeywords - lower-case words; a row MUST match at least one
 * @param {string[]} opts.excludeKeys  - lower-case words; a row is excluded if any match
 * @param {string}   opts.trendAction  - Actions method name for the trend button
 * @param {string}   opts.pageId       - short id used in element ids (e.g. 'kiln')
 */
export function initTargetVariables({ tbodyId, pageKeywords = [], excludeKeys = [], trendAction, pageId }) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;

    const cfg      = state.currentModelConfig || {};
    const calcVars = cfg.calculated_variables || {};

    // Collect all is_setpoint variables that have a defined dynamic_sp_tag
    const targets = Object.entries(calcVars)
        .filter(([, v]) => v.is_setpoint === true && v.dynamic_sp_tag)
        .map(([key, v]) => ({
            key,
            label: v.friendly_name || v.description || key,
            unit:  v.unit || '',
            min:   v.default_min !== undefined ? v.default_min : null,
            max:   v.default_max !== undefined ? v.default_max : null,
        }));

    // Filter by page keywords / excludes
    const filtered = targets.filter(({ key, label }) => {
        const haystack = (key + ' ' + label).toLowerCase();
        if (excludeKeys.length && excludeKeys.some(k => haystack.includes(k))) return false;
        if (!pageKeywords.length) return true;
        return pageKeywords.some(k => haystack.includes(k));
    });

    filtered.sort((a, b) => a.label.localeCompare(b.label));

    tbody.innerHTML = '';
    _tvRegistry[pageId] = [];

    if (!filtered.length) {
        tbody.innerHTML = `<tr><td colspan="5" class="p-2 text-center text-gray-500 text-[10px]">No target variables configured</td></tr>`;
        return;
    }

    filtered.forEach(({ key, label, unit, min, max }) => {
        const safeId   = key.replace(/[^a-zA-Z0-9]/g, '');
        const currId   = `op-tgt-curr-${pageId}-${safeId}`;
        const statusId = `op-tgt-status-${pageId}-${safeId}`;
        const nudgeId  = `op-tgt-nudge-${pageId}-${safeId}`;
        const tgtId    = `op-tgt-tgt-${pageId}-${safeId}`;

        const rangeStr = (min !== null && max !== null)
            ? `Range: ${min}–${max} ${unit}`
            : (min !== null ? `Min: ${min}` : (max !== null ? `Max: ${max}` : ''));

        // Store for updater
        _tvRegistry[pageId].push({ key, safeId, min, max });

        tbody.innerHTML += `
        <tr class="hover:bg-white/5 transition-colors text-white" data-target-key="${key}">
            <td class="p-1.5 align-middle overflow-hidden text-white">
                <div class="flex items-center gap-1.5 w-full">
                    <button onclick="Actions.${trendAction}('${key}')"
                        id="op-trend-btn-${pageId}-tgt-${safeId}"
                        class="text-gray-500 hover:text-[#ebf552] transition-colors focus:outline-none shrink-0">
                        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"
                            fill="none" stroke="currentColor" stroke-width="2"
                            stroke-linecap="round" stroke-linejoin="round">
                            <path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>
                        </svg>
                    </button>
                    <span class="truncate flex-1 min-w-0 font-bold text-white text-[12px]" title="${key}">${label}</span>
                </div>
            </td>
            <td class="p-1.5 font-mono font-bold text-right truncate align-middle text-white" id="${currId}" title="${rangeStr}">
                <span id="${statusId}" class="font-mono font-bold px-1 rounded text-white text-[12px]">---</span>
            </td>
            <td class="p-1.5 font-mono font-bold text-right truncate align-middle text-white text-[12px]" id="${nudgeId}">
                <span class="text-white">-</span>
            </td>
            <td class="p-1.5 font-mono font-bold text-right truncate align-middle text-white pr-2 text-[12px]" id="${tgtId}">
                <span class="text-white">---</span>
            </td>
        </tr>`;
    });
}

/**
 * updateTargetVariables — called on every live_values socket event.
 * Updates the Curr cell with colour coding vs min/max range.
 *
 * @param {object} data   - flat live values dict { tag: value }
 * @param {string} pageId - same pageId passed to initTargetVariables
 */
export function updateTargetVariables(data, pageId) {
    const reg = _tvRegistry[pageId];
    if (!reg) return;

    reg.forEach(({ key, safeId, min, max }) => {
        const statusEl = document.getElementById(`op-tgt-status-${pageId}-${safeId}`);
        if (!statusEl) return;

        const rawVal = data[key];
        if (rawVal === undefined || rawVal === null || rawVal === '') {
            statusEl.textContent = '---';
            statusEl.className   = 'font-mono font-bold px-1 rounded text-gray-300 text-[10px]';
            return;
        }

        const val = parseFloat(rawVal);
        if (isNaN(val)) {
            statusEl.textContent = '---';
            statusEl.className   = 'font-mono font-bold px-1 rounded text-gray-300 text-[10px]';
            return;
        }

        const decimals = (val > 999) ? 0 : (val > 99 ? 1 : 2);
        statusEl.textContent = val.toFixed(decimals);

        // Colour coding: matches Live Sensors panel scale
        // red = out of range, yellow = near limit (within 10%), white capsule = in range
        if (min !== null && max !== null) {
            const range  = max - min;
            const buffer = range * 0.10;
            if (val < min || val > max) {
                statusEl.className = 'font-mono font-bold px-1 rounded text-white bg-red-600 text-[12px]';
            } else if (val < (min + buffer) || val > (max - buffer)) {
                statusEl.className = 'font-mono font-bold px-1 rounded text-black bg-yellow-900 text-[12px]';
            } else {
                statusEl.className = 'font-mono font-bold px-1 rounded text-slate-800 bg-slate-100 text-[12px]';
            }
        } else {
            statusEl.className = 'font-mono font-bold px-1 rounded text-white text-[12px]';
        }

        // Update Target column with the dynamic SP tag value from data if available
        const tgtEl = document.getElementById(`op-tgt-tgt-${pageId}-${safeId}`);
        if (tgtEl) {
            const varConf = state.currentModelConfig?.calculated_variables?.[key] || state.currentModelConfig?.control_variables?.[key];
            if (varConf && varConf.dynamic_sp_tag) {
                const spTag = varConf.dynamic_sp_tag;
                if (data[spTag] !== undefined && data[spTag] !== null && data[spTag] !== '') {
                    const spVal = parseFloat(data[spTag]);
                    if (!isNaN(spVal)) {
                        const decimals = spVal > 999 ? 0 : spVal > 99 ? 1 : 2;
                        tgtEl.innerHTML = `<span class="text-white font-black">${spVal.toFixed(decimals)}</span>`;
                    } else {
                        tgtEl.innerHTML = `<span class="text-gray-500">---</span>`;
                    }
                } else {
                    tgtEl.innerHTML = `<span class="text-gray-500">---</span>`;
                }
            } else {
                tgtEl.innerHTML = `<span class="text-gray-500">---</span>`;
            }
        }
    });
}

/**
 * updateTargetVariablesActions — called on every autopilot_update event.
 * Fills the Nudge (▲/▼ next step) and Target (final goal) cells
 * for any target variable that appears in actions[].var_name.
 *
 * @param {object} data   - autopilot_update payload
 * @param {string} pageId - 'kiln' | 'preheater' | 'cooler'
 */
export function updateTargetVariablesActions(data, pageId) {
    const reg = _tvRegistry[pageId];
    if (!reg || !data) return;

    // Build a quick lookup from var_name → action
    const actionMap = {};
    if (data.actions && data.actions.length > 0) {
        data.actions.forEach(act => { actionMap[act.var_name] = act; });
    }

    reg.forEach(({ key, safeId }) => {
        const nudgeEl = document.getElementById(`op-tgt-nudge-${pageId}-${safeId}`);
        const tgtEl   = document.getElementById(`op-tgt-tgt-${pageId}-${safeId}`);
        if (!nudgeEl && !tgtEl) return;

        const act = actionMap[key];
        if (!act) {
            // No action for this target — clear cells
            if (nudgeEl) nudgeEl.innerHTML = `<span class="text-gray-500">-</span>`;
            if (tgtEl)   tgtEl.innerHTML   = `<span class="text-gray-500">---</span>`;
            return;
        }

        const finalTarget  = parseFloat(act.fingerprint_set_point || 0);
        const liveCurr     = parseFloat(act.current_setpoint || 0);
        const backendNudge = act.nudge_target !== undefined ? parseFloat(act.nudge_target) : null;
        const nudgedTarget = backendNudge !== null ? backendNudge : finalTarget;
        const nudgeDiff    = nudgedTarget - liveCurr;

        const varConf = state.currentModelConfig?.calculated_variables?.[key] || state.currentModelConfig?.control_variables?.[key];
        let displayedTarget = finalTarget;
        let targetIsValid = true;
        if (varConf && varConf.dynamic_sp_tag) {
            const spTag = varConf.dynamic_sp_tag;
            if (state.latestLiveValues && state.latestLiveValues[spTag] !== undefined && state.latestLiveValues[spTag] !== null && state.latestLiveValues[spTag] !== '') {
                const spVal = parseFloat(state.latestLiveValues[spTag]);
                if (!isNaN(spVal)) {
                    displayedTarget = spVal;
                } else {
                    targetIsValid = false;
                }
            } else {
                targetIsValid = false;
            }
        } else {
            targetIsValid = false;
        }

        const decimals     = displayedTarget > 999 ? 0 : displayedTarget > 99 ? 1 : 2;

        if (nudgeEl) {
            if (Math.abs(nudgeDiff) > 0.001 && targetIsValid) {
                if (nudgeDiff > 0) {
                    nudgeEl.innerHTML = `<span class="text-blue-400 font-bold">▲ ${nudgedTarget.toFixed(decimals)}</span>`;
                } else {
                    nudgeEl.innerHTML = `<span class="text-gray-400 font-bold">▼ ${nudgedTarget.toFixed(decimals)}</span>`;
                }
            } else {
                nudgeEl.innerHTML = `<span class="text-white">-</span>`;
            }
        }

        if (tgtEl) {
            if (targetIsValid) {
                tgtEl.innerHTML = `<span class="text-white font-black">${displayedTarget.toFixed(decimals)}</span>`;
            } else {
                tgtEl.innerHTML = `<span class="text-gray-500">---</span>`;
            }
        }
    });
}
