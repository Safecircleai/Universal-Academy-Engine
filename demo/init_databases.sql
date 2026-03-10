-- UAE Multi-Node Demo: Initialize two separate databases
CREATE DATABASE uae_node_a;
CREATE DATABASE uae_node_b;
GRANT ALL PRIVILEGES ON DATABASE uae_node_a TO uae;
GRANT ALL PRIVILEGES ON DATABASE uae_node_b TO uae;
