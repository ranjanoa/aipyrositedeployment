import { state } from "../inits/state.js";
import { drawOpSummaryChart } from "./drawOpSummaryChart.js"
import { drawOpParallelChart } from "./drawOpParallelChart.js"
import { updateCvTableAiStatus } from "./initAiLoopStatus.js";

export function updateOpSummary(data) {
    const now = Date.now();

    if (state.currentModelConfig && state.currentModelConfig.kpi_tags) {
        Object.keys(state.currentModelConfig.kpi_tags).forEach(kpiName => {
            const tagInfo = state.currentModelConfig.kpi_tags[kpiName];
            const tag = state.currentModelConfig.kpi_tags[kpiName].tag;
            if (data[tag] !== undefined) {
                const el = document.getElementById(`op3-kpi-${tag.replace(/[^a-zA-Z0-9]/g, '')}`);
                if (el) {
                    el.innerText = parseFloat(data[tag]).toFixed(1);
                    const val = parseFloat(data[tag]).toFixed(1);

                    const min = tagInfo?.default_min;
                    const max = tagInfo?.default_max;

                    if (min !== undefined && max !== undefined) {
                          const range = max - min;
                            const buffer = range * 0.1;
                        el.classList.remove('text-white');
                        if (val < min || val > max) {
                            el.classList.add('text-red-500');
                        }

                        else if (val < (min + buffer) || val > (max - buffer)) {
                            el.classList.add('text-yellow-600');
                        }
                        else {
                            el.classList.add('text-white');   // NORMAL
                          
                        }
                    }
                }
            }
        });
    }

    Object.keys(data).forEach(tag => {
        if (tag.includes('timestamp')) return;

        const safeId = tag.replace(/[^a-zA-Z0-9]/g, '');
        const val = parseFloat(data[tag]).toFixed(2);

        const curEl = document.getElementById(`op3-cur-${safeId}`);
        if (curEl) {
            if (tag.startsWith("TRG -")) {
                const item = state.currentModelConfig?.calculated_variables?.[tag] ||
                             state.currentModelConfig?.control_variables?.[tag] ||
                             state.currentModelConfig?.indicator_variables?.[tag];
                const valNum = parseFloat(data[tag]);
                if (item && !isNaN(valNum) && item.default_min !== undefined && item.default_max !== undefined) {
                    const min = parseFloat(item.default_min);
                    const max = parseFloat(item.default_max);
                    const range = max - min;
                    const buffer = range * 0.10;
                    if (valNum < min || valNum > max) {
                        curEl.innerHTML = `<span class="font-mono font-bold px-1 rounded text-white bg-red-600 text-[12px]">${val}</span>`;
                    } else if (valNum < (min + buffer) || valNum > (max - buffer)) {
                        curEl.innerHTML = `<span class="font-mono font-bold px-1 rounded text-black bg-yellow-900 text-[12px]">${val}</span>`;
                    } else {
                        curEl.innerHTML = `<span class="font-mono font-bold px-1 rounded text-slate-800 bg-slate-100 text-[12px]">${val}</span>`;
                    }
                } else {
                    curEl.innerText = val;
                }
            } else {
                curEl.innerText = val;
            }
        }

        //  const liveEl = document.getElementById(`op3-live-${safeId}`);
        // if (liveEl) liveEl.innerText = val;

        if (!state.opHistoryData[tag]) {
            state.opHistoryData[tag] = [];
        }

        state.opHistoryData[tag].push({ ts: now, val: parseFloat(data[tag]) });
        state.opHistoryData[tag] = state.opHistoryData[tag].filter(pt => (now - pt.ts) <= 45 * 60000); // 45 min buffer
    });

    drawOpSummaryChart();
    drawOpParallelChart();
    updateCvTableAiStatus(data, 'op3-');
}
