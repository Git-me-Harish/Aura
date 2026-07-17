-- AURA — real knowledge corpus + knowledge graph seed.
-- Replaces the in-memory KG dict and the hard-coded _seed docs in knowledge.py.
-- Loaded automatically by docker-compose as /docker-entrypoint-initdb.d/003_knowledge_seed.sql.

-- ──────────────────────────────────────────────────────────────────────────
-- Knowledge docs (RAG corpus)
-- ──────────────────────────────────────────────────────────────────────────
INSERT INTO knowledge_docs (doc_id, title, text, tags) VALUES
    ('doc_ppo',     'Proximal Policy Optimization',
     'PPO clips the policy update ratio to a small range (typically [1-eps, 1+eps]), preventing destructive updates. It is the workhorse algorithm for recommendation policy training because it is sample-efficient and stable under off-policy data when paired with importance sampling.',
     ARRAY['rl','policy-gradient','recommendation']),
    ('doc_bge',      'BGE Embeddings Family',
     'BGE-M3 supports dense, sparse, and multi-vector retrieval in one model. BGE-small-en-v1.5 is the lightweight 384-dim variant, ideal for CPU inference and small-footprint deployments. Both are released by BAAI under a permissive license.',
     ARRAY['embeddings','retrieval','bge']),
    ('doc_qdrant',   'Qdrant Vector DB',
     'Qdrant supports payload filtering with hybrid BM25 + dense search in a single query. The async client (qdrant_client.AsyncQdrantClient) is preferred for FastAPI workloads because it does not block the event loop. Collections can be sharded for horizontal scale.',
     ARRAY['vector-db','retrieval','qdrant']),
    ('doc_mcp',      'Model Context Protocol',
     'MCP standardizes how LLMs call external tools and data sources. AURA implements MCP-style tool handlers for Spotify, Google Calendar, GitHub, OpenWeather, and NewsAPI. Each handler returns a normalized JSON shape so the rest of the system is tool-agnostic.',
     ARRAY['mcp','tools','integration']),
    ('doc_ndcg',     'NDCG: Normalized Discounted Cumulative Gain',
     'NDCG measures ranking quality, emphasizing highly relevant items appearing early in the list. Range [0,1], higher is better. It is the primary offline metric for the AURA Recommendation Agent alongside Precision@K and MAP.',
     ARRAY['metrics','ranking','evaluation']),
    ('doc_sb3',      'stable-baselines3',
     'stable-baselines3 provides PPO, DQN, A2C, SAC implementations. AURA wraps it with a custom Gymnasium env (AuraRecEnv) that emits per-user state vectors and ingests real user-action rewards. Policy snapshots are saved as zip artifacts and logged to MLflow.',
     ARRAY['rl','pytorch','sb3']),
    ('doc_mlflow',   'MLflow Tracking',
     'MLflow tracks experiments, params, metrics, and artifacts. AURA logs every policy update with reward, samples_seen, and policy_version. The MLflow Model Registry is used to promote policy versions from staging to production.',
     ARRAY['mlops','tracking','mlflow']),
    ('doc_groq',     'Groq Inference API',
     'Groq offers free-tier OpenAI-compatible inference for Llama-3.3-70B-Versatile and Llama-3.1-8B-Instant. The LPU hardware delivers very low latency. AURA uses Groq as the primary LLM provider, falling back to HuggingFace Inference API when quota is exhausted.',
     ARRAY['llm','groq','inference']),
    ('doc_nextauth', 'NextAuth.js',
     'NextAuth.js issues JWT session tokens that AURA''s FastAPI backend validates with python-jose using the shared NEXTAUTH_SECRET. This enables multi-user auth without a separate IdP. Custom JWT callbacks embed user_id, timezone, and preferred_language in the token payload.',
     ARRAY['auth','jwt','nextauth']),
    ('doc_lightfm',  'LightFM Hybrid Recommender',
     'LightFM is a Python implementation of hybrid matrix factorization. It supports user and item content features alongside collaborative signals, and supports WARP, BPR, and logistic losses. AURA uses LightFM as a candidate generator with item tags as content features.',
     ARRAY['recsys','lightfm','cf']),
    ('doc_neural_cf','Neural Collaborative Filtering',
     'Neural CF (He et al. 2017) replaces the dot-product of classical MF with a neural architecture combining GMF (generalized MF) and MLP (multi-layer perceptron) branches. AURA implements NCF in PyTorch and trains it on the real interactions table.',
     ARRAY['recsys','pytorch','ncf']),
    ('doc_clickhouse','ClickHouse for Event Logging',
     'ClickHouse is a columnar OLAP database purpose-built for high-throughput append-only event logs. AURA writes every user action, RL experience, and policy update to ClickHouse for sub-second analytical queries on the metrics dashboard.',
     ARRAY['olap','events','clickhouse']),
    ('doc_kafka',    'Kafka Event Streaming',
     'Kafka is a partitioned, replicated log. AURA uses it as the durable backbone of the event bus: user actions are produced to the aura.user_actions topic, consumed by the RL pipeline, and persisted to ClickHouse for replay. KRaft mode removes the Zookeeper dependency.',
     ARRAY['streaming','kafka','events']),
    ('doc_redis_pubsub', 'Redis Pub/Sub for WebSocket Fan-out',
     'When AURA runs behind a load balancer with multiple FastAPI workers, each worker only sees its own WebSocket subscribers. Redis pub/sub bridges them: every worker publishes WS events to a shared channel and subscribes to relay broadcasts to its local clients.',
     ARRAY['redis','pubsub','websocket'])
ON CONFLICT (doc_id) DO NOTHING;

-- ──────────────────────────────────────────────────────────────────────────
-- Knowledge graph entities
-- ──────────────────────────────────────────────────────────────────────────
INSERT INTO kg_entities (entity, relations) VALUES
    ('PPO',                   '{"is_a": ["policy_gradient_algorithm"], "competes_with": ["SAC", "DQN"], "used_for": ["recommendation_policy"], "improves": ["sample_efficiency"]}'::jsonb),
    ('BGE-M3',                '{"is_a": ["embedding_model"], "supports": ["multilingual", "long_context"]}'::jsonb),
    ('BGE',                   '{"is_a": ["embedding_model_family"], "includes": ["bge-small", "bge-base", "bge-m3"]}'::jsonb),
    ('Qdrant',                '{"is_a": ["vector_db"], "supports": ["hybrid_search", "metadata_filtering"]}'::jsonb),
    ('MCP',                   '{"is_a": ["protocol"], "connects": ["LLM", "external_tools"]}'::jsonb),
    ('Multi-agent',           '{"pattern": ["orchestrator"], "benefits": ["separation_of_concerns", "parallelism"]}'::jsonb),
    ('NDCG',                  '{"is_a": ["ranking_metric"], "range": ["0_to_1"], "higher_is": ["better"]}'::jsonb),
    ('stable-baselines3',     '{"is_a": ["rl_library"], "supports": ["PPO", "DQN", "A2C", "SAC"]}'::jsonb),
    ('MLflow',                '{"is_a": ["mlops_platform"], "supports": ["experiment_tracking", "model_registry"]}'::jsonb),
    ('Groq',                  '{"is_a": ["llm_inference_provider"], "models": ["llama-3.3-70b", "llama-3.1-8b"]}'::jsonb),
    ('NextAuth',              '{"is_a": ["auth_library"], "framework": ["Next.js"], "supports": ["oauth", "jwt"]}'::jsonb),
    ('LightFM',               '{"is_a": ["hybrid_cf_library"], "supports": ["warp", "bpr", "logistic"], "uses": ["content_features"]}'::jsonb),
    ('NeuralCF',              '{"is_a": ["deep_recsys_model"], "combines": ["gmf", "mlp"], "implemented_in": ["pytorch"]}'::jsonb),
    ('ClickHouse',            '{"is_a": ["columnar_olap_db"], "used_for": ["event_logging", "analytics"]}'::jsonb),
    ('Kafka',                 '{"is_a": ["distributed_log"], "used_for": ["event_streaming"], "supports": ["kraft_mode"]}'::jsonb),
    ('Redis',                 '{"is_a": ["in_memory_db"], "supports": ["pubsub", "cache", "rate_limiting"]}'::jsonb)
ON CONFLICT (entity) DO NOTHING;
