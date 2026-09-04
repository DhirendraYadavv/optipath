from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from neo4j import GraphDatabase
from pydantic import BaseModel

app = FastAPI(title="OptiPath - Career Gap & Academic Pathfinding Engine")

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

# --- Synthetic Student ERP Store ---
MOCK_STUDENTS = {
    "SGT10023": {
        "name": "Aarav Sharma",
        "program": "MCA",
        "current_semester": 2,
        "completed_courses": ["Code-OL130102"],  # Python Programming
    },
    "SGT10045": {
        "name": "Priya Nair",
        "program": "MCA",
        "current_semester": 3,
        "completed_courses": ["Code-OL130102", "Code-OL130202"],  # Python + DS
    },
    "SGT10089": {
        "name": "Rohan Verma",
        "program": "MCA",
        "current_semester": 4,
        "completed_courses": [
            "Code-OL130102",
            "Code-OL130202",
            "Code-OL130221",
        ],  # Python + DS + AI
    },
}


class GapAnalysisRequest(BaseModel):
    target_role: str
    completed_courses: List[str]
    program: Optional[str] = "MCA"


@app.get("/roles")
def get_job_roles():
    query = "MATCH (j:JobRole) RETURN j.name AS role"
    records, _, _ = driver.execute_query(query)
    return [r["role"] for r in records]


@app.get("/auth/student-lookup/{roll_no}")
def student_lookup(roll_no: str):
    roll = roll_no.upper().strip()
    if roll not in MOCK_STUDENTS:
        raise HTTPException(
            status_code=404,
            detail="Student not found in synthetic ERP database.",
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


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>OptiPath | Career Gap Engine</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
        <style>
            #network-canvas { height: 420px; width: 100%; border-radius: 0.75rem; background-color: #0b1329; }
        </style>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen font-sans p-6">
        <div class="max-w-6xl mx-auto space-y-6">
            <!-- Header -->
            <header class="border-b border-slate-800 pb-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div>
                    <h1 class="text-3xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-sky-400 to-indigo-400">OptiPath</h1>
                    <p class="text-sm text-slate-400">Curriculum-Grounded Career Gap & Pathfinding Engine</p>
                </div>
                <div class="flex items-center gap-3">
                    <span class="px-3 py-1 bg-emerald-500/10 text-emerald-400 text-xs rounded-full border border-emerald-500/20">Neo4j Aura Live</span>
                    <span class="px-3 py-1 bg-sky-500/10 text-sky-400 text-xs rounded-full border border-sky-500/20">SGT CDOE Engine</span>
                </div>
            </header>

            <!-- Control Strip -->
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                    <label class="text-xs font-semibold uppercase tracking-wider text-slate-400 block mb-1">Target Job Role</label>
                    <select id="roleSelect" class="w-full bg-slate-950 border border-slate-700 text-slate-100 rounded-lg p-2.5 text-sm focus:border-sky-500 focus:outline-none">
                        <option value="AI & Data Scientist">AI & Data Scientist</option>
                        <option value="Full-Stack Developer">Full-Stack Developer</option>
                        <option value="Cloud Architect">Cloud Architect</option>
                    </select>
                </div>
                <div>
                    <label class="text-xs font-semibold uppercase tracking-wider text-slate-400 block mb-1">Synthetic ERP Student Lookup</label>
                    <div class="flex gap-2">
                        <input id="rollInput" type="text" placeholder="SGT10023, SGT10045, SGT10089" value="SGT10023" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm uppercase focus:border-sky-500 focus:outline-none">
                        <button onclick="lookupStudent()" class="bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-2 rounded-lg text-xs font-semibold transition">Lookup</button>
                    </div>
                </div>
                <div>
                    <label class="text-xs font-semibold uppercase tracking-wider text-slate-400 block mb-1">Completed Courses</label>
                    <input id="coursesInput" type="text" value="Code-OL130102" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:border-sky-500 focus:outline-none">
                </div>
            </div>

            <!-- Action Buttons -->
            <div class="flex gap-3">
                <button onclick="runAnalysis()" class="bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 px-6 py-2.5 rounded-xl font-medium text-sm transition flex-1 shadow-lg shadow-sky-950">Run Skill-Gap Analysis</button>
            </div>

            <!-- Main Canvas & Readout -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- React Flow / Vis Canvas (2 Cols) -->
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

                <!-- Metrics & Timeline to Close (1 Col) -->
                <div class="space-y-4">
                    <!-- Readiness Score -->
                    <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl">
                        <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Market Readiness Score</span>
                        <div class="mt-2 flex items-baseline gap-2">
                            <span id="readinessScore" class="text-4xl font-black text-sky-400">0%</span>
                            <span class="text-xs text-slate-400">aligned with live market criteria</span>
                        </div>
                    </div>

                    <!-- Timeline-to-Close Card -->
                    <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-3">
                        <span class="text-xs font-semibold uppercase tracking-wider text-slate-400 block">Timeline-to-Close (Curriculum Traversal)</span>
                        <div id="timelineOutput" class="space-y-2 text-xs text-slate-300 max-h-64 overflow-y-auto">
                            <p class="text-slate-500">Run analysis to compute semester resolution path.</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            let network = null;

            async function lookupStudent() {
                const roll = document.getElementById('rollInput').value.trim();
                try {
                    const res = await fetch(`/auth/student-lookup/${roll}`);
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail);
                    document.getElementById('coursesInput').value = data.completed_courses.join(', ');
                    runAnalysis();
                } catch(e) {
                    alert(e.message);
                }
            }

            async function runAnalysis() {
                const role = document.getElementById('roleSelect').value;
                const coursesRaw = document.getElementById('coursesInput').value;
                const completed = coursesRaw ? coursesRaw.split(',').map(s => s.trim()).filter(Boolean) : [];

                try {
                    // 1. Skill Gap Call
                    const gapRes = await fetch('/graph/skill-gap', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ target_role: role, completed_courses: completed })
                    });
                    const gapData = await gapRes.json();
                    document.getElementById('readinessScore').innerText = `${gapData.readiness_percentage}%`;

                    // 2. Timeline Call
                    const timelineRes = await fetch('/graph/timeline', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ target_role: role, completed_courses: completed })
                    });
                    const timelineData = await timelineRes.json();
                    renderTimeline(timelineData.timeline_stages);

                    // 3. Render Vis Graph DAG
                    renderGraph(role, gapData);

                } catch(e) {
                    console.error(e);
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

                // Center node: Job Role
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

            window.onload = runAnalysis;
        </script>
    </body>
    </html>
    """