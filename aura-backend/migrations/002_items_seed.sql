-- AURA — real item catalog seed.
-- These are real, descriptive rows the Recommendation Agent ranks against.
-- Loaded automatically by docker-compose as /docker-entrypoint-initdb.d/002_items_seed.sql.

INSERT INTO items (item_id, title, category, description, tags) VALUES
    ('it_ppo_refactor',   'PPO Trainer Refactor',          'tech',     'Refactor the PPO trainer to support distributed rollout and gradient accumulation across multiple GPUs.',             ARRAY['ml','rl','pytorch','engineering']),
    ('it_qdrant_guide',   'Qdrant Hybrid Search Guide',    'tech',     'Walkthrough of BM25 sparse + dense retrieval on Qdrant with payload filtering and re-ranking.',                       ARRAY['vector-db','rag','search','qdrant']),
    ('it_mlflow_track',   'MLflow Tracking Best Practices','tech',     'How to log params, metrics, and artifacts for distributed RL training with MLflow.',                                 ARRAY['mlops','mlflow','rl','tracking']),
    ('it_m83_midnight',   'Midnight City — M83',           'music',    'Synthwave classic from 2011; the slow build matches an evening focus session.',                                       ARRAY['synthwave','electronic','focus']),
    ('it_strobe',         'Strobe — Deadmau5',             'music',    'Ten-minute progressive house build; ideal for deep-work blocks.',                                                      ARRAY['progressive-house','electronic','focus']),
    ('it_xx_intro',       'Intro — The xx',                'music',    'Minimal indie pop; low-BPM atmospheric background for reading.',                                                       ARRAY['indie','minimal','reading']),
    ('it_dune_two',       'Dune: Part Two',                'movies',   'Denis Villeneuve sequel; long-form sci-fi matching the user''s weekend binge pattern.',                               ARRAY['sci-fi','drama','long-form']),
    ('it_indie_scifi',    'Indie Sci-Fi Shorts',           'movies',   'Curated playlist of independent sci-fi short films under 20 minutes each.',                                          ARRAY['sci-fi','indie','short-form']),
    ('it_morning_5k',     'Morning 5K — Cubbon Park',      'fitness',  '5K route through Cubbon Park; ideal weather window 6:00–7:00 AM, low traffic.',                                      ARRAY['running','outdoor','morning']),
    ('it_strength_45',    '45-min Strength Session',       'fitness',  'Compound lifts + accessory work; fits a lunch-break window.',                                                          ARRAY['strength','gym','short']),
    ('it_coffee_eth',     'Single-Origin Ethiopian',       'food',     'Washed Yirgacheffe from a local roaster; bright citrus, light body, fresh batch roasted yesterday.',                  ARRAY['coffee','specialty','single-origin']),
    ('it_pasta_recipe',   'Weeknight Pasta Recipe',        'food',     '30-minute garlic-olive-oil spaghetti with chili and parsley; pantry-friendly.',                                       ARRAY['cooking','recipe','quick']),
    ('it_ddia_book',      'Designing Data-Intensive Apps', 'books',    'Martin Kleppmann''s deep dive into distributed systems, replication, and consistency — reinforces long-term interest.',ARRAY['distributed-systems','databases','engineering']),
    ('it_arrival_film',   'Arrival (Film Study)',          'books',    'Linguistics-meets-sci-fi; pairs well with the user''s pattern of weekend long-form viewing.',                          ARRAY['sci-fi','linguistics','film-study']),
    ('it_nvda_earnings',  'NVDA — Earnings Tomorrow',      'finance',  'Earnings call at 6 PM IST; current holding, options implied move ~7%.',                                                ARRAY['equities','earnings','event-driven']),
    ('it_index_rebal',    'Index Rebalance Alert',        'finance',  'Quarterly Russell 1000 rebalance: 23 additions, 18 deletions; passive flow window.',                                  ARRAY['index-funds','rebalance','macro']),
    ('it_aura_spec',      'AURA Architecture Spec v0.3',   'tech',     'Open the architecture document last edited yesterday; recommender system design notes.',                              ARRAY['docs','aura','architecture']),
    ('it_kg_walkthrough', 'Knowledge Graph Walkthrough',   'tech',     'How AURA''s in-Postgres KG (kg_entities table) improves factual recall over flat RAG.',                              ARRAY['kg','rag','aura'])
ON CONFLICT (item_id) DO NOTHING;
