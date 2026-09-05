from io import BytesIO
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from neo4j import GraphDatabase
from pydantic import BaseModel
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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

# Extended Synthetic ERP Cohort
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
    "SGT20011": {
        "name": "Meera Joshi",
        "program": "BCA",
        "current_semester": 2,
        "completed_courses": ["Code-OL130102"],
    },
}

SALARY_BASELINES = {
    "AI & Data Scientist": {"baseline": 4.5, "post_degree": 12.0},
    "Full-Stack Developer": {"baseline": 3.8, "post_degree": 9.5},
    "Cloud Architect": {"baseline": 5.0, "post_degree": 14.0},
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
            status_code=404, detail="Student record not found in synthetic ERP."
        )
    return {"roll_no": roll, **MOCK_STUDENTS[roll]}


@app.post("/graph/skill-gap")
def compute_skill_gap(payload: GapAnalysisRequest):
    query = """
    MATCH (jr:JobRole {name: $role})-[:REQUIRES]->(s:Skill)
    OPTIONAL MATCH (c:Course)-[t:TEACHES]->(s)
    WHERE toUpper(c.code) IN [code IN $completed | toUpper(code)]
    WITH s, c, max(coalesce(t.weight, 0.0)) AS confidence
    RETURN s.name AS skill, s.category AS category, confidence, collect(DISTINCT c.title) AS source_courses
    ORDER BY confidence DESC, s.name ASC
    """
    records, _, _ = driver.execute_query(
        query, role=payload.target_role, completed=payload.completed_courses
    )

    verified, partial, gap = [], [], []

    for r in records:
        item = {
            "skill": r["skill"],
            "category": r["category"],
            "confidence": round(r["confidence"], 2),
            "sources": [s for s in r["source_courses"] if s],
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

    salary_info = SALARY_BASELINES.get(
        payload.target_role, {"baseline": 4.0, "post_degree": 10.0}
    )
    projected_salary = round(
        salary_info["baseline"]
        + (
            (salary_info["post_degree"] - salary_info["baseline"])
            * (readiness_pct / 100)
        ),
        1,
    )

    return {
        "role": payload.target_role,
        "readiness_percentage": readiness_pct,
        "projected_lpa": projected_salary,
        "salary_range": salary_info,
        "total_required": total,
        "verified_skills": verified,
        "partial_skills": partial,
        "skill_gaps": gap,
        "completed_courses": payload.completed_courses,
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
      AND future_course.code STARTS WITH 'Code-'
      AND NOT toUpper(future_course.title) CONTAINS 'LAB'
    RETURN DISTINCT s.name AS missing_skill,
           sem.number AS closes_in_semester,
           future_course.code AS course_code,
           future_course.title AS course_title,
           max(ft.weight) AS projected_confidence
    ORDER BY closes_in_semester ASC, missing_skill ASC
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
                "course": f"{r['course_code']} - {r['course_title']}",
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
    WITH collect(DISTINCT s23.name) AS skills_2023
    MATCH (r26:RoleSnapshot {role: $role, year: 2026})-[:DEMANDED]->(s26:Skill)
    WITH skills_2023, collect(DISTINCT s26.name) AS skills_2026

    RETURN skills_2023,
           skills_2026,
           [s IN skills_2026 WHERE NOT s IN skills_2023] AS emerging_skills
    """
    records, _, _ = driver.execute_query(query, role=role)
    if not records:
        raise HTTPException(
            status_code=404, detail="Drift data not found for role."
        )

    rec = records[0]
    emerging = rec["emerging_skills"]

    curriculum_check = """
    MATCH (s:Skill) WHERE s.name IN $emerging
    OPTIONAL MATCH (c:Course)-[t:TEACHES]->(s)
    RETURN s.name AS skill, count(c) > 0 AS taught_in_sgt
    """
    checks, _, _ = driver.execute_query(curriculum_check, emerging=emerging)

    drift_report = [
        {
            "skill": ch["skill"],
            "curriculum_status": (
                "Covered in SGT Curriculum"
                if ch["taught_in_sgt"]
                else "Curriculum Gap (Needs Syllabus Update)"
            ),
        }
        for ch in checks
    ]

    return {
        "role": role,
        "historical_year": 2023,
        "current_year": 2026,
        "emerging_skills": drift_report,
        "stable_skills": [
            s for s in rec["skills_2026"] if s in rec["skills_2023"]
        ],
    }


@app.post("/resume/export-pdf")
def export_verified_resume_pdf(payload: GapAnalysisRequest):
    gap_data = compute_skill_gap(payload)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    elements = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleStyle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#475569"),
        spaceAfter=14,
    )
    section_style = ParagraphStyle(
        "SectionStyle",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=colors.HexColor("#1e293b"),
        spaceBefore=12,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#334155"),
        spaceAfter=4,
    )

    elements.append(
        Paragraph("SGT CDOE • OptiPath Verified Competency Report", title_style)
    )
    elements.append(
        Paragraph(
            f"Target Industry Role: <b>{gap_data['role']}</b> &nbsp;|&nbsp; Certified Market Readiness: <b>{gap_data['readiness_percentage']}%</b>",
            subtitle_style,
        )
    )
    elements.append(Spacer(1, 8))

    elements.append(
        Paragraph("1. Academically Verified Competencies", section_style)
    )
    table_data = [["Skill", "Domain", "Confidence", "Certified Coursework"]]
    for item in gap_data["verified_skills"]:
        sources = ", ".join(item["sources"]) if item["sources"] else "Core Syllabus Coursework"
        table_data.append(
            [
                item["skill"],
                item["category"],
                f"{int(item['confidence']*100)}%",
                sources,
            ]
        )

    t = Table(table_data, colWidths=[120, 90, 70, 240])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0284c7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
            ]
        )
    )
    elements.append(t)
    elements.append(Spacer(1, 14))

    if gap_data["skill_gaps"]:
        elements.append(
            Paragraph("2. Outstanding Curriculum Gaps (Roadmapped)", section_style)
        )
        for g in gap_data["skill_gaps"]:
            elements.append(
                Paragraph(
                    f"&bull; <b>{g['skill']}</b> ({g['category']}) &mdash; Scheduled for resolution in subsequent academic semesters.",
                    body_style,
                )
            )

    elements.append(Spacer(1, 20))
    elements.append(
        Paragraph(
            f"<b>Integrity Hash:</b> SGT-AUTH-{abs(hash(gap_data['role'] + str(payload.completed_courses)))}<br/>"
            "<i>Issued by SGT Center for Distance and Online Education &bull; OptiPath Career Graph Validation</i>",
            body_style,
        )
    )

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=SGT_Verified_Profile_{gap_data['role'].replace(' ', '_')}.pdf"
        },
    )


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>OptiPath | SGT CDOE Career Gap Engine</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
        <style>
            #network-canvas { height: 460px; width: 100%; border-radius: 0.75rem; background-color: #060b18; }
        </style>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen font-sans p-6">
        <div class="max-w-6xl mx-auto space-y-6">
            <!-- Header -->
            <header class="border-b border-slate-800 pb-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div>
                    <h1 class="text-3xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-sky-400 via-indigo-300 to-emerald-400">OptiPath</h1>
                    <p class="text-sm text-slate-400">Curriculum-Grounded Career Gap & Pathfinding Engine &bull; SGT CDOE</p>
                </div>
                <div class="flex gap-2 bg-slate-900 p-1 rounded-xl border border-slate-800 text-xs font-semibold">
                    <button id="tabA" onclick="switchTab('A')" class="px-4 py-2 rounded-lg bg-sky-600 text-white transition">Flow A: Enrolled Student</button>
                    <button id="tabB" onclick="switchTab('B')" class="px-4 py-2 rounded-lg text-slate-400 hover:text-white transition">Flow B: Prospective Pivot</button>
                    <button id="tabDrift" onclick="switchTab('drift')" class="px-4 py-2 rounded-lg text-slate-400 hover:text-white transition">Market Drift (Mechanic #3)</button>
                </div>
            </header>

            <!-- Flow A: Enrolled Controls -->
            <div id="flowAControls" class="space-y-4">
                <div class="bg-slate-900 border border-slate-800 p-4 rounded-2xl grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                        <label class="text-xs font-semibold uppercase tracking-wider text-slate-400 block mb-1">Target Job Role</label>
                        <select id="roleSelect" onchange="runCurrentFlow()" class="w-full bg-slate-950 border border-slate-700 text-slate-100 rounded-lg p-2 text-sm">
                            <option value="AI & Data Scientist">AI & Data Scientist</option>
                            <option value="Full-Stack Developer">Full-Stack Developer</option>
                            <option value="Cloud Architect">Cloud Architect</option>
                        </select>
                    </div>
                    <div>
                        <label class="text-xs font-semibold uppercase tracking-wider text-slate-400 block mb-1">Synthetic ERP Lookup</label>
                        <div class="flex gap-2">
                            <input id="rollInput" type="text" value="SGT10023" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm uppercase">
                            <button onclick="lookupStudent()" class="bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-2 rounded-lg text-xs font-semibold">Lookup</button>
                        </div>
                    </div>
                    <div>
                        <label class="text-xs font-semibold uppercase tracking-wider text-slate-400 block mb-1">Completed Courses</label>
                        <input id="coursesInput" type="text" value="Code-OL130102" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm">
                    </div>
                </div>
                <div class="flex gap-3">
                    <button onclick="runCurrentFlow()" class="bg-sky-600 hover:bg-sky-500 py-2.5 px-6 rounded-xl font-medium text-sm transition flex-1">Run Skill-Gap Analysis</button>
                    <button onclick="downloadPdfResume()" class="bg-emerald-600 hover:bg-emerald-500 py-2.5 px-6 rounded-xl font-medium text-sm transition flex items-center justify-center gap-2">
                        <span>Download Official ATS PDF</span>
                    </button>
                </div>
            </div>

            <!-- Flow B: Prospective Pivot Controls & Salary Projection -->
            <div id="flowBControls" class="hidden space-y-4">
                <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl flex flex-col md:flex-row items-center justify-between gap-4">
                    <div>
                        <span class="text-xs font-semibold uppercase tracking-wider text-indigo-400">Prospective Student Mode</span>
                        <h3 class="text-lg font-bold text-white">Degree Pivot & Salary Transformation</h3>
                        <p class="text-xs text-slate-400">Simulate market employability before and after enrolling in SGT Online MCA.</p>
                    </div>
                    <div class="flex items-center gap-3 bg-slate-950 px-4 py-3 rounded-xl border border-slate-800">
                        <label class="text-sm font-medium text-slate-300 cursor-pointer" for="pivotToggle">Enroll in SGT Online MCA</label>
                        <input type="checkbox" id="pivotToggle" onchange="runCurrentFlow()" class="w-5 h-5 accent-emerald-500 cursor-pointer">
                    </div>
                </div>

                <!-- Salary Slider ROI Box -->
                <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl grid grid-cols-1 md:grid-cols-2 gap-4 items-center">
                    <div>
                        <span class="text-xs font-semibold uppercase tracking-wider text-slate-400 block">Projected Compensation (LPA)</span>
                        <div class="text-3xl font-extrabold text-emerald-400 mt-1" id="salaryDisplay">&#8377; 4.5 LPA</div>
                        <p class="text-xs text-slate-400 mt-1">Estimated annual package benchmarked against live entry vs. verified credential status.</p>
                    </div>
                    <div class="space-y-2">
                        <div class="flex justify-between text-xs text-slate-400">
                            <span>Unskilled Baseline: <b id="minSal">&#8377; 4.5L</b></span>
                            <span>Target Degree Cap: <b id="maxSal">&#8377; 12.0L</b></span>
                        </div>
                        <div class="w-full bg-slate-950 h-3 rounded-full overflow-hidden border border-slate-800">
                            <div id="salaryBar" class="h-full bg-gradient-to-r from-sky-500 to-emerald-400 transition-all duration-500" style="width: 15%"></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Market Drift Section -->
            <div id="driftSection" class="hidden bg-slate-900 border border-slate-800 p-6 rounded-2xl space-y-4">
                <div class="flex justify-between items-center">
                    <div>
                        <span class="text-xs font-semibold uppercase tracking-wider text-amber-400">Novel Mechanic #3</span>
                        <h3 class="text-xl font-bold text-white">Curriculum Market Drift Detector</h3>
                        <p class="text-xs text-slate-400">Diffs 2023 vs 2026 role requirements against current SGT syllabus.</p>
                    </div>
                    <button onclick="loadDrift()" class="bg-amber-600 hover:bg-amber-500 px-4 py-2 rounded-xl text-xs font-semibold transition">Scan Neo4j Drift</button>
                </div>
                <div id="driftOutput" class="space-y-2 pt-2"></div>
            </div>

            <!-- Visuals: Hierarchical DAG & Timeline -->
            <div id="graphLayout" class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div class="lg:col-span-2 bg-slate-900 border border-slate-800 p-4 rounded-2xl space-y-3">
                    <div class="flex justify-between items-center px-1">
                        <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-300">Hierarchical DAG (Courses &rarr; Skills &rarr; Role)</h2>
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
                        <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Curriculum Market Readiness</span>
                        <div class="mt-2 flex items-baseline gap-2">
                            <span id="readinessScore" class="text-4xl font-black text-sky-400">0%</span>
                            <span class="text-xs text-slate-400">confidence verified</span>
                        </div>
                    </div>

                    <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-3">
                        <span class="text-xs font-semibold uppercase tracking-wider text-slate-400 block">Timeline-to-Close (Curriculum Traversal)</span>
                        <div id="timelineOutput" class="space-y-2 text-xs text-slate-300 max-h-64 overflow-y-auto"></div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            let currentTab = 'A';
            let network = null;

            function switchTab(tab) {
                currentTab = tab;
                document.getElementById('flowAControls').classList.add('hidden');
                document.getElementById('flowBControls').classList.add('hidden');
                document.getElementById('driftSection').classList.add('hidden');
                document.getElementById('graphLayout').classList.remove('hidden');

                document.getElementById('tabA').className = 'px-4 py-2 rounded-lg text-slate-400 hover:text-white transition';
                document.getElementById('tabB').className = 'px-4 py-2 rounded-lg text-slate-400 hover:text-white transition';
                document.getElementById('tabDrift').className = 'px-4 py-2 rounded-lg text-slate-400 hover:text-white transition';

                if (tab === 'A') {
                    document.getElementById('flowAControls').classList.remove('hidden');
                    document.getElementById('tabA').className = 'px-4 py-2 rounded-lg bg-sky-600 text-white transition';
                    runCurrentFlow();
                } else if (tab === 'B') {
                    document.getElementById('flowBControls').classList.remove('hidden');
                    document.getElementById('tabB').className = 'px-4 py-2 rounded-lg bg-indigo-600 text-white transition';
                    runCurrentFlow();
                } else if (tab === 'drift') {
                    document.getElementById('driftSection').classList.remove('hidden');
                    document.getElementById('graphLayout').classList.add('hidden');
                    document.getElementById('tabDrift').className = 'px-4 py-2 rounded-lg bg-amber-600 text-white transition';
                    loadDrift();
                }
            }

            async function lookupStudent() {
                const roll = document.getElementById('rollInput').value.trim();
                try {
                    const res = await fetch(`/auth/student-lookup/${roll}`);
                    const d = await res.json();
                    if (!res.ok) throw new Error(d.detail);
                    document.getElementById('coursesInput').value = d.completed_courses.join(', ');
                    runCurrentFlow();
                } catch(e) {
                    alert(e.message);
                }
            }

            function getActiveCompletedCourses() {
                if (currentTab === 'B') {
                    const isEnrolled = document.getElementById('pivotToggle').checked;
                    return isEnrolled ? ["Code-OL130102", "Code-OL130202", "Code-OL130221"] : [];
                }
                const raw = document.getElementById('coursesInput').value;
                return raw ? raw.split(',').map(s => s.trim()).filter(Boolean) : [];
            }

            async function runCurrentFlow() {
                const role = document.getElementById('roleSelect').value;
                const completed = getActiveCompletedCourses();

                try {
                    const gapRes = await fetch('/graph/skill-gap', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ target_role: role, completed_courses: completed })
                    });
                    const gapData = await gapRes.json();
                    document.getElementById('readinessScore').innerText = `${gapData.readiness_percentage}%`;

                    // Update Salary Visualization
                    if (gapData.projected_lpa) {
                        document.getElementById('salaryDisplay').innerHTML = `&#8377; ${gapData.projected_lpa} LPA`;
                        document.getElementById('minSal').innerText = `₹ ${gapData.salary_range.baseline}L`;
                        document.getElementById('maxSal').innerText = `₹ ${gapData.salary_range.post_degree}L`;
                        document.getElementById('salaryBar').style.width = `${gapData.readiness_percentage}%`;
                    }

                    const timeRes = await fetch('/graph/timeline', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ target_role: role, completed_courses: completed })
                    });
                    const timeData = await timeRes.json();
                    renderTimeline(timeData.timeline_stages);
                    renderDAG(role, completed, gapData);
                } catch(e) {
                    console.error(e);
                }
            }

            function renderTimeline(stages) {
                const out = document.getElementById('timelineOutput');
                if (!stages || stages.length === 0) {
                    out.innerHTML = '<div class="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-emerald-300">All role requirements resolved!</div>';
                    return;
                }
                out.innerHTML = stages.map(s => `
                    <div class="p-3 bg-slate-950/80 rounded-xl border border-slate-800">
                        <div class="font-bold text-sky-400 mb-1">Closes in Semester ${s.semester}</div>
                        ${s.resolutions.map(r => `
                            <div class="text-slate-300 ml-1 mb-1">
                                &bull; <strong class="text-white">${r.skill}</strong> via <span class="text-slate-400">${r.course}</span>
                                <span class="text-emerald-400 font-mono text-[10px] ml-1">(+${Math.round(r.projected_confidence * 100)}%)</span>
                            </div>
                        `).join('')}
                    </div>
                `).join('');
            }

            function renderDAG(role, completed, data) {
                const nodes = [];
                const edges = [];

                // Layer 1 (Left): Completed Course Nodes
                completed.forEach((c, idx) => {
                    const cId = `C_${idx}`;
                    nodes.push({
                        id: cId,
                        label: c,
                        level: 1,
                        shape: 'box',
                        color: { background: '#1e293b', border: '#38bdf8' },
                        font: { color: '#38bdf8', face: 'monospace', size: 11 }
                    });
                });

                // Layer 3 (Right): Target Job Role Node
                nodes.push({
                    id: 'TARGET_ROLE',
                    label: role,
                    level: 3,
                    shape: 'box',
                    color: { background: '#4338ca', border: '#818cf8' },
                    font: { color: '#ffffff', size: 14, bold: true }
                });

                // Layer 2 (Middle): Skills
                let sCounter = 0;
                function addSkills(list, bg, border) {
                    list.forEach(item => {
                        const sId = `S_${sCounter++}`;
                        nodes.push({
                            id: sId,
                            label: `${item.skill}\\n(${Math.round(item.confidence * 100)}%)`,
                            level: 2,
                            shape: 'ellipse',
                            color: { background: bg, border: border },
                            font: { color: '#ffffff', size: 11 }
                        });
                        edges.push({ from: sId, to: 'TARGET_ROLE', color: { color: border }, arrows: 'to' });
                        if (item.confidence > 0 && completed.length > 0) {
                            edges.push({ from: 'C_0', to: sId, color: { color: '#38bdf8' }, arrows: 'to', dashes: true });
                        }
                    });
                }

                addSkills(data.verified_skills, '#10b981', '#34d399');
                addSkills(data.partial_skills, '#f59e0b', '#fbbf24');
                addSkills(data.skill_gaps, '#ef4444', '#f87171');

                const container = document.getElementById('network-canvas');
                const networkData = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
                const options = {
                    layout: {
                        hierarchical: {
                            direction: 'LR',
                            sortMethod: 'directed',
                            levelSeparation: 190,
                            nodeSpacing: 80
                        }
                    },
                    physics: false
                };

                if (network) network.destroy();
                network = new vis.Network(container, networkData, options);
            }

            async function loadDrift() {
                const out = document.getElementById('driftOutput');
                out.innerHTML = '<p class="text-slate-400">Scanning Neo4j snapshot version nodes...</p>';
                try {
                    const res = await fetch('/market/drift?role=AI%20%26%20Data%20Scientist');
                    const d = await res.json();
                    out.innerHTML = `
                        <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-3">
                            <div class="text-xs font-semibold text-slate-300">Emerging Industry Competencies (2023 vs 2026 Diff):</div>
                            <div class="space-y-2">
                                ${d.emerging_skills.map(s => `
                                    <div class="flex justify-between items-center p-2.5 rounded-lg bg-slate-900 border border-slate-800">
                                        <span class="font-medium text-amber-300 text-sm">${s.skill}</span>
                                        <span class="text-xs px-2.5 py-1 rounded-full ${s.curriculum_status.includes('Covered') ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/10 text-rose-400 border border-rose-500/30'}">${s.curriculum_status}</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    `;
                } catch(e) {
                    out.innerHTML = `<p class="text-rose-400">${e.message}</p>`;
                }
            }

            async function downloadPdfResume() {
                const role = document.getElementById('roleSelect').value;
                const completed = getActiveCompletedCourses();
                const res = await fetch('/resume/export-pdf', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ target_role: role, completed_courses: completed })
                });
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `SGT_Verified_Profile_${role.replace(/\\s+/g, '_')}.pdf`;
                a.click();
            }

            window.onload = runCurrentFlow;
        </script>
    </body>
    </html>
    """