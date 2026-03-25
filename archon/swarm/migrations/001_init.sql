CREATE TABLE IF NOT EXISTS swarm_migrations (
  id TEXT PRIMARY KEY,
  applied_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS task_history (
  task_id TEXT PRIMARY KEY,
  goal TEXT NOT NULL,
  agent_manifest_json TEXT NOT NULL,
  result_text TEXT NOT NULL,
  success INTEGER NOT NULL,
  duration_seconds REAL NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_performance (
  skill_name TEXT PRIMARY KEY,
  success_count INTEGER NOT NULL,
  failure_count INTEGER NOT NULL,
  avg_confidence REAL NOT NULL,
  last_used REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS spawn_patterns (
  goal_type TEXT PRIMARY KEY,
  pattern_json TEXT NOT NULL,
  success_rate REAL NOT NULL,
  sample_count INTEGER NOT NULL,
  last_used REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS goal_embeddings (
  task_id TEXT PRIMARY KEY,
  goal TEXT NOT NULL,
  embedding_json TEXT NOT NULL
);
