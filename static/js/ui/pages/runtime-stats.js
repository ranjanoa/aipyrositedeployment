// Runtime Analytics page module
import { state } from "../../inits/state.js";

// --- Persistent background state ---
// The refresh interval is NEVER destroyed on tab switch.
// Results are cached so the tab renders instantly on re-entry.
let refreshInterval = null;
let currentWindowMinutes = 60;
let _cachedData = null;         // Last successful API response
let _isTabVisible = false;      // Whether the analytics tab is currently shown
let _pendingRender = false;     // True if new data arrived while tab was hidden

export function RuntimeStats() {
    const container = document.createElement("div");
    container.className = "runtime-stats-container hidden h-full grid-cols-12 gap-4 transition-grid overflow-hidden relative p-4";
    container.id = "panel-runtime-stats";

    container.innerHTML = `
        <div class="col-span-12 flex flex-col gap-4 h-full overflow-hidden">
            <!-- Header section with controls -->
            <div class="glass-panel shrink-0 p-4 bg-[#1a3842] border border-[#2d4a54] flex flex-row justify-between items-center rounded-lg shadow-lg">
                <div class="flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ebf552" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="18" y1="20" x2="18" y2="10"/>
                        <line x1="12" y1="20" x2="12" y2="4"/>
                        <line x1="6" y1="20" x2="6" y2="14"/>
                    </svg>
                    <div>
                        <h1 class="text-white text-base font-black uppercase tracking-wider">Runtime Analytics</h1>
                        <p class="text-gray-400 text-xs mt-0.5">Real-time statistics & loop engagement analysis</p>
                    </div>
                </div>
                
                <div class="flex items-center gap-3">
                    <div class="flex items-center gap-2">
                        <span class="text-xs font-bold text-gray-300 uppercase tracking-wider">Analysis Window:</span>
                        <select id="stats-window-select" onchange="window.RuntimeStatsActions.changeWindow(this.value)"
                            onclick="if(this.value.startsWith('custom')) { const container = document.getElementById('custom-range-container'); if(container) { container.classList.remove('hidden'); container.classList.add('flex'); } }"
                            class="text-xs bg-[#152e36] text-white border border-[#2d4a54] rounded-md px-2.5 py-1.5 outline-none font-bold cursor-pointer hover:border-white/20 transition-colors">
                            <option value="30" class="bg-[#152e36] text-white">Last 30 Minutes</option>
                            <option value="60" selected class="bg-[#152e36] text-white">Last 1 Hour</option>
                            <option value="240" class="bg-[#152e36] text-white">Last 4 Hours</option>
                            <option value="480" class="bg-[#152e36] text-white">Last 8 Hours</option>
                            <option value="1440" class="bg-[#152e36] text-white">Last 24 Hours</option>
                            <option value="custom" class="bg-[#152e36] text-white">Custom Range...</option>
                        </select>
                    </div>

                    <!-- Custom Datepicker Container (hidden by default) -->
                    <div id="custom-range-container" class="hidden items-center gap-2 bg-[#152e36]/80 border border-[#2d4a54] p-1 px-2.5 rounded-md transition-all duration-300">
                        <span class="text-[10px] text-gray-400 font-bold uppercase">From:</span>
                        <input type="datetime-local" id="custom-start-time" 
                            class="text-xs bg-[#122a33] text-white border border-[#2d4a54] rounded px-2 py-1 outline-none cursor-pointer">
                        <span class="text-[10px] text-gray-400 font-bold uppercase">To:</span>
                        <input type="datetime-local" id="custom-end-time" 
                            class="text-xs bg-[#122a33] text-white border border-[#2d4a54] rounded px-2 py-1 outline-none cursor-pointer">
                        <button onclick="window.RuntimeStatsActions.applyCustomRange()"
                            class="text-[10px] font-black px-3 py-1.5 bg-[#ebf552] text-slate-900 rounded-md hover:scale-105 active:scale-95 transition-all duration-150 cursor-pointer shadow-md hover:brightness-110 active:brightness-90 uppercase tracking-wider font-bold">
                            APPLY
                        </button>
                    </div>

                    <button onclick="window.RuntimeStatsActions.refreshData(true)"
                        class="text-xs font-bold px-3 py-1.5 bg-[#ebf552] text-slate-900 rounded-md hover:brightness-110 transition-colors flex items-center gap-1.5 cursor-pointer">
                        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="animate-spin-hover">
                            <path d="M23 4v6h-6M1 20v-6h6"/>
                            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                        </svg>
                        REFRESH
                    </button>
                </div>
            </div>

            <!-- Main stats container -->
            <div class="flex-1 flex gap-4 min-h-0 overflow-hidden">
                <!-- Left panel: Detailed mappings table -->
                <div class="flex-1 glass-panel border border-[#2d4a54] bg-[#1a3842] flex flex-col min-w-0 rounded-lg overflow-hidden">
                    <div class="p-3 bg-[#152e36] border-b border-[#2d4a54] flex justify-between items-center shrink-0">
                        <span class="text-xs font-bold text-white uppercase tracking-wider">Control Variable Performance Metrics</span>
                        <div class="flex items-center gap-2">
                            <span id="stats-loading-indicator" class="hidden text-[10px] text-[#ebf552] font-bold flex items-center gap-1">
                                <svg class="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                </svg>
                                UPDATING...
                            </span>
                            <span id="stats-status-info" class="text-[10px] text-gray-400 font-mono">Last updated: --:--:--</span>
                        </div>
                    </div>
                    
                    <div class="flex-1 overflow-y-auto">
                        <table class="w-full text-xs text-left table-fixed">
                            <thead class="text-gray-400 border-b border-[#2d4a54] bg-[#152e36]/50 sticky top-0 backdrop-blur z-10">
                                <tr>
                                    <th class="p-2.5 font-bold w-[30%] pl-4">Variable</th>
                                    <th class="p-2.5 font-bold text-center w-[15%]">AI Status</th>
                                    <th class="p-2.5 font-bold text-right w-[15%]">Current RH (PLC)</th>
                                    <th class="p-2.5 font-bold text-right w-[15%]">RH Delta (Window)</th>
                                    <th class="p-2.5 font-bold w-[25%] pr-4 pl-6">Engagement Ratio</th>
                                </tr>
                            </thead>
                            <tbody id="runtime-stats-table-body" class="divide-y divide-[#2d4a54]/50">
                                <tr>
                                    <td colspan="5" class="p-6 text-center text-gray-500 italic">Loading statistics...</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Right panel: Quick Insights & Summary Card -->
                <div class="w-[300px] shrink-0 flex flex-col gap-4 overflow-hidden h-full">


                    <!-- Guidance Card -->
                    <div class="flex-1 glass-panel border border-[#2d4a54] bg-[#1a3842] p-4 rounded-lg flex flex-col overflow-hidden shadow-lg">
                        <span class="text-[10px] font-black text-gray-400 uppercase tracking-widest shrink-0">Operator Guide</span>
                        <h3 class="text-white text-xs font-bold mt-1 shrink-0">Understanding Metrics</h3>
                        
                        <div class="flex-1 overflow-y-auto mt-3 pr-1 text-xs text-gray-300 flex flex-col gap-3.5 custom-scrollbar">
                            <div>
                                <span class="text-[#ebf552] font-bold block mb-1">AI Indication:</span>
                                <p class="text-gray-400 leading-normal text-[11px]">Displays the real-time status of the loop controller. When green (Active), the AI system is currently managing setpoint writes.</p>
                            </div>
                            <div>
                                <span class="text-[#ebf552] font-bold block mb-1">PLC RH Totaliser:</span>
                                <p class="text-gray-400 leading-normal text-[11px]">The absolute runtime accumulator stored in the PLC for that specific control loop.</p>
                            </div>
                            <div>
                                <span class="text-[#ebf552] font-bold block mb-1">RH Delta (Window):</span>
                                <p class="text-gray-400 leading-normal text-[11px]">The exact hours/minutes that the AI system was active during the selected analysis window (computed as current RH minus value at the start of the window).</p>
                            </div>
                            <div>
                                <span class="text-[#ebf552] font-bold block mb-1">Engagement Ratio:</span>
                                <p class="text-gray-400 leading-normal text-[11px]">Percentage of time the loop was under AI control within the window. A higher ratio indicates more automated control and less operator manual overrides.</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    return container;
}

// Global actions for page interaction
window.RuntimeStatsActions = {
    changeWindow(value) {
        const customContainer = document.getElementById("custom-range-container");
        if (value.startsWith("custom")) {
            if (customContainer) {
                customContainer.classList.remove("hidden");
                customContainer.classList.add("flex");
                
                // Initialize default range (yesterday to now)
                const startInput = document.getElementById("custom-start-time");
                const endInput = document.getElementById("custom-end-time");
                if (startInput && endInput && !startInput.value) {
                    const now = new Date();
                    const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
                    
                    const formatLocalISO = (d) => {
                        const pad = (n) => String(n).padStart(2, '0');
                        return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
                    };
                    
                    startInput.value = formatLocalISO(yesterday);
                    endInput.value = formatLocalISO(now);
                }
            }
        } else {
            if (customContainer) {
                customContainer.classList.add("hidden");
                customContainer.classList.remove("flex");
            }
            
            // Reset custom option text when switching away
            const statsSelect = document.getElementById("stats-window-select");
            if (statsSelect) {
                const customOption = Array.from(statsSelect.options).find(opt => opt.value === "custom");
                if (customOption) {
                    customOption.text = "Custom Range...";
                    customOption.value = "custom";
                }
            }
            
            currentWindowMinutes = parseInt(value);
            this.refreshData(true);
        }
    },

    applyCustomRange() {
        const startInput = document.getElementById("custom-start-time");
        const endInput = document.getElementById("custom-end-time");
        const statsSelect = document.getElementById("stats-window-select");
        
        if (startInput && endInput && startInput.value && endInput.value && statsSelect) {
            try {
                const startD = new Date(startInput.value);
                const endD = new Date(endInput.value);
                
                const formatShort = (d) => {
                    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
                    const pad = (n) => String(n).padStart(2, '0');
                    return `${d.getDate()} ${months[d.getMonth()]} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
                };
                
                // Update option text dynamically to show range and select it
                const customOption = Array.from(statsSelect.options).find(opt => opt.value.startsWith("custom"));
                if (customOption) {
                    customOption.text = `Custom: ${formatShort(startD)} - ${formatShort(endD)}`;
                    customOption.value = `custom_${startD.getTime()}_${endD.getTime()}`; // unique value to preserve change events
                    statsSelect.value = customOption.value; // Explicitly select the new custom range value
                }
                
                // Hide custom inputs container (close calendar window)
                const customContainer = document.getElementById("custom-range-container");
                if (customContainer) {
                    customContainer.classList.add("hidden");
                    customContainer.classList.remove("flex");
                }
            } catch(e) {
                console.error("Error setting custom option labels:", e);
            }
        }
        this.refreshData(true);
    },

    refreshData(showLoader = false) {
        const tableBody = document.getElementById("runtime-stats-table-body");
        const loadingIndicator = document.getElementById("stats-loading-indicator");

        if (loadingIndicator) {
            loadingIndicator.classList.remove("hidden");
        }

        // If tab is visible and no cache yet, show a spinner
        if (_isTabVisible && tableBody && (showLoader || tableBody.innerHTML.includes("Loading statistics"))) {
            // Only show spinner if we have no cached data to show
            if (!_cachedData) {
                tableBody.innerHTML = `
                    <tr>
                        <td colspan="5" class="p-8 text-center text-gray-400 font-bold">
                            <div class="flex items-center justify-center gap-2">
                                <svg class="animate-spin h-4 w-4 text-[#ebf552]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                </svg>
                                Fetching runtime statistics...
                            </div>
                        </td>
                    </tr>
                `;
            }
        }

        let url = `/api/runtime-stats?window_minutes=${currentWindowMinutes}`;
        
        const statsSelect = document.getElementById("stats-window-select");
        if (statsSelect && statsSelect.value.startsWith("custom")) {
            const startInput = document.getElementById("custom-start-time");
            const endInput = document.getElementById("custom-end-time");
            if (startInput && endInput && startInput.value && endInput.value) {
                try {
                    const startStr = new Date(startInput.value).toISOString();
                    const endStr = new Date(endInput.value).toISOString();
                    url = `/api/runtime-stats?start_time=${encodeURIComponent(startStr)}&end_time=${encodeURIComponent(endStr)}`;
                } catch(e) {
                    console.error("Error formatting datetimes:", e);
                }
            }
        }

        fetch(url)
            .then(res => res.json())
            .then(data => {
                if (loadingIndicator) {
                    loadingIndicator.classList.add("hidden");
                }
                if (data.status === "success") {
                    // Always cache the latest successful result
                    _cachedData = data;
                    _pendingRender = true;

                    if (_isTabVisible) {
                        // Tab is open — render immediately
                        this.renderStats(data);
                        _pendingRender = false;
                    }
                    // If tab is hidden, data sits in cache until wakeRuntimeStats() is called
                } else {
                    if (_isTabVisible && tableBody) {
                        tableBody.innerHTML = `<tr><td colspan="5" class="p-6 text-center text-red-500 font-bold">Failed to load statistics: ${data.error || 'Unknown Error'}</td></tr>`;
                    }
                }
            })
            .catch(err => {
                if (loadingIndicator) {
                    loadingIndicator.classList.add("hidden");
                }
                console.error("Error fetching stats:", err);
                if (_isTabVisible && tableBody) {
                    tableBody.innerHTML = `<tr><td colspan="5" class="p-6 text-center text-red-500 font-bold">Network error while fetching statistics.</td></tr>`;
                }
            });
    },

    renderStats(data) {
        const tableBody = document.getElementById("runtime-stats-table-body");
        if (!tableBody) return;

        const timeStr = new Date().toLocaleTimeString([], { hour12: false });
        const updateInfo = document.getElementById("stats-status-info");
        if (updateInfo) {
            updateInfo.innerText = `Last updated: ${timeStr}`;
        }

        const stats = data.statistics || [];
        if (stats.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="5" class="p-6 text-center text-gray-400 italic">No loop performance statistics available.</td></tr>`;
            return;
        }

        // 2. Render Variable Rows
        let html = '';
        stats.forEach(stat => {
            const isEngaged = stat.current_status > 0.5;
            const util = stat.utilization_pct || 0;
            
            // Choose color based on engagement percentage
            let barColor = 'bg-red-500';
            if (util > 90) barColor = 'bg-[#00FF66]';
            else if (util > 50) barColor = 'bg-orange-500';

            html += `
                <tr class="hover:bg-white/5 transition-colors">
                    <td class="p-3 pl-4 align-middle">
                        <div class="flex flex-col">
                            <span class="font-bold text-white text-[12px]">${stat.var_name}</span>
                            <span class="text-[10px] text-gray-400 mt-0.5">${stat.description}</span>
                        </div>
                    </td>
                    <td class="p-3 text-center align-middle">
                        <div class="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-[#122a33] border border-[#2d4a54]">
                            <span class="w-2 h-2 rounded-full ${isEngaged ? 'bg-[#00FF66] shadow-[0_0_4px_#00FF66]' : 'bg-red-500'}"></span>
                            <span class="text-[10px] ${isEngaged ? 'text-white' : 'text-gray-400'} font-bold uppercase leading-none">${isEngaged ? 'Active' : 'Inactive'}</span>
                        </div>
                    </td>
                    <td class="p-3 font-mono font-bold text-right text-gray-300 align-middle pr-4">
                        ${stat.current_rh !== "-" ? `${stat.current_rh} <span class="text-[9px] text-gray-500">h</span>` : '-'}
                    </td>
                    <td class="p-3 font-mono font-bold text-right text-white align-middle pr-4">
                        ${formatHours(stat.rh_delta)}
                    </td>
                    <td class="p-3 align-middle pr-4 pl-6">
                        <div class="flex items-center gap-3">
                            <div class="flex-1 h-2 bg-[#122a33] rounded-full overflow-hidden border border-[#2d4a54]">
                                <div class="h-full ${barColor} transition-all duration-500" style="width: ${util}%"></div>
                            </div>
                            <span class="font-mono font-bold text-white text-[11px] shrink-0 w-8 text-right">${util.toFixed(1)}%</span>
                        </div>
                    </td>
                </tr>
            `;
        });

        tableBody.innerHTML = html;
    }
};

function formatHours(hoursFloat) {
    if (hoursFloat === 0) return `<span class="text-gray-500">0m</span>`;
    const hours = Math.floor(hoursFloat);
    const mins = Math.round((hoursFloat - hours) * 60);
    
    let parts = [];
    if (hours > 0) parts.push(`${hours}h`);
    if (mins > 0 || hours === 0) parts.push(`${mins}m`);
    return parts.join(' ');
}

export function initRuntimeStats() {
    // Mark the tab as visible so fetches render immediately
    _isTabVisible = true;

    // If we already have cached data, render it instantly (no wait for network)
    if (_cachedData && _pendingRender) {
        window.RuntimeStatsActions.renderStats(_cachedData);
        _pendingRender = false;
    } else if (_cachedData) {
        // Render the cached data straight away so the page isn't empty
        window.RuntimeStatsActions.renderStats(_cachedData);
    }

    // Start the persistent background interval only once, ever
    if (!refreshInterval) {
        // Do an immediate fetch on first start
        window.RuntimeStatsActions.refreshData(true);
        refreshInterval = setInterval(() => {
            window.RuntimeStatsActions.refreshData(false);
        }, 10000);
    } else {
        // Interval already running in background — just trigger a fresh fetch
        // so the displayed data is up-to-date the moment the user sees the tab
        window.RuntimeStatsActions.refreshData(false);
    }
}

// wakeRuntimeStats is called when the tab becomes visible.
// It marks the tab as visible and flushes any pending cached render.
export function wakeRuntimeStats() {
    _isTabVisible = true;
    if (_cachedData && _pendingRender) {
        window.RuntimeStatsActions.renderStats(_cachedData);
        _pendingRender = false;
    } else if (_cachedData) {
        window.RuntimeStatsActions.renderStats(_cachedData);
    }
}

export function destroyRuntimeStats() {
    // Intentional no-op: the background interval is NEVER stopped on tab switch.
    // Data continues to refresh in the background so results are instant on re-entry.
    // The interval is only stopped if the page itself is unloaded.
    _isTabVisible = false;
}
