import streamlit as st
from neo4j import GraphDatabase
from pyvis.network import Network
import streamlit.components.v1 as components
import os
from dotenv import load_dotenv

load_dotenv()

class Neo4jGraphViewer:
    def __init__(self, uri, user, password):
        """Initialize Neo4j connection"""
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            self.connected = True
        except Exception as e:
            st.error(f"Failed to connect to Neo4j: {str(e)}")
            self.connected = False
    
    def close(self):
        """Close the connection"""
        if hasattr(self, 'driver'):
            self.driver.close()
    
    def get_all_relationships(self, limit=200):
        """Fetch all relationships from the graph"""
        if not self.connected:
            return []
        
        with self.driver.session() as session:
            result = session.run(f"""
                MATCH (n)-[r]->(m)
                RETURN n, r, m
                LIMIT {limit}
            """)
            return [(record["n"], record["r"], record["m"]) for record in result]

def create_graph_visualization(relationships):
    """Create an interactive network graph using PyVis"""
    net = Network(
        height="750px",
        width="100%",
        bgcolor="#222222",
        font_color="white",
        directed=True
    )
    
    # Physics settings for better layout
    net.barnes_hut(
        gravity=-8000,
        central_gravity=0.3,
        spring_length=250,
        spring_strength=0.001,
        damping=0.09
    )
    
    # Color coding for different node types
    colors = {
        "Person": "#FF6B6B",
        "Project": "#4ECDC4",
        "Company": "#45B7D1",
        "Department": "#FFA07A",
        "Technology": "#98D8C8",
        "Meeting": "#F7DC6F",
        "Task": "#BB8FCE",
        "Document": "#85C1E2"
    }
    
    added_nodes = set()
    
    for source_node, relationship, target_node in relationships:
        # Add source node
        source_id = source_node.get("id", str(id(source_node)))
        if source_id not in added_nodes:
            label = list(source_node.labels)[0] if source_node.labels else "Unknown"
            tooltip = "\n".join([f"{k}: {v}" for k, v in dict(source_node).items()])
            net.add_node(
                source_id,
                label=source_node.get("name", source_id),
                title=tooltip,
                color=colors.get(label, "#95A5A6"),
                size=25
            )
            added_nodes.add(source_id)
        
        # Add target node
        target_id = target_node.get("id", str(id(target_node)))
        if target_id not in added_nodes:
            label = list(target_node.labels)[0] if target_node.labels else "Unknown"
            tooltip = "\n".join([f"{k}: {v}" for k, v in dict(target_node).items()])
            net.add_node(
                target_id,
                label=target_node.get("name", target_id),
                title=tooltip,
                color=colors.get(label, "#95A5A6"),
                size=25
            )
            added_nodes.add(target_id)
        
        # Add relationship
        edge_tooltip = f"{relationship.type}"
        net.add_edge(source_id, target_id, title=edge_tooltip, label=relationship.type)
    
    return net.generate_html()

def main():
    """Main function to display Neo4j graph"""
    st.title("🕸️ Knowledge Graph")
    
    # Use environment variables for connection
    uri = os.getenv("NEO4J_URI", "")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    
    limit = st.slider("Max nodes to display", 50, 500, 200)
    
    viewer = Neo4jGraphViewer(uri, user, password)
    if viewer.connected:
        with st.spinner("Loading graph..."):
            relationships = viewer.get_all_relationships(limit=limit)
        
        if relationships:
            html = create_graph_visualization(relationships)
            components.html(html, height=800, scrolling=False)
            st.info(f"Displaying {len(relationships)} relationships")
        else:
            st.warning("No data found in the graph")
    else:
        st.error("Could not connect to Neo4j. Check your .env file and Neo4j server.")

if __name__ == "__main__":
    main()