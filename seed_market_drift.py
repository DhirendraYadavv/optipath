from neo4j import GraphDatabase

URI = "neo4j+s://1a8ea85a.databases.neo4j.io"
AUTH = ("1a8ea85a", "UzFHMFFxC_nRMONZ2a55gCHB0CDWAx3jwosskGKVRA8")

cypher = """
// Create Emerging 2026 Skills
MERGE (s1:Skill {name: 'Generative AI & LLMs', category: 'AI'})
MERGE (s2:Skill {name: 'Vector Databases', category: 'Database'})
MERGE (s3:Skill {name: 'MLOps & CI/CD', category: 'DevOps'})

// 2023 Snapshot (Baseline)
MERGE (r23:RoleSnapshot {role: 'AI & Data Scientist', year: 2023})
WITH r23
MATCH (s:Skill) WHERE s.name IN ['Python', 'Data Structures', 'Applied Machine Learning', 'SQL & Relational DBs']
MERGE (r23)-[:DEMANDED]->(s)

// 2026 Snapshot (Market Drifted)
WITH 1 AS dummy
MERGE (r26:RoleSnapshot {role: 'AI & Data Scientist', year: 2026})
WITH r26
MATCH (s:Skill) WHERE s.name IN ['Python', 'Applied Machine Learning', 'Neural Networks', 'Generative AI & LLMs', 'Vector Databases', 'MLOps & CI/CD']
MERGE (r26)-[:DEMANDED]->(s)
"""

with GraphDatabase.driver(URI, auth=AUTH) as driver:
    with driver.session() as session:
        for stmt in cypher.strip().split(";"):
            cleaned = stmt.strip()
            if cleaned:
                session.run(cleaned)
    print("Market Drift snapshots (2023 vs 2026) seeded successfully!")