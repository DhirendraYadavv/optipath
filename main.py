from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from neo4j import GraphDatabase
from pydantic import BaseModel

app = FastAPI(title="OptiPath - SGT CDOE Career Gap Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

URI = "neo4j+s://1a8ea85a.databases.neo4j.io"
AUTH = ("1a8ea85a", "UzFHMFFxC_nRMONZ2a55gCHB0CDWAx3jwosskGKVRA8")
driver = GraphDatabase.driver(URI, auth=AUTH)

# Synthetic ERP Data
MOCK_STUDENTS = {
    "SGT10023": {
        "name": "Aarav Sharma",
        "program": "MCA",
        "current_semester": 2,
        "completed_courses": ["Code-OL130102"],
    },
    "SGT10045": {
        "name": "Priya Nair",
        "program": "MCA",
        "current_semester": 3,
        "completed_courses": ["Code-OL130102", "Code-OL130202"],
    },
    "SGT10089": {
        "name": "Rohan Verma",
        "program": "MCA",
        "current_semester": 4,
        "completed_courses": [
            "Code-OL130102",
            "Code-OL130202",
            "Code-OL130221",
        ],
    },
}


class GapAnalysisRequest(BaseModel):
    target_role: str
    completed_courses: List[str]
    program: Optional[str] = "MCA"


@app.get("/auth/student-lookup/{roll_no}")
def student_lookup(roll_no: str):
    roll = roll_no.upper().strip()
    if roll not in MOCK_STUDENTS:
        raise HTTPException(
            status_code=404, detail="Student not found in synthetic ERP."
        )
    return {"roll_no": roll, **MOCK_STUDENTS[roll]}


@app.post("/graph/skill-gap")
def compute_skill_gap(payload: GapAnalysisRequest):
    query = """
    MATCH (jr:JobRole {name: $role})-[:REQUIRES]->(s:Skill)
    OPTIONAL MATCH (c:Course)-[t:TEACHES]->(s)
    WHERE toUpper(c.code) IN [code IN $completed | toUpper(code)]
    WITH s, max(coalesce(t.weight, 0.0)) AS confidence
    RETURN s.name AS skill, s.category AS category, confidence
    ORDER BY confidence DESC, s.name ASC
    """
    records, _, _ = driver.execute_query(
        query, role=payload.target_role, completed=payload.completed_courses
    )

    verified = []
    partial = []
    gap = []

    for r in records:
        item = {
            "skill": r["skill"],
            "category": r["category"],
            "confidence": round(r["confidence"], 2),
        }
        if r["confidence"] >= 0.75:
            verified.append(item)
        elif r["confidence"] > 0.0:
            partial.append(item)
        else:
            gap.append(item)

    total = len(records)
    readiness_pct = (
        round(
            (sum(r["confidence"] for r in records) / total) * 100
            if total > 0
            else 0,
            1,
        )
    )

    return {
        "role": payload.target_role,
        "readiness_percentage": readiness_pct,
        "total_required": total,
        "verified_skills": verified,
        "partial_skills": partial,
        "skill_gaps": gap,
    }


@app.post("/graph/timeline")
def compute_timeline_to_close(payload: GapAnalysisRequest):
    query = """
    MATCH (jr:JobRole {name: $role})-[:REQUIRES]->(s:Skill)
    OPTIONAL MATCH (c:Course)-[t:TEACHES]->(s)
    WHERE toUpper(c.code) IN [code IN $completed | toUpper(code)]
    WITH jr, s, max(coalesce(t.weight, 0.0)) AS current_conf
    WHERE current_conf < 0.75

    MATCH (p:Program)-[:HAS_SEMESTER]->(sem:Semester)-[:INCLUDES]->(future_course:Course)-[ft:TEACHES]->(s)
    WHERE toUpper(p.name) = toUpper($program)
    RETURN s.name AS missing_skill,
           sem.number AS closes_in_semester,
           future_course.code AS course_code,
           future_course.title AS course_title,
           ft.weight AS projected_confidence
    ORDER BY closes_in_semester ASC
    """
    records, _, _ = driver.execute_query(
        query,
        role=payload.target_role,
        completed=payload.completed_courses,
        program=payload.program,
    )

    timeline = {}
    for r in records:
        sem_num = r["closes_in_semester"]
        if sem_num not in timeline:
            timeline[sem_num] = []
        timeline[sem_num].append(
            {
                "skill": r["missing_skill"],
                "course": f"{r['course_code']} ({r['course_title']})",
                "projected_confidence": round(r["projected_confidence"], 2),
            }
        )

    return {
        "target_role": payload.target_role,
        "timeline_stages": [
            {"semester": k, "resolutions": v}
            for k, v in sorted(timeline.items())
        ],
    }


@app.get("/market/drift")
def get_market_drift(role: str = "AI & Data Scientist"):
    query = """
    MATCH (r23:RoleSnapshot {role: $role, year: 2023})-[:DEMANDED]->(s23:Skill)
    WITH collect(s23.name) AS skills_2023
    MATCH (r26:RoleSnapshot {role: $role, year: 2026})-[:DEMANDED]->(s26:Skill)
    WITH skills_2023, collect(s26.name) AS skills_2026

    RETURN skills_2023,
           skills_2026,
           [s IN skills_2026 WHERE NOT s IN skills_2023] AS emerging_skills,
           [s IN skills_2023 WHERE NOT s IN skills_2026] AS obsolete_skills
    """
    records, _, _ = driver.execute_query(query, role=role)
    if not records:
        raise HTTPException(
            status_code=404, detail="Drift data not found for role."
        )

    rec = records[0]
    emerging = rec["emerging_skills"]

    # Check whether SGT curriculum covers these emerging skills
    curriculum_check = """
    MATCH (s:Skill) WHERE s.name IN $emerging
    OPTIONAL MATCH (c:Course)-[t:TEACHES]->(s)
    RETURN s.name AS skill, count(c) > 0 AS taught_in_sgt
    """
    checks, _, _ = driver.execute_query(curriculum_check, emerging=emerging)

    drift_report = [
        {"skill": ch["skill"], "curriculum_status": "Covered in SGT" if ch["taught_in_sgt"] else "Curriculum Gap (Needs Syllabus Update)"}
        for ch in checks
    ]

    return {
        "role": role,
        "historical_year": 2023,
        "current_year": 2026,
        "emerging_skills": drift_report,
        "stable_skills": [s for s in rec["skills_2026"] if s in rec["skills_2023"]],
    }


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>OptiPath | SGT CDOE Career Engine</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
        <style>
            #network-canvas { height: 420px; width: 100%; border-radius: 0.75rem; background-color: #080e1e; }
        </style>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen font-sans p-6">
        <div class="max-w-6xl mx-auto space-y-6">
            <header class="border-b border-slate-800 pb-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div>
                    <h1 class="text-3xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-sky-400 via-indigo-300 to-emerald-400">OptiPath</h1>
                    <p class="text-sm text-slate-400">Curriculum-Grounded Career Gap Engine &bull; SGT CDOE</p>
                </div>
                <!-- Flow Selector Tabs -->
                <div class="flex gap-2 bg-slate-900 p-1 rounded-xl border border-slate-800 text-xs font-semibold">
                    <button id="tabFlowA" onclick="switchTab('A')" class="px-4 py-2 rounded-lg bg-sky-600 text-white transition">Flow A: Enrolled Student</button>
                    <button id="tabFlowB" onclick="switchTab('B')" class="px-4 py-2 rounded-lg text-slate-400 hover:text-white transition">Flow B: Prospective Pivot</button>
                    <button id="tabDrift" onclick="switchTab('drift')" class="px-4 py-2 rounded-lg text-slate-400 hover:text-white transition">Market Drift (Mechanic #3)</button>
                </div>
            </header>

            <!-- Flow A: Enrolled Student Section -->
            <div id="sectionFlowA" class="space-y-6">
                <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                        <label class="text-xs font-semibold uppercase tracking-wider text-slate-400 block mb-1">Target Job Role</label>
                        <select id="roleSelectA" class="w-full bg-slate-950 border border-slate-700 text-slate-100 rounded-lg p-2.5 text-sm">
                            <option value="AI & Data Scientist">AI & Data Scientist</option>
                            <option value="Full-Stack Developer">Full-Stack Developer</option>
                            <option value="Cloud Architect">Cloud Architect</option>
                        </select>
                    </div>
                    <div>
                        <label class="text-xs font-semibold uppercase tracking-wider text-slate-400 block mb-1">Synthetic ERP Lookup</label>
                        <div class="flex gap-2">
                            <input id="rollInput" type="text" placeholder="SGT10023, SGT10045..." value="SGT10023" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm uppercase">
                            <button onclick="lookupStudent()" class="bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-2 rounded-lg text-xs font-semibold">Lookup</button>
                        </div>
                    </div>
                    <div>
                        <label class="text-xs font-semibold uppercase tracking-wider text-slate-400 block mb-1">Completed Courses</label>
                        <input id="coursesInputA" type="text" value="Code-OL130102" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm">
                    </div>
                </div>
                <button onclick="runFlowA()" class="w-full bg-sky-600 hover:bg-sky-500 py-2.5 rounded-xl font-medium text-sm transition">Run Student Skill-Gap Analysis</button>
            </div>

            <!-- Flow B: Prospective Pivot Section -->
            <div id="sectionFlowB" class="hidden space-y-6">
                <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl flex flex-col md:flex-row items-center justify-between gap-4">
                    <div class="space-y-1">
                        <span class="text-xs font-semibold uppercase tracking-wider text-indigo-400">External Applicant Mode</span>
                        <h3 class="text-lg font-bold text-white">Prospective Student Skill Transformation</h3>
                        <p class="text-xs text-slate-400">Compare starting baseline with 0 formal credits against degree completion.</p>
                    </div>
                    <div class="flex items-center gap-3 bg-slate-950 p-2 rounded-xl border border-slate-800">
                        <span class="text-xs font-medium text-slate-300">Add SGT Online MCA</span>
                        <input type="checkbox" id="pivotToggle" onchange="runFlowB()" class="w-5 h-5 accent-emerald-500 cursor-pointer">
                    </div>
                </div>
            </div>

            <!-- Market Drift Section -->
            <div id="sectionDrift" class="hidden space-y-6">
                <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-4">
                    <div>
                        <span class="text-xs font-semibold uppercase tracking-wider text-amber-400">Curriculum Advisory Engine</span>
                        <h3 class="text-lg font-bold text-white">Market Drift Detector (2023 vs 2026 Snapshot Diff)</h3>
                        <p class="text-xs text-slate-400">Identifies skills newly demanded by industry and flags curriculum gaps for SGT syllabus committees.</p>
                    </div>
                    <button onclick="runDrift()" class="bg-amber-600 hover:bg-amber-500 px-5 py-2 rounded-lg text-xs font-semibold transition">Detect Curriculum Drift</button>
                    <div id="driftReport" class="space-y-2 text-sm pt-2"></div>
                </div>
            </div>

            <!-- Graph DAG Canvas & Readout -->
            <div id="mainVisuals" class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div class="lg:col-span-2 bg-slate-900 border border-slate-800 p-4 rounded-2xl space-y-3">
                    <div class="flex justify-between items-center px-1">
                        <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-300">Confidence-Weighted Graph DAG</h2>
                        <div class="flex gap-3 text-xs">
                            <span class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span> Verified (&ge;75%)</span>
                            <span class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-amber-500"></span> Partial</span>
                            <span class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-rose-500"></span> Gap</span>
                        </div>
                    </div>
                    <div id="network-canvas"></div>
                </div>

                <div class="space-y-4">
                    <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl">
                        <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Readiness Score</span>
                        <div class="mt-2 flex items-baseline gap-2">
                            <span id="readinessScore" class="text-4xl font-black text-sky-400">0%</span>
                            <span class="text-xs text-slate-400">market alignment</span>
                        </div>
                    </div>

                    <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-3">
                        <span class="text-xs font-semibold uppercase tracking-wider text-slate-400 block">Timeline-to-Close</span>
                        <div id="timelineOutput" class="space-y-2 text-xs text-slate-300 max-h-64 overflow-y-auto">
                            <p class="text-slate-500">Run an analysis to view semester breakdown.</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            let network = null;

            function switchTab(tab) {
                document.getElementById('sectionFlowA').classList.add('hidden');
                document.getElementById('sectionFlowB').classList.add('hidden');
                document.getElementById('sectionDrift').classList.add('hidden');

                document.getElementById('tabFlowA').className = 'px-4 py-2 rounded-lg text-slate-400 hover:text-white transition';
                document.getElementById('tabFlowB').className = 'px-4 py-2 rounded-lg text-slate-400 hover:text-white transition';
                document.getElementById('tabDrift').className = 'px-4 py-2 rounded-lg text-slate-400 hover:text-white transition';

                if (tab === 'A') {
                    document.getElementById('sectionFlowA').classList.remove('hidden');
                    document.getElementById('tabFlowA').className = 'px-4 py-2 rounded-lg bg-sky-600 text-white transition';
                    document.getElementById('mainVisuals').classList.remove('hidden');
                    runFlowA();
                } else if (tab === 'B') {
                    document.getElementById('sectionFlowB').classList.remove('hidden');
                    document.getElementById('tabFlowB').className = 'px-4 py-2 rounded-lg bg-indigo-600 text-white transition';
                    document.getElementById('mainVisuals').classList.remove('hidden');
                    runFlowB();
                } else if (tab === 'drift') {
                    document.getElementById('sectionDrift').classList.remove('hidden');
                    document.getElementById('tabDrift').className = 'px-4 py-2 rounded-lg bg-amber-600 text-white transition';
                    document.getElementById('mainVisuals').classList.add('hidden');
                    runDrift();
                }
            }

            async function lookupStudent() {
                const roll = document.getElementById('rollInput').value.trim();
                try {
                    const res = await fetch(`/auth/student-lookup/${roll}`);
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail);
                    document.getElementById('coursesInputA').value = data.completed_courses.join(', ');
                    runFlowA();
                } catch(e) {
                    alert(e.message);
                }
            }

            async function runFlowA() {
                const role = document.getElementById('roleSelectA').value;
                const coursesRaw = document.getElementById('coursesInputA').value;
                const completed = coursesRaw ? coursesRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
                await executeAnalysis(role, completed);
            }

            async function runFlowB() {
                const role = "AI & Data Scientist";
                const isEnrolled = document.getElementById('pivotToggle').checked;
                // If enrolled in MCA, simulate all core MCA courses completed
                const completed = isEnrolled ? ["Code-OL130102", "Code-OL130202", "Code-OL130221"] : [];
                await executeAnalysis(role, completed);
            }

            async function executeAnalysis(role, completed) {
                try {
                    const gapRes = await fetch('/graph/skill-gap', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ target_role: role, completed_courses: completed })
                    });
                    const gapData = await gapRes.json();
                    document.getElementById('readinessScore').innerText = `${gapData.readiness_percentage}%`;

                    const timelineRes = await fetch('/graph/timeline', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ target_role: role, completed_courses: completed })
                    });
                    const timelineData = await timelineRes.json();
                    renderTimeline(timelineData.timeline_stages);
                    renderGraph(role, gapData);
                } catch(e) {
                    console.error(e);
                }
            }

            async function runDrift() {
                const report = document.getElementById('driftReport');
                report.innerHTML = '<p class="text-slate-400">Diffing 2023 vs 2026 role snapshots in Neo4j...</p>';
                try {
                    const res = await fetch('/market/drift?role=AI%20%26%20Data%20Scientist');
                    const d = await res.json();
                    report.innerHTML = `
                        <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-3">
                            <div class="text-xs font-semibold text-slate-300">Emerging Industry Requirements (Since 2023):</div>
                            <div class="space-y-2">
                                ${d.emerging_skills.map(s => `
                                    <div class="flex justify-between items-center p-2 rounded bg-slate-900 border border-slate-800">
                                        <span class="font-medium text-amber-300">${s.skill}</span>
                                        <span class="text-xs px-2 py-0.5 rounded ${s.curriculum_status.includes('Covered') ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/10 text-rose-400 border border-rose-500/30'}">${s.curriculum_status}</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    `;
                } catch(e) {
                    report.innerHTML = `<p class="text-rose-400">${e.message}</p>`;
                }
            }

            function renderTimeline(stages) {
                const container = document.getElementById('timelineOutput');
                if (!stages || stages.length === 0) {
                    container.innerHTML = '<p class="text-emerald-400 font-medium">No skill gaps remain! Ready for market application.</p>';
                    return;
                }
                container.innerHTML = stages.map(s => `
                    <div class="p-3 bg-slate-950/80 rounded-xl border border-slate-800">
                        <div class="font-bold text-indigo-400 mb-1">Closes in Semester ${s.semester}</div>
                        ${s.resolutions.map(r => `
                            <div class="text-slate-300 ml-1 mb-1">
                                &bull; <strong class="text-white">${r.skill}</strong> via <span class="text-slate-400">${r.course}</span>
                                <span class="text-emerald-400 font-mono text-[10px] ml-1">(+${Math.round(r.projected_confidence * 100)}%)</span>
                            </div>
                        `).join('')}
                    </div>
                `).join('');
            }

            function renderGraph(role, data) {
                const nodes = [];
                const edges = [];
                nodes.push({ id: 'ROLE', label: role, shape: 'box', color: { background: '#4f46e5', border: '#818cf8' }, font: { color: '#fff', face: 'monospace', size: 14 } });

                let idCounter = 1;
                function addSkills(items, color, border) {
                    items.forEach(item => {
                        const id = idCounter++;
                        nodes.push({
                            id: id,
                            label: `${item.skill}\\n(${Math.round(item.confidence * 100)}%)`,
                            shape: 'dot',
                            size: 18,
                            color: { background: color, border: border },
                            font: { color: '#e2e8f0', size: 11 }
                        });
                        edges.push({ from: 'ROLE', to: id, color: { color: border }, width: 1.5 });
                    });
                }

                addSkills(data.verified_skills, '#10b981', '#34d399');
                addSkills(data.partial_skills, '#f59e0b', '#fbbf24');
                addSkills(data.skill_gaps, '#ef4444', '#f87171');

                const container = document.getElementById('network-canvas');
                const networkData = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
                const options = {
                    physics: { barnesHut: { springLength: 130, springConstant: 0.04 } },
                    interaction: { hover: true, zoomView: true }
                };

                if (network) network.destroy();
                network = new vis.Network(container, networkData, options);
            }

            window.onload = runFlowA;
        </script>
    </body>
    </html>
    """