from neo4j import GraphDatabase

URI = "neo4j+s://1a8ea85a.databases.neo4j.io"
AUTH = ("1a8ea85a", "UzFHMFFxC_nRMONZ2a55gCHB0CDWAx3jwosskGKVRA8")

cleanup_queries = [
    # 1. Remove raw prefix duplicate courses without 'Code-'
    """
    MATCH (c:Course)
    WHERE NOT c.code STARTS WITH 'Code-'
    DETACH DELETE c
    """,
    # 2. Remove redundant lab relationships mapped to the same skill
    """
    MATCH (c:Course)-[t:TEACHES]->(s:Skill)
    WHERE toUpper(c.title) CONTAINS 'LAB'
    DETACH DELETE t
    """,
    # 3. Create snapshots
    """
    MERGE (r23:RoleSnapshot {role: 'AI & Data Scientist', year: 2023})
    MERGE (r26:RoleSnapshot {role: 'AI & Data Scientist', year: 2026})
    """,
    # 4. Link 2023 Demanded Skills
    """
    MATCH (r23:RoleSnapshot {role: 'AI & Data Scientist', year: 2023})
    MATCH (s:Skill)
    WHERE s.name IN ['Python', 'Data Structures', 'SQL & Relational DBs']
    MERGE (r23)-[:DEMANDED]->(s)
    """,
    # 5. Link 2026 Demanded Skills
    """
    MATCH (r26:RoleSnapshot {role: 'AI & Data Scientist', year: 2026})
    MATCH (s:Skill)
    WHERE s.name IN ['Python', 'Applied Machine Learning', 'Neural Networks', 'Generative AI & LLMs', 'Vector Databases', 'MLOps & CI/CD']
    MERGE (r26)-[:DEMANDED]->(s)
    """,
]

with GraphDatabase.driver(URI, auth=AUTH) as driver:
    with driver.session() as session:
        for query in cleanup_queries:
            session.run(query)
    print("Database cleaned: duplicates removed and snapshots verified!")