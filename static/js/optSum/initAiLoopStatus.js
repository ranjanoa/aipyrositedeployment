/**
 * initAiLoopStatus.js
 * ──────────────────────────────────────────────────────────────────────────
 * Two responsibilities:
 *
 * 1. RIGHT PANEL — standalone AI Loop Status section
 *    Renders a compact list (above Live Sensors) with:
 *      • Traffic light dot  — from indicator_variables ending "AI Bit"
 *                             (1 = green pulse = AI ON,  0 = red = AI OFF)
 *      • Run hours badge    — from indicator_variables ending "AI RH"
 *
 * 2. CV TABLE — inline AI indicator injected into each Control Variable row
 *    The last column ("AI") of each CV row holds:
 *      • A traffic light dot  (op-cv-ai-bit-<pageId>-<safeCvTag>)
 *      • A run-hours span     (op-cv-ai-rh-<pageId>-<safeCvTag>)
 *    Mapping is established at init time via injectCvAiCells().
 *
 * Page filtering uses the same keyword-match approach throughout.
 */

import { state } from "../inits/state.js";

// ── bit/RH mapping for setpoint variables ──────────────────────────────────
export const CV_AI_MAPPING = {
    "Kiln feed": { bitTag: "Kiln feed AI Status", rhTag: "Kiln feed AI RH" },
    "Kiln filling degree (%) SP": { bitTag: "Kiln filling degree AI Status", rhTag: "Kiln Filling degree AI RH" },
    "Kiln speed": { bitTag: "Kiln speed AI Status", rhTag: "Kiln speed AI RH" },
    "Petcoke (Kiln)": { bitTag: "Petcoke (Kiln) AI Status", rhTag: "Petcoke (Kiln) AI RH" },
    "RDF (Kiln)": { bitTag: "RDF (Kiln) AI Status", rhTag: "RDF (Kiln) AI RH" },
    "RIP (Kiln)": { bitTag: "RIP (Kiln) AI Status", rhTag: "RIP (Kiln) AI RH" },
    "ID fan speed": { bitTag: "ID fan speed AI Status", rhTag: "ID fan speed AI RH" },
    "Petcoke (PC)": { bitTag: "Petcoke (PC) AI Status", rhTag: "Petcoke (PC) AI RH" },
    "RDF 1 (PC)": { bitTag: "RDF 1 (PC) AI Status", rhTag: "RDF 1 (PC) AI RH" },
    "RDF 2 (PC)": { bitTag: "RDF 2 (PC) AI Status", rhTag: "RDF 2 (PC) AI RH" },
    "Tert air damper": { bitTag: "Tert air damper AI Status", rhTag: "Tertiary air damper position AI RH" },
    "Tertiary air damper position": { bitTag: "Tert air damper AI Status", rhTag: "Tertiary air damper position AI RH" },
    "Dividing gate": { bitTag: "Dividing gate AI Status", rhTag: "Dividing gate position AI RH" },
    "Dividing gate position": { bitTag: "Dividing gate AI Status", rhTag: "Dividing gate position AI RH" },
    "Quench fan speed": { bitTag: "Quench fan speed AI Status", rhTag: "Quenching fan speed SP AI RH" },
    "Quenching fan speed SP": { bitTag: "Quench fan speed AI Status", rhTag: "Quenching fan speed SP AI RH" },
    "Quench fan gas flow": { bitTag: "Quench fan speed AI Status", rhTag: "Quenching fan speed SP AI RH" },
    "Cooler speed (central 2)": { bitTag: "Cooler speed (central 2) AI Status", rhTag: "Cooler grate speed (central 2) AI RH" },
    "Cooler speed (central 1)": { bitTag: "Cooler speed (central 1) AI Status", rhTag: "Cooler grate speed (central 1) AI RH" },
    "Cooler speed (right)": { bitTag: "Cooler speed (right) AI Status", rhTag: "Cooler grate speed (right) AI RH" },
    "Cooler speed (left)": { bitTag: "Cooler speed (left) AI Status", rhTag: "Cooler grate speed (left) AI RH" },
    "Cooler grate pressure (avg)": { bitTag: "Cooler grate P SP AI Status", rhTag: "Cooler grate pressure SP AI RH" },
    "Cooler grate P SP": { bitTag: "Cooler grate P SP AI Status", rhTag: "Cooler grate pressure SP AI RH" },
    "Cooler BF fan motor speed": { bitTag: "Cooler BF fan speed AI Status", rhTag: "Cooler bagfilter fan motor speed AI RH" },
    "Cooler BF fan speed": { bitTag: "Cooler BF fan speed AI Status", rhTag: "Cooler bagfilter fan motor speed AI RH" }
};

// ── CV STATUS UPDATER ───────────────────────────────────────────────────────
export function updateCvTableAiStatus(data, prefix) {
    if (!data) return;
    Object.keys(CV_AI_MAPPING).forEach(cvKey => {
        const safeId = cvKey.replace(/[^a-zA-Z0-9]/g, '');
        const dotEl = document.getElementById(`${prefix}ai-dot-${safeId}`);
        const rhEl = document.getElementById(`${prefix}rh-${safeId}`);

        const mapping = CV_AI_MAPPING[cvKey];

        // 1. Update AI Status Dot
        if (dotEl) {
            let active = false;
            if (mapping.bitTag && data[mapping.bitTag] !== undefined) {
                const val = parseFloat(data[mapping.bitTag]);
                active = !isNaN(val) && val >= 0.99;
            }
            if (active) {
                dotEl.className = "w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse shrink-0 border border-black/20";
                dotEl.title = "AI Status: ON";
            } else {
                dotEl.className = "w-2.5 h-2.5 rounded-full bg-red-500 shrink-0 border border-black/20";
                dotEl.title = "AI Status: OFF";
            }
        }

        // 2. Update Run Hours value
        if (rhEl) {
            if (mapping.rhTag) {
                const rawRh = data[mapping.rhTag];
                if (rawRh !== undefined && rawRh !== null && rawRh !== '') {
                    rhEl.textContent = parseFloat(rawRh).toFixed(1);
                } else {
                    rhEl.textContent = '---';
                }
            } else {
                rhEl.textContent = '---';
            }
        }
    });
}

