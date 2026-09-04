from typing import List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from neo4j import GraphDatabase
from pydantic import BaseModel

app = FastAPI(title="OptiPath - Academic Pathfinding Engine")

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


class EligibilityRequest(BaseModel):
    completed_courses: List[str]


@app.get("/curriculum/{program}/{semester}")
def get_semester_curriculum(program: str, semester: int):
    query = """
    MATCH (p:Program)-[:HAS_SEMESTER]->(s:Semester {number: $sem})-[:INCLUDES]->(c:Course)
    WHERE toUpper(p.name) = toUpper($prog)
    RETURN c.code AS Code, c.title AS Title
    """
    records, _, _ = driver.execute_query(query, prog=program, sem=semester)
    if not records:
        raise HTTPException(
            status_code=404, detail="Curriculum not found for this program/semester."
        )

    return {
        "program": program.upper(),
        "semester": semester,
        "courses": [{"code": r["Code"], "title": r["Title"]} for r in records],
    }


@app.get("/curriculum/{program}")
def get_full_program_curriculum(program: str):
    query = """
    MATCH (p:Program)-[:HAS_SEMESTER]->(s:Semester)-[:INCLUDES]->(c:Course)
    WHERE toUpper(p.name) = toUpper($prog)
    RETURN s.number AS Semester, collect({code: c.code, title: c.title}) AS Courses
    ORDER BY s.number
    """
    records, _, _ = driver.execute_query(query, prog=program)
    if not records:
        raise HTTPException(status_code=404, detail="Program not found.")

    return {
        "program": program.upper(),
        "semesters": [
            {"semester": r["Semester"], "courses": r["Courses"]} for r in records
        ],
    }


@app.get("/course/{code}/prerequisites")
def get_course_prerequisites(code: str):
    query = """
    MATCH (c:Course)-[:REQUIRES]->(p:Course)
    WHERE toUpper(c.code) = toUpper($course_code)
    RETURN p.code AS Code, p.title AS Title
    """
    records, _, _ = driver.execute_query(query, course_code=code)
    return {
        "course": code,
        "prerequisites": [{"code": r["Code"], "title": r["Title"]} for r in records],
    }


@app.get("/course/{code}/learning-path")
def get_full_prerequisite_path(code: str):
    query = """
    MATCH path = (c:Course)-[:REQUIRES*1..]->(prereq:Course)
    WHERE toUpper(c.code) = toUpper($course_code)
    WITH prereq, length(path) AS depth
    RETURN prereq.code AS Code, prereq.title AS Title, depth
    ORDER BY depth DESC
    """
    records, _, _ = driver.execute_query(query, course_code=code)
    return {
        "target_course": code,
        "required_sequence": [
            {"step": idx + 1, "code": r["Code"], "title": r["Title"]}
            for idx, r in enumerate(records)
        ],
    }


@app.post("/course/{code}/check-eligibility")
def check_eligibility(code: str, payload: EligibilityRequest):
    query = """
    MATCH path = (c:Course)-[:REQUIRES*1..]->(prereq:Course)
    WHERE toUpper(c.code) = toUpper($course_code)
    WITH prereq, length(path) AS depth
    RETURN prereq.code AS Code, prereq.title AS Title, depth
    ORDER BY depth DESC
    """
    records, _, _ = driver.execute_query(query, course_code=code)

    completed_set = {c.strip().upper() for c in payload.completed_courses}
    required_courses = [
        {"code": r["Code"], "title": r["Title"]} for r in records
    ]

    missing = [
        course
        for course in required_courses
        if course["code"].upper() not in completed_set
    ]

    return {
        "target_course": code,
        "eligible": len(missing) == 0,
        "missing_prerequisites": missing,
        "total_prerequisites": len(required_courses),
    }


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>OptiPath - Curriculum & Pathfinding Engine</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-900 text-slate-100 min-h-screen font-sans p-6">
        <div class="max-w-5xl mx-auto space-y-8">
            <header class="border-b border-slate-800 pb-4 flex justify-between items-center">
                <div>
                    <h1 class="text-3xl font-bold text-sky-400">OptiPath</h1>
                    <p class="text-sm text-slate-400">Intelligent Curriculum & Pathfinding Platform</p>
                </div>
                <span class="px-3 py-1 bg-emerald-500/10 text-emerald-400 text-xs rounded-full border border-emerald-500/20">Neo4j Aura Connected</span>
            </header>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- Program Explorer -->
                <div class="bg-slate-800/60 p-6 rounded-xl border border-slate-700/60 space-y-4">
                    <h2 class="text-xl font-semibold text-white">Program Curriculum</h2>
                    <div class="flex gap-2">
                        <input id="progInput" type="text" placeholder="e.g. MCA, BCA, MBA" value="MCA" class="bg-slate-950 border border-slate-700 px-3 py-2 rounded-lg flex-1 text-sm focus:outline-none focus:border-sky-500 uppercase">
                        <button onclick="fetchCurriculum()" class="bg-sky-600 hover:bg-sky-500 px-4 py-2 rounded-lg text-sm font-medium transition">Load</button>
                    </div>
                    <div id="curriculumOutput" class="space-y-3 max-h-80 overflow-y-auto pr-2 text-sm text-slate-300"></div>
                </div>

                <!-- Pathfinding & Eligibility -->
                <div class="bg-slate-800/60 p-6 rounded-xl border border-slate-700/60 space-y-4">
                    <h2 class="text-xl font-semibold text-white">Prerequisite Path & Eligibility</h2>
                    <div class="space-y-2">
                        <input id="targetCourse" type="text" placeholder="Target Course (e.g. Code-OL130221)" value="Code-OL130221" class="w-full bg-slate-950 border border-slate-700 px-3 py-2 rounded-lg text-sm focus:outline-none focus:border-sky-500">
                        <input id="completedInput" type="text" placeholder="Completed Courses (comma-separated, e.g. Code-OL130102)" value="Code-OL130102" class="w-full bg-slate-950 border border-slate-700 px-3 py-2 rounded-lg text-sm focus:outline-none focus:border-sky-500">
                        <div class="flex gap-2 pt-2">
                            <button onclick="fetchLearningPath()" class="bg-indigo-600 hover:bg-indigo-500 px-4 py-2 rounded-lg text-sm font-medium transition flex-1">View Full Path</button>
                            <button onclick="checkEligibility()" class="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded-lg text-sm font-medium transition flex-1">Check Eligibility</button>
                        </div>
                    </div>
                    <div id="pathOutput" class="space-y-2 text-sm max-h-80 overflow-y-auto pr-2 text-slate-300"></div>
                </div>
            </div>
        </div>

        <script>
            async function fetchCurriculum() {
                const prog = document.getElementById('progInput').value.trim();
                const out = document.getElementById('curriculumOutput');
                out.innerHTML = '<p class="text-slate-400">Loading curriculum...</p>';
                try {
                    const res = await fetch(`/curriculum/${prog}`);
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Failed');
                    out.innerHTML = data.semesters.map(s => `
                        <div class="bg-slate-900/80 p-3 rounded-lg border border-slate-800">
                            <div class="font-semibold text-sky-300 mb-1">Semester ${s.semester}</div>
                            <ul class="list-disc list-inside space-y-1 text-xs text-slate-400">
                                ${s.courses.map(c => `<li><span class="text-slate-200 font-mono">${c.code}</span>: ${c.title}</li>`).join('')}
                            </ul>
                        </div>
                    `).join('');
                } catch(e) {
                    out.innerHTML = `<p class="text-rose-400 text-xs">${e.message}</p>`;
                }
            }

            async function fetchLearningPath() {
                const target = document.getElementById('targetCourse').value.trim();
                const out = document.getElementById('pathOutput');
                out.innerHTML = '<p class="text-slate-400">Traversing graph...</p>';
                try {
                    const res = await fetch(`/course/${target}/learning-path`);
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Failed');
                    if (data.required_sequence.length === 0) {
                        out.innerHTML = '<p class="text-emerald-400">No prerequisites required. Course is ready to take!</p>';
                        return;
                    }
                    out.innerHTML = `
                        <div class="font-medium text-indigo-300 mb-2">Required Sequence:</div>
                        <ol class="space-y-2">
                            ${data.required_sequence.map(s => `
                                <li class="bg-slate-900 p-2.5 rounded border border-slate-800 flex items-center gap-3">
                                    <span class="w-6 h-6 rounded-full bg-indigo-500/20 text-indigo-300 flex items-center justify-center font-mono text-xs">${s.step}</span>
                                    <div>
                                        <div class="font-mono text-xs text-slate-200">${s.code}</div>
                                        <div class="text-xs text-slate-400">${s.title}</div>
                                    </div>
                                </li>
                            `).join('')}
                        </ol>
                    `;
                } catch(e) {
                    out.innerHTML = `<p class="text-rose-400 text-xs">${e.message}</p>`;
                }
            }

            async function checkEligibility() {
                const target = document.getElementById('targetCourse').value.trim();
                const completedRaw = document.getElementById('completedInput').value;
                const completed = completedRaw ? completedRaw.split(',').map(s => s.trim()) : [];
                const out = document.getElementById('pathOutput');
                out.innerHTML = '<p class="text-slate-400">Checking graph rules...</p>';
                try {
                    const res = await fetch(`/course/${target}/check-eligibility`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ completed_courses: completed })
                    });
                    const data = await res.json();
                    if (data.eligible) {
                        out.innerHTML = `
                            <div class="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-300">
                                <strong>Eligible!</strong> All prerequisites satisfied for ${data.target_course}.
                            </div>
                        `;
                    } else {
                        out.innerHTML = `
                            <div class="p-4 bg-rose-500/10 border border-rose-500/30 rounded-lg text-rose-300 space-y-2">
                                <div><strong>Not Eligible.</strong> Missing ${data.missing_prerequisites.length} prerequisite(s):</div>
                                <ul class="list-disc list-inside text-xs space-y-1 text-rose-200">
                                    ${data.missing_prerequisites.map(m => `<li><span class="font-mono">${m.code}</span> - ${m.title}</li>`).join('')}
                                </ul>
                            </div>
                        `;
                    }
                } catch(e) {
                    out.innerHTML = `<p class="text-rose-400 text-xs">${e.message}</p>`;
                }
            }

            // Auto-load MCA on start
            window.onload = fetchCurriculum;
        </script>
    </body>
    </html>
    """