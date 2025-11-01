from flask import Flask, request, jsonify
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

class Neo4jClient:
    def __init__(self, uri, user, password):
        """Initialize Neo4j connection"""
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
    
    def close(self):
        """Close the connection"""
        self.driver.close()
    
    def create_graph_from_json(self, graph_data):
        """
        Push graph-formatted JSON to Neo4j
        
        Expected JSON format:
        {
            "nodes": [
                {"id": "1", "label": "Person", "properties": {"name": "John", "age": 30}},
                {"id": "2", "label": "Company", "properties": {"name": "Acme Corp"}}
            ],
            "relationships": [
                {
                    "from": "1", 
                    "to": "2", 
                    "type": "WORKS_AT", 
                    "properties": {"since": 2020}
                }
            ]
        }
        """
        with self.driver.session() as session:
            # Create nodes
            for node in graph_data.get("nodes", []):
                session.run(
                    f"MERGE (n:{node['label']} {{id: $id}}) SET n += $properties",
                    id=node['id'],
                    properties=node.get('properties', {})
                )
            
            # Create relationships
            for rel in graph_data.get("relationships", []):
                session.run(
                    f"""
                    MATCH (a {{id: $from_id}}), (b {{id: $to_id}})
                    MERGE (a)-[r:{rel['type']}]->(b)
                    SET r += $properties
                    """,
                    from_id=rel['from'],
                    to_id=rel['to'],
                    properties=rel.get('properties', {})
                )
            
            return {
                "status": "success", 
                "nodes_created": len(graph_data.get("nodes", [])), 
                "relationships_created": len(graph_data.get("relationships", []))
            }
    
    def query_graph(self, cypher_query, parameters=None):
        """Execute a custom Cypher query"""
        with self.driver.session() as session:
            result = session.run(cypher_query, parameters or {})
            return [record.data() for record in result]
    
    def delete_database(self):
        """Delete all nodes and relationships from the database"""
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        return {"status": "success", "message": "Database cleared"}

# Initialize Neo4j client
URI = os.environ.get("NEO4J_URI")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD")

if not URI or not PASSWORD:
    raise ValueError("NEO4J_URI and NEO4J_PASSWORD must be set in environment variables")

neo4j_client = Neo4jClient(URI, USER, PASSWORD)

# Routes
@app.route('/')
def home():
    return jsonify({"message": "Neo4j Flask API is running!", "endpoints": ["/push", "/query", "/health"]})

@app.route('/health', methods=['GET'])
def health_check():
    """Check if Neo4j connection is working"""
    try:
        result = neo4j_client.query_graph("RETURN 'connected' AS status")
        return jsonify({"status": "healthy", "neo4j": result[0]}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

@app.route('/push', methods=['POST'])
def push_graph():
    """
    Push graph data to Neo4j
    
    Expected JSON body:
    {
        "nodes": [...],
        "relationships": [...]
    }
    """
    try:
        graph_data = request.get_json()
        
        if not graph_data:
            return jsonify({"error": "No JSON data provided"}), 400
        
        if "nodes" not in graph_data:
            return jsonify({"error": "Missing 'nodes' field in JSON"}), 400
        
        result = neo4j_client.create_graph_from_json(graph_data)
        return jsonify(result), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/query', methods=['POST'])
def query_graph():
    """
    Execute a custom Cypher query or search by label/property.

    Expected JSON body:
    {
        "cypher": "MATCH (n:Person) RETURN n LIMIT 10",  // optional
        "label": "Person",                               // optional
        "property": "name",                              // optional
        "value": "John",                                 // optional
        "parameters": {}                                 // optional
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        # If cypher is provided, use it
        if "cypher" in data:
            cypher_query = data["cypher"]
            parameters = data.get("parameters", {})
        # Otherwise, build query from label/property/value
        elif "label" in data and "property" in data:
            label = data["label"]
            prop = data["property"]
            value = data.get("value")
            if value is not None:
                cypher_query = f"MATCH (n:{label}) WHERE n.{prop} = $value RETURN n"
                parameters = {"value": value}
            else:
                cypher_query = f"MATCH (n:{label}) WHERE exists(n.{prop}) RETURN n"
                parameters = {}
        else:
            return jsonify({"error": "Missing 'cypher' or 'label' and 'property' fields in JSON"}), 400

        result = neo4j_client.query_graph(cypher_query, parameters)
        return jsonify({"result": result, "count": len(result)}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/clear', methods=['DELETE'])
def clear_database():
    """Clear all nodes and relationships (use with caution!)"""
    try:
        result = neo4j_client.delete_database()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Cleanup on shutdown
@app.teardown_appcontext
def shutdown_session(exception=None):
    pass  # Connection is managed per request

if __name__ == "__main__":
    try:
        app.run(debug=True, host='0.0.0.0', port=8080)
    finally:
        neo4j_client.close()