import { state } from "../inits/state.js";
import { drawOpSummaryChart } from "./drawOpSummaryChart.js";
import { drawOpSummaryChartKiln } from "./optSumkiln/drawOpSummaryChartKiln.js";
import { drawOpSummaryChartPreheater } from "./optSumPreheater/drawOpSummaryChartPreheater.js";
import { drawOpSummaryChartCooler } from "./optSumCooler/drawOpSummaryChartCooler.js";

export function updateHistoryRange(val) {
    state.historyRange = parseFloat(val);

    // Sync all dropdown elements to this new value
    document.querySelectorAll(".history-range-select").forEach(el => {
        el.value = val;
    });

    // Redraw all charts to reflect the new range
    drawOpSummaryChart();
    drawOpSummaryChartKiln();
    drawOpSummaryChartPreheater();
    drawOpSummaryChartCooler();
}
