from neo4j import GraphDatabase

URI = "neo4j+s://1a8ea85a.databases.neo4j.io"
AUTH = ("1a8ea85a", "UzFHMFFxC_nRMONZ2a55gCHB0CDWAx3jwosskGKVRA8")

cypher_script = """
// 1. Create Industry Job Roles
MERGE (jr1:JobRole {name: 'Full-Stack Developer'})
MERGE (jr2:JobRole {name: 'Cloud Architect'})
MERGE (jr3:JobRole {name: 'AI & Data Scientist'})

// 2. Create Skills
UNWIND [
  {name: 'Python', category: 'Language'},
  {name: 'Data Structures', category: 'Core CS'},
  {name: 'Algorithms', category: 'Core CS'},
  {name: 'SQL & Relational DBs', category: 'Database'},
  {name: 'Applied Machine Learning', category: 'AI'},
  {name: 'Neural Networks', category: 'AI'},
  {name: 'Cloud Infrastructure', category: 'Cloud'},
  {name: 'Docker & Containers', category: 'DevOps'},
  {name: 'Kubernetes', category: 'DevOps'},
  {name: 'REST APIs & Backend', category: 'Backend'},
  {name: 'Web Security & Auth', category: 'Security'}
] AS s
MERGE (:Skill {name: s.name, category: s.category})

// 3. Link JobRoles to Required Skills
WITH 1 AS dummy
MATCH (jr:JobRole {name: 'Full-Stack Developer'})
MATCH (s1:Skill {name: 'Python'})
MATCH (s2:Skill {name: 'Data Structures'})
MATCH (s3:Skill {name: 'SQL & Relational DBs'})
MATCH (s4:Skill {name: 'REST APIs & Backend'})
MATCH (s5:Skill {name: 'Docker & Containers'})
MERGE (jr)-[:REQUIRES]->(s1)
MERGE (jr)-[:REQUIRES]->(s2)
MERGE (jr)-[:REQUIRES]->(s3)
MERGE (jr)-[:REQUIRES]->(s4)
MERGE (jr)-[:REQUIRES]->(s5)

WITH 1 AS dummy
MATCH (jr:JobRole {name: 'Cloud Architect'})
MATCH (s1:Skill {name: 'Python'})
MATCH (s2:Skill {name: 'Cloud Infrastructure'})
MATCH (s3:Skill {name: 'Docker & Containers'})
MATCH (s4:Skill {name: 'Kubernetes'})
MATCH (s5:Skill {name: 'Web Security & Auth'})
MERGE (jr)-[:REQUIRES]->(s1)
MERGE (jr)-[:REQUIRES]->(s2)
MERGE (jr)-[:REQUIRES]->(s3)
MERGE (jr)-[:REQUIRES]->(s4)
MERGE (jr)-[:REQUIRES]->(s5)

WITH 1 AS dummy
MATCH (jr:JobRole {name: 'AI & Data Scientist'})
MATCH (s1:Skill {name: 'Python'})
MATCH (s2:Skill {name: 'Data Structures'})
MATCH (s3:Skill {name: 'Applied Machine Learning'})
MATCH (s4:Skill {name: 'Neural Networks'})
MATCH (s5:Skill {name: 'SQL & Relational DBs'})
MERGE (jr)-[:REQUIRES]->(s1)
MERGE (jr)-[:REQUIRES]->(s2)
MERGE (jr)-[:REQUIRES]->(s3)
MERGE (jr)-[:REQUIRES]->(s4)
MERGE (jr)-[:REQUIRES]->(s5)

// 4. Map MCA Courses to Skills with Confidence Weights (0.3=Mention, 0.6=Lab, 1.0=Capstone)
WITH 1 AS dummy
MATCH (c:Course) WHERE toUpper(c.title) CONTAINS 'PYTHON'
MATCH (s:Skill {name: 'Python'})
MERGE (c)-[:TEACHES {weight: 1.0}]->(s)

WITH 1 AS dummy
MATCH (c:Course) WHERE toUpper(c.title) CONTAINS 'DATA STRUCTURE'
MATCH (s1:Skill {name: 'Data Structures'})
MATCH (s2:Skill {name: 'Algorithms'})
MERGE (c)-[:TEACHES {weight: 0.9}]->(s1)
MERGE (c)-[:TEACHES {weight: 0.7}]->(s2)

WITH 1 AS dummy
MATCH (c:Course) WHERE toUpper(c.title) CONTAINS 'INTELLIGENCE' OR toUpper(c.title) CONTAINS 'AI'
MATCH (s1:Skill {name: 'Applied Machine Learning'})
MATCH (s2:Skill {name: 'Neural Networks'})
MERGE (c)-[:TEACHES {weight: 0.8}]->(s1)
MERGE (c)-[:TEACHES {weight: 0.6}]->(s2)

WITH 1 AS dummy
MATCH (c:Course) WHERE toUpper(c.title) CONTAINS 'DATABASE' OR toUpper(c.title) CONTAINS 'SQL' OR toUpper(c.title) CONTAINS 'MANAGEMENT SYSTEM'
MATCH (s:Skill {name: 'SQL & Relational DBs'})
MERGE (c)-[:TEACHES {weight: 0.85}]->(s)

WITH 1 AS dummy
MATCH (c:Course) WHERE toUpper(c.title) CONTAINS 'SECURITY' OR toUpper(c.title) CONTAINS 'NETWORK'
MATCH (s:Skill {name: 'Web Security & Auth'})
MERGE (c)-[:TEACHES {weight: 0.6}]->(s)

WITH 1 AS dummy
MATCH (c:Course) WHERE toUpper(c.title) CONTAINS 'CLOUD'
MATCH (s:Skill {name: 'Cloud Infrastructure'})
MERGE (c)-[:TEACHES {weight: 0.75}]->(s)
"""

with GraphDatabase.driver(URI, auth=AUTH) as driver:
    with driver.session() as session:
        for query in cypher_script.strip().split(";"):
            cleaned = query.strip()
            if cleaned:
                session.run(cleaned)
    print("Graph successfully seeded with Skills, JobRoles, and TEACHES weights!")