import { state } from "../../inits/state.js";
export function drawOpSummaryChartPreheater() {
    if (!state.charts.opSummaryPreheaterChartCanvas) return;

            const now = Date.now();
            const colors = ['#ebf552', '#3b82f6', '#10b981', '#f97316', '#a855f7', '#ec4899', '#ffffff', '#22d3ee'];
            const datasets = [];

            // STRICTLY ONLY variables manually selected by the user
            const varsToPlot = [...state.opActiveTrendsPreheater];
            const minX = state.historyRange !== undefined ? parseFloat(state.historyRange) : -40;
            const scales = {
                x: {
                    type: 'linear',
                    min: minX,
                    max: 10,
                    ticks: {
                        stepSize: 10,
                        color: '#aabdc4',
                        callback: function (val) { return val + 'm'; }
                    },
                    grid: { color: '#2d4a54' }
                },
                y: { display: false }
            };

            varsToPlot.slice(0, 8).forEach((tag, idx) => {
                const color = colors[idx % colors.length];
                const yAxisId = `y-${tag.replace(/[^a-zA-Z0-9]/g, '')}`;

                // Add dynamic scale for this variable
                scales[yAxisId] = {
                    display: idx === 0, // Show first axis as reference
                    position: 'left',
                    grid: { display: idx === 0, color: '#2d4a54' },
                    ticks: { color: '#aabdc4' }
                };

                let histData = [];
                if (state.opHistoryDataKiln[tag]) {
                    histData = state.opHistoryDataKiln[tag].map(pt => ({
                        x: -((now - pt.ts) / 60000),
                        y: pt.val
                    })).filter(pt => pt.x >= minX);
                }

                datasets.push({
                    label: tag + ' (Real)',
                    data: histData,
                    borderColor: color,
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.1,
                    yAxisID: yAxisId
                });

                const isControl = state.currentModelConfig.control_variables && state.currentModelConfig.control_variables[tag];
                const liveCurr = state.latestLiveValues[tag] !== undefined ?
                    parseFloat(state.latestLiveValues[tag]) :
                    (histData.length > 0 ? histData[histData.length - 1].y : 0);

                if (isControl) {
                    const action = (window.latestActions || []).find(a => a.var_name === tag);
                    const varConf = state.currentModelConfig.control_variables[tag];
                    const finalTarget = action ? parseFloat(action.fingerprint_set_point || 0) : liveCurr;
                    const gain = varConf ? (Math.abs(parseFloat(varConf.nudge_speed)) || 0.15) : 0.15;
                    const defMax = varConf ? parseFloat(varConf.default_max || 9999) : 9999;
                    const defMin = varConf ? parseFloat(varConf.default_min || -9999) : -9999;
                    const span = Math.abs(defMax - defMin);
                    const minPush = span < 10000 ? (span * 0.05) : 0.1;

                    // Simulate Nudge Trend (Nudge Curve) step-by-step as per settings
                    let nudgeVal = liveCurr;
                    const nudgeTrend = [{ x: 0, y: nudgeVal }];
                    for (let m = 1; m <= 10; m++) {
                        const gap = finalTarget - nudgeVal;
                        if (Math.abs(gap) > 0.001) {
                            const moveRequest = Math.max(Math.abs(gap * gain), minPush);
                            nudgeVal = nudgeVal + Math.sign(gap) * Math.min(moveRequest, Math.abs(gap));
                        } else {
                            nudgeVal = finalTarget;
                        }
                        nudgeTrend.push({ x: m, y: nudgeVal });
                    }

                    datasets.push({
                        label: tag + ' (Target)',
                        data: nudgeTrend,
                        borderColor: color,
                        borderWidth: 2,
                        borderDash: [4, 4],
                        pointRadius: 0,
                        tension: 0.1,
                        yAxisID: yAxisId
                    });
                } else {
                    let predDataRaw = state.opPredictionData[tag];
                    if (!predDataRaw || predDataRaw.length === 0) {
                        predDataRaw = Array(11).fill(liveCurr);
                    }

                    let predData = predDataRaw.map((val, minFromNow) => ({
                        x: minFromNow,
                        y: val
                    })).filter(pt => pt.x <= 10);

                    if (histData.length > 0) {
                        predData.unshift({ x: 0, y: histData[histData.length - 1].y });
                    }

                    datasets.push({
                        label: tag + ' (Pred)',
                        data: predData,
                        borderColor: color,
                        borderWidth: 2,
                        borderDash: [4, 4],
                        pointRadius: 0,
                        tension: 0.1,
                        yAxisID: yAxisId
                    });
                }
            });

            state.charts.opSummaryPreheaterChartCanvas.options.scales = scales;
            state.charts.opSummaryPreheaterChartCanvas.data.datasets = datasets;
            state.charts.opSummaryPreheaterChartCanvas.update('none');

}
