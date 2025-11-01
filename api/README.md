Neo4j Flask API

This is a Flask-based API to interact with a Neo4j database. It allows you to push graph data, query the database, and clear all data from the Neo4j instance. The API is built to interact with Neo4j via HTTP requests.

Table of Contents

- Base URL
- Authentication
- Endpoints
  - Home
  - Health Check
  - Push Graph Data
  - Query Graph
  - Clear Database
- Example Requests

---

Base URL

http://<your-server-ip>:8080

Replace <your-server-ip> with the actual IP address or hostname of the server where the Flask application is running.

---

Authentication

The API uses environment variables to configure the connection to the Neo4j database:

- NEO4J_URI: The URI of your Neo4j instance (e.g., bolt://localhost:7687).
- NEO4J_USER: The username for Neo4j authentication (default is neo4j).
- NEO4J_PASSWORD: The password for Neo4j authentication.

These values must be set in your environment for the API to connect to Neo4j. The application uses the python-dotenv package to load these variables from a .env file.

---

Endpoints

1. Home

Endpoint: /  
Method: GET

Returns a simple message indicating that the API is running and lists available endpoints.

Response Example:
{
    "message": "Neo4j Flask API is running!",
    "endpoints": ["/push", "/query", "/health"]
}

---

2. Health Check

Endpoint: /health  
Method: GET

Checks the health of the Neo4j database by running a simple query. If the Neo4j connection is working, it will return a success message.

Response Example:
{
    "status": "healthy",
    "neo4j": [{"status": "connected"}]
}

If the connection fails:
{
    "status": "unhealthy",
    "error": "Error message"
}

---

3. Push Graph Data

Endpoint: /push  
Method: POST

Pushes graph data to the Neo4j database. The body of the request should contain the graph data in JSON format, including nodes and relationships.

Request Body Example:
{
    "nodes": [
        {
            "id": "1",
            "label": "Person",
            "properties": {
                "name": "John",
                "age": 30
            }
        },
        {
            "id": "2",
            "label": "Company",
            "properties": {
                "name": "Acme Corp"
            }
        }
    ],
    "relationships": [
        {
            "from": "1",
            "to": "2",
            "type": "WORKS_AT",
            "properties": {
                "since": 2020
            }
        }
    ]
}

Response Example:
{
    "status": "success",
    "nodes_created": 2,
    "relationships_created": 1
}

If the request is missing required fields:
{
    "error": "Missing 'nodes' field in JSON"
}

---

4. Query Graph

Endpoint: /query  
Method: POST

Executes a custom Cypher query or searches for nodes by label and property. The query can either be passed directly as a Cypher string or using label/property/value pairs.

1. Request Body Example (using label/property/value):
{
    "label": "Person",
    "property": "name",
    "value": "John"
}

### Example Labels, Properties, and Values

Below is a list of all possible labels, their properties, and sample values based on the provided graph data:

**Label:** `Project`
- Properties:
  - `name`: "Team Nebula — Real-Time Dashboard"
  - `description`: "Real-time dashboard project. Frontend completed UI and query button; backend connected FastAPI to data feed. Current problem: Query button intermittently fails to re-render charts."
  - `status`: "in progress"
  - `lastWorkedOn`: "2025-11-01"

**Label:** `Person`
- Properties:
  - `name`: "Dana", "Ben", "Alice"
  - `role`: "Frontend", "Backend", "Project Lead"
  - `details`: 
    - "Finished the dashboard UI and query button; suspects useEffect hook missed queryParam causing re-render bug."
    - "Connected FastAPI to the data feed; will pair with Dana to debug re-rendering issue."
    - "Ran quick sync; coordinated the fix activity."
  - `lastActivity`: "2025-11-01"

**Label:** `Issue`
- Properties:
  - `title`: "Query button intermittently doesn’t re-render charts"
  - `description`: "The Query button sometimes fails to re-render charts; likely cause: frontend useEffect hook missing dependency (queryParam)."
  - `severity`: "medium"
  - `status`: "open"
  - `reportedBy`: "Alice"
  - `assignedTo`: ["Dana", "Ben"]
  - `targetFixTiming`: "before code freeze"
  - `lastObserved`: "2025-11-01"

**Relationship Types:**
- `WORKS_ON`
- `MANAGES`
- `REPORTS`
- `AFFECTS`
- `ASSIGNED_TO`

2. Request Body Example (using Cypher query):
{
    "cypher": "MATCH (n:Person) RETURN n LIMIT 10"
}

3. Response Example (Cypher query):
{
    "result": [
        {"n": {"id": "1", "name": "John", "age": 30}},
        {"n": {"id": "2", "name": "Jane", "age": 25}}
    ],
    "count": 2
}

If there’s an error:
{
    "error": "Missing 'cypher' or 'label' and 'property' fields in JSON"
}

---

5. Clear Database

Endpoint: /clear  
Method: DELETE

Clears all nodes and relationships from the database. Use this with caution, as it will delete all data.

Response Example:
{
    "status": "success",
    "message": "Database cleared"
}

If there’s an error:
{
    "error": "Error message"
}

---

Example Requests

Here’s how you might interact with the API using curl from the command line.

Health Check
curl http://localhost:8080/health

Push Graph Data
curl -X POST http://localhost:8080/push -H "Content-Type: application/json" -d '{
    "nodes": [
        {"id": "1", "label": "Person", "properties": {"name": "John", "age": 30}},
        {"id": "2", "label": "Company", "properties": {"name": "Acme Corp"}}
    ],
    "relationships": [
        {"from": "1", "to": "2", "type": "WORKS_AT", "properties": {"since": 2020}}
    ]
}'

Query Graph
curl -X POST http://localhost:8080/query -H "Content-Type: application/json" -d '{
    "label": "Person",
    "property": "name",
    "value": "John"
}'

Clear Database
curl -X DELETE http://localhost:8080/clear

---

Conclusion

With these API endpoints, you can easily interact with a Neo4j database, including creating nodes and relationships, querying data, and clearing the database. For any issues, please ensure the correct environment variables are set and the Neo4j database is running and accessible.



