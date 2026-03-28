# WhaleSwarm — Product Requirements Document
## Universal Swarm Intelligence Engine: Document-to-Multi-Platform Simulation

**Version:** 1.0
**Date:** 2026-03-28
**Purpose:** A complete specification sufficient to build the system from scratch, including every architectural decision, algorithm, and design choice that contributes to the system's ability to simulate a swarm of agents simultaneously betting on a Polymarket market while participating in Reddit threads and Twitter posts — all grounded in a knowledge graph derived from real documents.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Core Architecture](#2-core-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Data Flow: End-to-End Pipeline](#4-data-flow-end-to-end-pipeline)
5. [Knowledge Graph Layer (GraphRAG)](#5-knowledge-graph-layer-graphrag)
6. [Agent Profile Generation](#6-agent-profile-generation)
7. [Simulation Configuration Generation](#7-simulation-configuration-generation)
8. [Simulation Engine](#8-simulation-engine)
9. [Platform Implementations](#9-platform-implementations)
10. [Cross-Platform Bridge Architecture](#10-cross-platform-bridge-architecture)
11. [Belief State System](#11-belief-state-system)
12. [Recommendation System](#12-recommendation-system)
13. [Report Agent (ReACT)](#13-report-agent-react)
14. [Backend API Layer](#14-backend-api-layer)
15. [Frontend Architecture](#15-frontend-architecture)
16. [Configuration System](#16-configuration-system)
17. [Storage Architecture](#17-storage-architecture)
18. [Performance Architecture](#18-performance-architecture)
19. [Key Design Decisions and Rationale](#19-key-design-decisions-and-rationale)
20. [File Structure Reference](#20-file-structure-reference)

---

## 1. System Overview

WhaleSwarm is a **Universal Swarm Intelligence Engine** that:

1. Ingests documents (PDF/MD/TXT) describing a real-world topic
2. Builds a **knowledge graph** (Neo4j) of entities and relationships from those documents
3. Derives **agent personas** from graph entities — each agent is a real-world "account" (politician, journalist, student, company, etc.) that could plausibly speak on social media
4. Runs those agents **simultaneously** across three simulated platforms:
   - **Twitter** — short posts, likes, reposts, quote-posts, follows
   - **Reddit** — posts, comments, up/downvotes, search, trending
   - **Polymarket** — prediction market with real AMM pricing, portfolios, trades
5. Agents on all three platforms share a **cross-platform information bridge** — Twitter/Reddit sentiment influences Polymarket prices and vice versa
6. Generates an **analytical report** using a ReACT agent that queries the knowledge graph and simulation data
7. Exposes an **interactive chatbot** to interview individual simulation agents post-hoc

The key insight: agents are not random. They are grounded in the knowledge graph. A CEO agent knows their company's relationships. A journalist agent writes from the perspective their bio implies. Their beliefs evolve round-by-round via a heuristic belief state system.

---

## 2. Core Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Frontend (Vue.js 3)                      │
│  Step1: Upload → Step2: Agents → Step3: Simulate → Step4: Report │
└──────────────────────────────┬──────────────────────────────────┘
                               │ REST API
┌──────────────────────────────▼──────────────────────────────────┐
│                    Backend (Python Flask)                          │
│                                                                    │
│  /api/graph    /api/simulation    /api/report                     │
│                                                                    │
│  ┌────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ OntologyGen    │  │ ProfileGenerator │  │  ReportAgent     │  │
│  │ GraphBuilder   │  │ SimConfigGen     │  │  GraphTools      │  │
│  │ EntityReader   │  │ SimulationRunner │  │  (InsightForge,  │  │
│  │                │  │ SimulationMgr    │  │   PanoramaSearch)│  │
│  └───────┬────────┘  └────────┬─────────┘  └──────────────────┘  │
│          │                   │                                     │
│  ┌───────▼───────────────────▼─────────────────────────────────┐ │
│  │              Neo4j Storage (GraphStorage interface)           │ │
│  │  Nodes: Entity+Type labels, embeddings, summaries            │ │
│  │  Edges: Relationships with facts                             │ │
│  └───────────────────────────────────────────────────────────── ┘ │
└──────────────────────────────┬──────────────────────────────────┘
                               │ subprocess spawn
┌──────────────────────────────▼──────────────────────────────────┐
│              Simulation Engine (OASIS fork)                                 │
│                                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Twitter      │  │ Reddit       │  │ Polymarket            │   │
│  │ Platform     │  │ Platform     │  │ Platform + AMM        │   │
│  │ (SQLite)     │  │ (SQLite)     │  │ (SQLite + AMM math)   │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         │                 │                      │               │
│  ┌──────▼─────────────────▼──────────────────────▼────────────┐  │
│  │              Channel (async message queue)                   │  │
│  └──────────────────────────┬───────────────────────────────── ┘  │
│                             │                                      │
│  ┌──────────────────────────▼───────────────────────────────────┐ │
│  │              AgentGraph (N SocialAgents)                      │ │
│  │  Each agent: CAMEL-AI ChatAgent + BeliefState + tools         │ │
│  └───────────────────────────────────────────────────────────── ┘ │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Technology Stack

| Layer | Technology | Version/Notes |
|---|---|---|
| **Backend** | Python | 3.11+ |
| **Web Framework** | Flask | CORS enabled, blueprint architecture |
| **Graph Database** | Neo4j Community | bolt://localhost:7687, self-hosted |
| **Neo4j Driver** | neo4j-python-driver | Async-compatible |
| **Agent Framework** | CAMEL-AI | `camel.agents.ChatAgent` extended |
| **Simulation DB** | SQLite | One .db file per platform per simulation |
| **LLM Interface** | OpenAI-compatible API | Works with Ollama, OpenRouter, Anthropic |
| **Embeddings** | Ollama or OpenAI | `nomic-embed-text` local or `text-embedding-3-small` cloud |
| **ML/RecSys** | PyTorch, SentenceTransformers, sklearn | CUDA-optional |
| **Twitter RecSys Model** | `paraphrase-MiniLM-L6-v2` | SentenceTransformer, local |
| **Twitter RecSys (deep)** | `Twitter/twhin-bert-base` | HuggingFace Transformers |
| **Frontend** | Vue.js 3 | Composition API + Options API mixed |
| **Build Tool** | Vite | Proxies /api → :5001 |
| **Graph Visualization** | D3.js | Force-directed layout, live physics |
| **HTTP Client** | Axios | Retry logic built in |
| **Async Tasks** | ThreadPoolExecutor + asyncio | Python stdlib |
| **Concurrency (dev)** | concurrently (npm) | Starts both frontend+backend |

### LLM Provider Modes

The system supports multiple LLM backends via an OpenAI-compatible adapter:

1. **Cloud (OpenRouter)**: Route to any model via `https://openrouter.ai/api/v1`
2. **Local (Ollama)**: `http://localhost:11434/v1` — requires `qwen3.5:27b` or similar with 32k context
3. **Claude Code**: Special `claude-code` provider for `claude-sonnet-4`

**Smart Model (Dual-Model Routing)**: Intelligence-sensitive tasks (ontology, reports, graph reasoning) use `SMART_*` env vars pointing to a stronger model, while bulk tasks (NER, profile gen) use the primary cheaper/faster model. This is configured entirely in `.env`.

---

## 4. Data Flow: End-to-End Pipeline

### Step 1: Document Ingestion & Ontology Generation

1. User uploads 1+ files (PDF/MD/TXT) + writes a `simulation_requirement` string
2. Backend extracts text from files (PDF via pdfminer/pypdf, MD/TXT direct)
3. All text is concatenated into `extracted_text.txt` in the project directory
4. `OntologyGenerator` sends text + simulation_requirement to the **Smart LLM** with a detailed system prompt:
   - Must produce exactly 8-10 entity types (8 specific + up to 2 fallback generic)
   - Entity types must be real-world "accounts" that speak on social media (not abstract concepts)
   - 6-10 relationship types
   - Returns JSON: `{entity_types: [...], edge_types: [...], analysis_summary: "..."}`
5. Ontology is saved to `project.json`; project status advances to `ontology_generated`

**Critical ontology rule**: Entities must be social media actors. Examples: `Student`, `Professor`, `CEO`, `Company`, `Journalist`, `Politician`, `Organization`. NOT: `Topic`, `Viewpoint`, `Concept`, `Event`. The ontology drives NER in the next step — every extracted entity will be one of these types.

### Step 2: Knowledge Graph Construction

1. Text is chunked: default 500 chars, 50-char overlap (configurable per project)
2. Chunks are processed in parallel batches via `ThreadPoolExecutor`:
   - Each batch spawns N worker threads (configurable `batch_size`, default 5)
   - Each thread independently calls `storage.add_text(chunk, graph_id)`
3. `storage.add_text()` pipeline per chunk:
   a. Retrieve ontology for this graph (entity + edge type guidance)
   b. Call `NERExtractor` (LLM) to extract entities matching ontology types + relations
   c. For each entity: generate text embedding (Ollama or OpenAI)
   d. Write nodes and edges to Neo4j using batch UNWIND queries
4. Neo4j schema:
   - Each entity node: labels `[:Entity:TypeName]`, properties `uuid, name, summary, attributes (JSON), embedding (vector), graph_id`
   - Each edge: type `[:RELATIONSHIP]` with dynamic sub-label, properties `uuid, name, fact, source_node_uuid, target_node_uuid, created_at`
   - Indexes on `graph_id`, `uuid`, `name` for fast lookup
5. Graph building runs as a background thread; Flask task manager tracks progress via `task_id`

**Batch UNWIND optimization**: Instead of one Neo4j transaction per entity (N transactions), entities are batched and inserted with a single UNWIND query. This gives ~10x insertion speedup.

### Step 3: Agent Profile Generation

1. `EntityReader` queries Neo4j for all nodes with meaningful entity types (filters out bare `Entity` label nodes)
2. `OasisProfileGenerator` takes each entity + its related edges and generates a full agent profile:
   - Uses **graph degree as social metric scaling factor** — entities with more connections get higher follower/karma counts
   - Applies entity-type baseline metrics (see §6 for full table)
   - Generates `user_id, user_name, name, bio, persona, karma, friend_count, follower_count, statuses_count, risk_tolerance, age, gender, mbti, country, profession, interested_topics`
   - **Web enrichment**: if the entity is a public figure (politician, CEO) or has thin context (<150 chars), calls `WebEnricher` for additional background via LLM research (optionally Perplexity API for grounded web search)
3. Profiles are generated in parallel batches and saved as platform-specific JSON files
4. Profiles are converted to platform formats via `to_reddit_format()`, `to_twitter_format()`, `to_polymarket_format()`

### Step 4: Simulation Configuration Generation

The `SimulationConfigGenerator` produces four nested config objects via sequential LLM calls (to avoid long-context failures):

1. `TimeSimulationConfig` — how time maps to rounds
2. `EventConfig` — initial posts, scheduled events, hot topic keywords, market seed question
3. `AgentActivityConfig` (batched per agent) — activity level, post rate, stance, sentiment_bias
4. `PlatformConfig` — viral threshold, echo chamber strength, recommendation weights

### Step 5: Simulation Execution

1. Flask `SimulationRunner` spawns a **subprocess** running the the simulation engine engine
2. the simulation engine initializes three `BasePlatform` instances (Twitter, Reddit, Polymarket) each backed by their own SQLite database
3. All three platforms run concurrently via `asyncio.gather()`
4. Each round: agents are selected according to activity config, each agent calls `perform_action_by_llm()`, the LLM returns tool calls, tool calls are dispatched via `Channel` → platform action handlers → SQLite writes
5. Cross-platform bridge injects social context into Polymarket agent observations and market prices into social media agent context
6. Belief states update heuristically at end of each round
7. Actions are logged to `actions.jsonl`; Flask polls this file for real-time UI updates

### Step 6: Report Generation

`ReportAgent` uses a ReACT (Reason-Act-Observe) loop with three graph retrieval tools to generate a structured markdown report, citing actual simulation actions and graph entities.

---

## 5. Knowledge Graph Layer (GraphRAG)

### 5.1 Purpose

The knowledge graph is the backbone of the entire simulation. It stores:
- Who the relevant entities are in the document domain
- What relationships exist between them
- The semantic content of each entity (embedding for similarity search)

This is what distinguishes WhaleSwarm from generic agent simulations: every agent is *grounded* in real extracted knowledge.

### 5.2 Storage: Neo4j Community Edition (Self-Hosted)

**Why Neo4j over Zep Cloud (the original)**:
- No cloud vendor lock-in, no API key dependency
- Free and open source (Community Edition)
- Local semantic search via embeddings stored in node properties
- Batch UNWIND queries for 10x insertion speed
- All data stays local — important for private document simulation

**Connection**: `bolt://localhost:7687`, default user `neo4j`, password in `.env`

### 5.3 Schema

```cypher
// Graph metadata node
(:Graph {
  graph_id: string,
  name: string,
  ontology_json: string,  // full ontology as JSON string
  created_at: datetime
})

// Entity node (multi-label)
(:Entity:Student {  // example — TypeName comes from ontology
  uuid: string,
  name: string,
  summary: string,       // LLM-extracted description
  attributes: string,    // JSON object with extra properties
  embedding: list<float>,// vector from embedding model (768 dims by default)
  graph_id: string
})

// Relationship edge
(:Entity)-[:RELATIONSHIP {  // dynamic sub-type from ontology
  uuid: string,
  name: string,           // e.g., "WORKS_FOR"
  fact: string,           // natural language: "Alice works for Acme Corp"
  source_node_uuid: string,
  target_node_uuid: string,
  created_at: datetime,
  valid_at: datetime,     // temporal (optional)
  invalid_at: datetime,   // when relationship ended (optional)
  expired_at: datetime    // when fact became stale (optional)
}]->(:Entity)
```

### 5.4 NER Extraction

`NERExtractor` receives:
- A text chunk
- The ontology (entity types + edge types to look for)

It returns JSON:
```json
{
  "entities": [
    {"name": "Alice Chen", "type": "Professor", "summary": "AI researcher at MIT focusing on NLP", "attributes": {"institution": "MIT", "field": "NLP"}},
    ...
  ],
  "relations": [
    {"source": "Alice Chen", "target": "MIT", "type": "WORKS_AT", "fact": "Alice Chen is a professor at MIT"}
  ]
}
```

The ontology-guided extraction ensures entities match the simulation's domain — if you upload a corporate document, you get company/CEO/employee entities; if you upload a policy document, you get politician/organization/advocacy group entities.

### 5.5 Embedding Strategy

- Default: Ollama with `nomic-embed-text` (768 dimensions, local)
- Alternative: OpenAI `text-embedding-3-small` (1536 dim, cloud)
- `EMBEDDING_DIMENSIONS` config must match the model
- Embeddings stored as node property (vector array)
- Used for semantic similarity search during report generation

### 5.6 Graph Search Methods (GraphToolsService)

Three retrieval tools, each with increasing power and latency:

#### QuickSearch
- Simple semantic search on entity summaries
- Embeds query, compute cosine similarity against all entity embeddings
- Returns top-K nodes with matching facts
- Use case: "Find all nodes related to X"

#### PanoramaSearch (Breadth)
- Get comprehensive view of a topic
- Fetches all matching nodes including temporal (expired) edges
- Returns full relationship chains
- Use case: "Give me everything connected to this entity"

#### InsightForge (Deep, most powerful)
- Multi-dimensional hybrid retrieval
- Step 1: Smart LLM generates 3-5 sub-questions from the main query
- Step 2: For each sub-question: semantic search + graph traversal
- Step 3: Collect semantic facts, entity insights, relationship chains
- Step 4: Return integrated multi-dimensional result
- Use case: Report sections, complex analytical questions

**InsightForgeResult fields**:
```python
@dataclass
class InsightForgeResult:
    query: str
    simulation_requirement: str
    sub_queries: List[str]
    semantic_facts: List[str]           # from embedding search
    entity_insights: List[Dict]         # per-entity detailed info
    relationship_chains: List[str]      # graph traversal paths
```

---

## 6. Agent Profile Generation

### 6.1 OasisAgentProfile Dataclass

```python
@dataclass
class OasisAgentProfile:
    user_id: str
    user_name: str         # @handle
    name: str              # Display name
    bio: str               # Short biography
    persona: str           # Detailed character description for LLM system prompt
    karma: int             # Reddit karma or Twitter score
    friend_count: int      # Following count
    follower_count: int    # Followers count
    statuses_count: int    # Historical post count
    risk_tolerance: str    # "conservative" | "moderate" | "aggressive" (Polymarket)
    age: int
    gender: str
    mbti: str              # Myers-Briggs type e.g. "INTJ"
    country: str
    profession: str
    interested_topics: List[str]
    source_entity_uuid: str  # Links back to the Neo4j node this agent was derived from
```

### 6.2 Social Metrics Derivation from Graph

Agent social metrics are not random — they are derived from graph topology:
- **Graph degree** = number of edges the entity has in the knowledge graph
- Degree is used as a scaling factor applied to entity-type baselines

**Baseline metrics by entity type** (approximate):

| Entity Type | Karma | Followers | Friend Count | Posts |
|---|---|---|---|---|
| MediaOutlet | 15,000 | 50,000 | 500 | 10,000 |
| Journalist | 8,000 | 20,000 | 1,000 | 8,000 |
| CEO | 5,000 | 15,000 | 500 | 3,000 |
| Politician | 10,000 | 30,000 | 800 | 5,000 |
| Organization | 12,000 | 40,000 | 600 | 7,000 |
| Professor | 3,000 | 5,000 | 800 | 4,000 |
| Company | 8,000 | 25,000 | 400 | 6,000 |
| Student | 800 | 300 | 400 | 500 |
| Person | 1,500 | 1,000 | 500 | 2,000 |

Entities with high graph degree get a multiplier (e.g., 1.5x to 3x) applied to these baselines.

### 6.3 Web Enrichment

Trigger conditions:
- Entity type is in `{"Politician", "CEO", "PublicFigure", "Celebrity"}`
- OR entity summary is very short (<150 characters)

When triggered: calls `WebEnricher.enrich(entity_name, entity_type, existing_summary)`

Two modes:
1. **LLM knowledge** (default): Prompts the LLM with "What do you know about {name}?"
2. **Grounded search** (optional): If `WEB_SEARCH_MODEL` is set (e.g., `perplexity/sonar-pro`), routes this call to a web-search-capable model

Result is merged into the entity's profile/persona field.

### 6.4 Platform-Specific Format Conversion

```python
def to_reddit_format(self) -> Dict:
    return {
        "user_id": self.user_id,
        "username": self.user_name,
        "realname": self.name,
        "bio": self.bio,
        "persona": self.persona,
        "karma": self.karma,
        "mbti": self.mbti,
        "gender": self.gender,
        "age": self.age,
        "country": self.country,
    }

def to_twitter_format(self) -> Dict:
    return {
        "user_id": self.user_id,
        "username": self.user_name,
        "name": self.name,
        "description": self.bio,
        "user_char": self.persona,     # used as 'user_char' in CSV
        "following_count": self.friend_count,
        "followers_count": self.follower_count,
        "statuses_count": self.statuses_count,
        # "following_agentid_list" and "previous_tweets" are seeded separately
    }

def to_polymarket_format(self) -> Dict:
    return {
        "user_id": self.user_id,
        "user_name": self.user_name,
        "risk_tolerance": self.risk_tolerance,
        "user_profile": self.persona,
    }
```

---

## 7. Simulation Configuration Generation

`SimulationConfigGenerator` produces config through 4 sequential LLM steps. Sequential (not parallel) to avoid token overflows and ensure later steps can reference earlier ones.

### 7.1 TimeSimulationConfig

```python
@dataclass
class TimeSimulationConfig:
    total_simulation_hours: int      # e.g., 24 (simulated hours to run)
    minutes_per_round: int           # e.g., 30 (real minutes per simulated hour)
    agents_per_hour: int             # how many agents activate each round
    peak_hours: List[int]            # e.g., [19, 20, 21, 22] (simulated hour)
    off_peak_hours: List[int]        # e.g., [0, 1, 2, 3, 4, 5]
    peak_multiplier: float           # e.g., 1.5
    off_peak_multiplier: float       # e.g., 0.05
    work_hour_multiplier: float      # e.g., 0.7
    evening_multiplier: float        # e.g., 1.2
```

Activity model is **China-timezone based** (inherited from OASIS):
- Dead hours 0-5: 0.05x activity
- Morning 6-8: 0.4x
- Work hours 9-18: 0.7x
- Evening 19-22: 1.5x (peak)
- Night 23: 0.8x

### 7.2 EventConfig

```python
@dataclass
class EventConfig:
    initial_posts: List[str]         # seed posts injected at round 0
    scheduled_events: List[Dict]     # {"hour": int, "event": str, "platform": str}
    hot_topic_keywords: List[str]    # keywords that boost content spread
    market_question: str             # the Polymarket question to seed
    market_initial_probability: float # initial YES probability (0.0-1.0)
    market_outcome_a: str            # e.g., "YES" or custom
    market_outcome_b: str            # e.g., "NO" or custom
```

### 7.3 AgentActivityConfig (per agent)

```python
@dataclass
class AgentActivityConfig:
    agent_id: str
    activity_level: str              # "high" | "medium" | "low" | "lurker"
    posts_per_hour: float            # average posts per simulated hour
    comments_per_hour: float         # average comments per simulated hour
    active_hours: List[int]          # hours when this agent is most active
    response_delay: int              # rounds before responding to events
    sentiment_bias: float            # -1.0 to 1.0, initial lean
    stance: str                      # "supportive"|"opposing"|"neutral"|"observer"|"strongly_supportive"|"strongly_opposing"
    influence_weight: float          # how much this agent's posts amplify
```

### 7.4 PlatformConfig

```python
@dataclass
class PlatformConfig:
    viral_threshold: int             # likes needed for viral spread
    echo_chamber_strength: float     # 0.0-1.0, how much like-minded content is boosted
    recommendation_weights: Dict     # weights for different recsys factors
    max_rec_post_len: int            # max posts shown per agent per round (default 30)
    recsys_type: str                 # "twitter" | "twhin" | "reddit" | "random"
```

---

## 8. Simulation Engine

The simulation engine is a fork of CAMEL-AI's OASIS framework, extended with:
- Generic simulation support (not just social media)
- Polymarket prediction market platform
- Cross-platform information bridge
- Belief state system
- Round analyzer

### 8.1 Core Abstractions

**`BasePlatform`** (abstract, `simulations/base.py`):
- Manages SQLite database lifecycle (schemas, init)
- Runs the async message loop: `await channel.receive_from()` → dispatch to handler
- Action dispatch via `getattr(self, action_name)` — any `async def` method becomes a callable action
- Core schemas: `user.sql`, `trace.sql` (shared across all simulations)
- Subclass-specific schemas declared in `required_schemas: list[str]`

**`BaseAction`** (abstract):
- Agent-side interface for calling platform actions
- Each public async method auto-discovered as an LLM-callable tool via `get_openai_function_list()`
- Uses `FunctionTool` from CAMEL-AI to expose methods as OpenAI-compatible tool definitions
- Sends messages via `Channel` (async queue): `await self.channel.write_to_receive_queue((agent_id, message, action_type))`

**`BaseEnvironment`** (abstract):
- Converts platform state to text prompt for agent's LLM
- Receives `extra_observation_context` (cross-platform bridge injects this)
- `async def to_text_prompt() -> str` — called before each agent action

**`BasePromptBuilder`** (abstract):
- `build_system_prompt(user_info) -> str`
- Each platform has its own implementation

**`SimulationConfig`** (dataclass):
```python
@dataclass
class SimulationConfig:
    name: str
    platform_cls: type[BasePlatform]
    action_cls: type[BaseAction]
    environment_cls: type[BaseEnvironment]
    prompt_builder: BasePromptBuilder
    default_actions: list[str]       # restricted action list
    platform_kwargs: dict            # passed to platform constructor
```

### 8.2 SocialAgent (extends CAMEL-AI ChatAgent)

```python
class SocialAgent(ChatAgent):
    social_agent_id: int
    user_info: UserInfo              # name, bio, persona, social metrics
    channel: Channel                 # async message queue
    env: BaseEnvironment             # current observation context
    action_tools: List[FunctionTool] # LLM-callable tools
    agent_graph: AgentGraph          # social network graph
    max_iteration: int               # max tool calls per turn (default 1)
    interview_record: bool           # record interviews to memory
```

**LLM scheduling strategy**: `'random_model'` — if multiple model backends provided, randomly selects one per call. This enables load balancing across Ollama instances or OpenAI keys.

**Two initialization paths**:
1. Legacy (social media): SocialAction + SocialEnvironment
2. Generic: Accepts `SimulationConfig` object

**Key methods**:
- `perform_action_by_llm()`: observes env → LLM call → tool calls dispatched
- `perform_interview(prompt)`: direct Q&A without full action cycle (optionally records to memory)
- `perform_test()`: "Helen is a writer" group polarization test (research evaluation)
- `perform_agent_graph_action()`: sync follow/unfollow edges in AgentGraph

### 8.3 Channel (Async Message Queue)

`Channel` is the communication backbone between agents and platforms:
- `write_to_receive_queue(data)` → returns `message_id`
- `read_from_send_queue(message_id)` → awaits response
- Bidirectional: agents write requests, platform writes responses
- Enables fully async agent-platform interaction without polling

### 8.4 AgentGraph

Directed graph of agents (NetworkX-backed or Neo4j-backed):
- `add_agent(agent)`, `get_agent(id)`, `get_agents()`: agent registry
- `add_edge(from_id, to_id)`, `remove_edge(from_id, to_id)`: follow relationships
- `get_num_nodes()`: count
- Social network evolves during simulation as agents follow/unfollow

### 8.5 Clock

```python
class Clock:
    def __init__(self, time_acceleration: int):  # e.g., 60 = 1 min real = 1 hr simulated
    def time_transfer(self, now: datetime, start: datetime) -> datetime:
        # Returns simulated timestamp
```

SQLite timestamps use simulated time — trace records reflect the simulated hour, not real clock.

### 8.6 Round Execution Flow

```
Round N begins
├── Determine active agents (based on AgentActivityConfig + current simulated hour)
├── For each active agent (concurrent):
│   ├── Inject cross-platform context into agent.env.extra_observation_context
│   ├── Inject belief state into agent system message
│   ├── agent.perform_action_by_llm()
│   │   ├── await env.to_text_prompt()  →  constructs observation string
│   │   ├── BaseMessage(observation) sent to CAMEL ChatAgent
│   │   ├── LLM returns tool calls (action_name + args)
│   │   ├── Each tool call → action.perform_action(message, action_type)
│   │   │   → channel.write_to_receive_queue(...)
│   │   │   → platform receives message
│   │   │   → platform dispatches to handler (getattr(self, action_name))
│   │   │   → SQLite write
│   │   │   → channel.send_to(result)
│   │   └── Return response with tool_calls info
│   └── Log action to actions.jsonl
├── Update recommendation matrices (platform-specific recsys)
├── Update belief states (heuristic, no LLM calls)
├── Compact old rounds into memory summary (background thread)
└── Round N ends
```

---

## 9. Platform Implementations

### 9.1 Twitter Platform

**SQLite schemas**: `user.sql`, `post.sql`, `like.sql`, `follow.sql`, `mute.sql`, `repost.sql`, `quote_post.sql`, `trace.sql`

**Available actions**:
- `create_post(content: str)`: Creates tweet (<280 chars enforced in prompt, not code)
- `like_post(post_id: int)`: Like a post
- `unlike_post(post_id: int)`: Remove like
- `repost(post_id: int)`: Repost without comment
- `quote_post(post_id: int, content: str)`: Repost with comment
- `follow(followee_id: int)`: Follow a user
- `unfollow(followee_id: int)`: Unfollow
- `mute(user_id: int)`: Mute a user (no more of their content in feed)
- `do_nothing()`: Skip turn

**System prompt template** (TwitterPromptBuilder):
```
# WHO YOU ARE
You are a real person on Twitter...
{name_string}
{description_string (from persona)}

# HOW TWITTER WORKS
[feed mechanics, 280 char limit, retweet culture]

# HOW TO DECIDE WHAT TO DO
DEFAULT: do_nothing
create_post: only when you have something original...
LIKE_POST: agree but nothing to add...
REPOST: amplify...
QUOTE_POST: add take on someone else's tweet...
follow: when you're genuinely interested...
do_nothing: YOUR DEFAULT...
```

**Recommendation system**: Personalized via SentenceTransformer (`paraphrase-MiniLM-L6-v2`) or TWHIN-BERT. User bio + recent posts encoded, cosine similarity against all posts, top-K shown. Optionally incorporates like history.

### 9.2 Reddit Platform

**SQLite schemas**: `user.sql`, `post.sql`, `comment.sql`, `like.sql`, `dislike.sql`, `follow.sql`, `mute.sql`, `report.sql`, `trace.sql`

**Available actions**:
- `create_post(title: str, content: str)`: Create a new post (subreddit implied)
- `create_comment(post_id: int, content: str)`: Comment on a post
- `like_post(post_id: int)`: Upvote
- `dislike_post(post_id: int)`: Downvote
- `like_comment(comment_id: int)`: Upvote comment
- `dislike_comment(comment_id: int)`: Downvote comment
- `search_posts(query: str)`: Search posts by keyword
- `search_user(username: str)`: Find a user
- `trend()`: Get trending posts
- `refresh()`: Refresh feed
- `follow(user_id: int)`: Follow a user
- `mute(user_id: int)`: Mute
- `report(post_id: int, reason: str)`: Report a post
- `do_nothing()`: Skip turn

**Recommendation system**: Reddit-style hot score algorithm:
```python
def calculate_hot_score(num_likes, num_dislikes, created_at):
    s = num_likes - num_dislikes
    order = log(max(abs(s), 1), 10)
    sign = 1 if s > 0 else -1 if s < 0 else 0
    seconds = epoch_seconds(created_at) - 1134028003  # Reddit epoch
    return round(sign * order + seconds / 45000, 7)
```
Posts sorted by hot score, top `max_rec_post_len` shown to all users.

**System prompt template** (RedditPromptBuilder): Similar structure to Twitter but with Reddit-specific formatting (titles, comments vs posts, upvotes/downvotes instead of likes/reposts).

### 9.3 Polymarket Platform

**SQLite schemas**: `user.sql`, `portfolio.sql`, `position.sql`, `market.sql`, `trade.sql`, `comment.sql`, `trace.sql`

**Platform initialization**:
```python
class PolymarketPlatform(BasePlatform):
    def __init__(self, db_path, channel, initial_balance=1000.0, initial_liquidity=10000.0,
                 real_clob_price: float = None):
```
- `initial_balance`: Each agent starts with $1,000 in cash
- `initial_liquidity`: AMM pool starts with $10,000 in reserves
- `real_clob_price`: If provided, the AMM reserves are reset to this price at the start of each round (see 9.5 Real-Price Anchoring).

**Available actions**:
- `sign_up()`: Register agent, create portfolio with initial_balance
- `create_market(question, outcome_a, outcome_b, initial_probability)`: Create prediction market
  - Sets AMM reserves: `k = liq^2`, then solve for reserves to achieve initial_probability
  - `price_a = reserve_b / (reserve_a + reserve_b) = initial_probability`
  - Therefore: `reserve_a = liq * sqrt((1 - p) / p)`, `reserve_b = liq * sqrt(p / (1 - p))`
- `buy_shares(market_id, outcome, amount_usd)`: Buy outcome shares
  - Validates balance, validates market open, validates outcome
  - Caps trade at **2% of pool reserves** to prevent manipulation
  - Calls `amm.quote_buy()` for execution price
  - Updates reserves, deducts balance, adds position, records trade
- `sell_shares(market_id, outcome, shares)`: Sell shares for USD
  - Calls `amm.quote_sell()` for execution price
  - Updates reserves, adds balance, reduces position, records trade
- `browse_markets()`: Returns active markets with current prices, trade count
- `view_portfolio()`: Returns cash balance, open positions with P&L, total value
- `comment_on_market(market_id, content)`: Add comment (visible to other agents via cross-platform bridge)
- `do_nothing()`: Skip turn

**System prompt template** (PolymarketPromptBuilder):
```
# WHO YOU ARE
You are a trader on a prediction market platform (similar to Polymarket)...
{name_str}
{profile_str}
Risk tolerance: {risk_str}

# HOW PREDICTION MARKETS WORK
[share prices, payout mechanics, you started with $1000]

# HOW TO DECIDE WHAT TO DO
DEFAULT: do_nothing — only trade with clear edge
buy_shares: when true probability > market price (mispricing)
  - Small edge 5-10%: $10-30
  - Medium edge 10-20%: $30-80
  - Large edge >20%: $80-200
  - Never >20% of cash on single position
sell_shares: take profit at fair value, cut losses, rebalance
do_nothing: YOUR DEFAULT (30-50% of rounds)

# TRADING PSYCHOLOGY
Be contrarian, react to new information, track P&L...
Social media signals: use Twitter/Reddit context as informational edge
```

**Observation prompt** (PolymarketEnvironment.to_text_prompt()):
```
## YOUR PORTFOLIO
Cash: $847.23
Positions: 23 YES shares @ $0.62 effective (current: $0.71, P&L: +$2.07)
Total portfolio: $1,023.85

## ACTIVE MARKETS
[1] "Will X happen by [date]?" YES: $0.71, NO: $0.29 | 47 trades

## SOCIAL CONTEXT
[injected from cross-platform bridge: recent Twitter/Reddit posts about the topic]

What do you want to do? Options: buy_shares, sell_shares, do_nothing
```

### 9.4 AMM Implementation (Constant-Product)

**Core invariant**: `x * y = k` where x = reserve_a, y = reserve_b

**Pricing**:
```
price_a = reserve_b / (reserve_a + reserve_b)
price_b = reserve_a / (reserve_a + reserve_b)
# Always: price_a + price_b = 1.0
```

**Buy (Mint-and-Swap)**:
```python
def quote_buy(reserve_a, reserve_b, outcome, amount_usd):
    k = reserve_a * reserve_b
    minted = amount_usd  # 1 complete set per $1

    if outcome == "YES":
        new_reserve_b = reserve_b + minted    # add unwanted shares to pool
        new_reserve_a = k / new_reserve_b     # pool gives back A shares
        swapped_a_out = reserve_a - new_reserve_a
        shares_out = minted + swapped_a_out   # minted A + swapped A
    else:
        # mirror for NO
        ...

    effective_price = amount_usd / shares_out
    return TradeResult(shares_out, effective_price, amount_usd, new_reserve_a, new_reserve_b)
```

**Sell (Split-Swap-and-Burn)** — quadratic solver:
```python
def quote_sell(reserve_a, reserve_b, outcome, shares):
    S = shares
    R_other = reserve_a if outcome == "YES" else reserve_b

    # Solve: x² + x·(R_a + R_b - S) - S·R_other = 0
    a, b, c = 1.0, (R_a + R_b - S), (-S * R_other)
    discriminant = b**2 - 4*a*c
    x = (-b + sqrt(discriminant)) / (2*a)

    usd_out = S - x  # complete sets burned = USD received
    ...
```

**2% cap**: `max_trade = 0.02 * min(reserve_a, reserve_b)` — enforced before AMM call to prevent single-agent market manipulation.

### 9.5 Real-Price Anchoring (WhaleSwarm Addition)

The base AMM is self-referential: agents trade a closed $10k pool and the price reflects only agent LLM biases, not reality. Real-price anchoring fixes this without removing the AMM.

**Mechanism:** At the start of each simulation round, before any agent acts, the AMM reserves are reset so the internal price matches the current real Polymarket CLOB price — while preserving the constant `k` and all agent portfolio positions.

```python
def anchor_to_real_price(market_id: int, real_price_yes: float):
    """Reset reserves to match real market price, preserving k."""
    row = db.execute("SELECT reserve_a, reserve_b FROM market WHERE market_id = ?", (market_id,))
    k = row["reserve_a"] * row["reserve_b"]  # preserve k

    # Solve for new reserves where price_YES = real_price_yes
    # price_YES = reserve_b / (reserve_a + reserve_b)
    # Combined with reserve_a * reserve_b = k:
    #   reserve_b = sqrt(k * real_price_yes / (1 - real_price_yes))
    #   reserve_a = k / reserve_b
    new_reserve_b = math.sqrt(k * real_price_yes / (1 - real_price_yes))
    new_reserve_a = k / new_reserve_b

    db.execute("UPDATE market SET reserve_a = ?, reserve_b = ? WHERE market_id = ?",
               (new_reserve_a, new_reserve_b, market_id))
```

**What happens each round:**
1. Real Polymarket price fetched via CLOB WebSocket (e.g., YES = $0.65)
2. AMM reserves reset so internal price = $0.65
3. Agents trade the internal AMM as normal (buy/sell/do_nothing)
4. Agent trades push the internal price away from $0.65 (e.g., to $0.72)
5. The **divergence** between internal price ($0.72) and real price ($0.65) is a signal
6. Next round: reserves reset to whatever the real price is now, cycle repeats

**What the divergence means:**
- Agents collectively trading the internal market to a higher price than reality = they think the real market is underpriced
- Agents collectively trading it lower = they think the real market is overpriced
- Large divergence + high agent conviction (large trade sizes) = strong signal
- Small divergence = agents roughly agree with the market, no edge

**Why this is better than removing the AMM entirely:**
- Agents still express conviction through action (committing scarce simulated cash), not just through text opinions
- The social→market→social feedback loop is preserved — social discussion influences trades, which move the internal price, which social agents can observe and react to
- You get **two independent probability estimates** from different mechanisms: the structured deliberation output AND the internal market divergence. Two signals that agree = higher confidence. Two that disagree = lower confidence or abstain.
- The AMM divergence captures something deliberation doesn't: how agents behave when they have to risk resources, not just explain reasoning

**Why this is better than keeping the AMM as-is:**
- The starting price each round is grounded in reality (thousands of real traders with real money), not in what agents thought last round
- Agents can't drift into a self-reinforcing bubble where their own trading history anchors them further and further from reality
- The divergence is meaningful: it measures the gap between what informed simulation agents think and what the real market says

**Agent portfolios are NOT reset.** Only reserves change. An agent who bought YES shares at $0.60 still holds those shares. Their P&L updates based on the new price. This means agents' past trades have consequences — they carry positions across rounds and must manage them, which creates richer decision-making than starting fresh each round.

**The divergence is tracked by `DivergenceTracker` and fed into the Trading Decision Layer** as a second signal alongside the structured deliberation swarm probability.

---

## 10. Cross-Platform Bridge Architecture

The most important emergent behavior in WhaleSwarm comes from agents on different platforms influencing each other. This is implemented as a shared memory/context injection system.

### 10.1 Social → Polymarket (Sentiment as Edge)

Before each Polymarket agent's turn, the platform's `to_text_prompt()` method fetches recent Twitter/Reddit posts related to the market question and injects them as "SOCIAL CONTEXT" in the observation string.

Implementation in `PolymarketEnvironment.to_text_prompt()`:
```python
def to_text_prompt(self) -> str:
    portfolio_str = await self._get_portfolio_text()
    markets_str = await self._get_markets_text()

    social_context = self.extra_observation_context  # injected externally

    return f"""
## YOUR PORTFOLIO
{portfolio_str}

## ACTIVE MARKETS
{markets_str}

{f"## SOCIAL MEDIA CONTEXT\n{social_context}" if social_context else ""}

What do you want to do?
"""
```

The `extra_observation_context` is set by the simulation runner each round from the `RoundMemory` system.

### 10.2 Polymarket → Social (Prices as Context)

Social media agents' observation contexts can include current market prices. The simulation runner injects `"Current market price for [question]: YES $0.67, NO $0.33"` into agent system messages via `inject_cross_platform_context()`.

### 10.3 RoundMemory (Sliding Window Compaction)

The cross-platform bridge uses a `RoundMemory` system to avoid context overflow across many rounds:
- **Current round**: Full action detail
- **Previous round**: Full action detail
- **Older rounds**: LLM-summarized into compact summaries (background thread)
- **Max exposure history**: 2000 content hashes per agent (dedup)

Compaction trigger: When accumulated rounds exceed a threshold, background thread summarizes oldest rounds into 2-3 sentence summaries.

### 10.4 Market-Media Bridge Pattern

The bridge is implemented via `inject_cross_platform_context()` and `inject_belief_context()` functions that manipulate agent system messages in-place:

```python
_CROSS_PLATFORM_MARKER = "\n\n# CROSS-PLATFORM CONTEXT"
_BELIEF_STATE_MARKER = "\n\n# YOUR CURRENT BELIEFS AND STANCE"

def inject_cross_platform_context(agent, context_text):
    content = agent.system_message.content
    marker_pos = content.find(_CROSS_PLATFORM_MARKER)
    if marker_pos != -1:
        content = content[:marker_pos]  # remove previous injection
    agent.system_message.content = content + "\n\n" + context_text
```

This pattern allows the simulation runner to update context at each round without creating new agent instances.

---

## 11. Belief State System

Each agent has a `BeliefState` that tracks their evolving opinions across rounds. This is **not** LLM-updated (too expensive for 40-200 rounds × N agents) — it uses heuristic rules.

### 11.1 BeliefState Dataclass

```python
@dataclass
class BeliefState:
    positions: Dict[str, float]        # topic → stance (-1.0 to +1.0)
    confidence: Dict[str, float]       # topic → certainty (0.0 to 1.0)
    trust: Dict[int, float]            # agent_id → trust level (0.0-1.0, default 0.5)
    exposure_history: Set[str]         # MD5 hashes of seen content (dedup)
    MAX_EXPOSURE_HISTORY: int = 2000   # evict oldest 500 when exceeded
```

**Topic extraction**: `extract_topics_from_requirement(simulation_requirement)` extracts 2-4 debate topics via LLM call (with regex fallback). Example: "AI regulation", "tech self-governance", "data privacy".

### 11.2 Initialization from Agent Config

```python
@classmethod
def from_profile(cls, agent_config, topics):
    stance_map = {
        "supportive": 0.6, "strongly_supportive": 0.9,
        "opposing": -0.6, "strongly_opposing": -0.9,
        "neutral": 0.0, "observer": 0.0
    }
    base_position = stance_map.get(stance_str, 0.0)
    base_confidence = min(1.0, max(0.1, 0.4 + abs(sentiment_bias) * 0.4))

    # Add Gaussian noise (σ=0.15 for position, σ=0.05 for confidence)
    # so identical stance agents still diverge slightly
```

### 11.3 Round Update Algorithm

Called once per round per agent:

```python
def update_from_round(self, posts_seen, own_engagement, round_num):
    for post in posts_seen:
        content_hash = md5(post.content)[:12]
        is_novel = content_hash not in self.exposure_history
        self.exposure_history.add(content_hash)

        post_stance = _estimate_stance(post.content)  # keyword heuristic
        author_trust = self.trust.get(post.author_id, 0.5)
        social_weight = min(1.0, 0.3 + post.num_likes * 0.07)
        novelty_mult = 1.5 if is_novel else 0.5  # novel args have 3x impact

        for topic in self.positions:
            if not _content_relates_to_topic(post.content, topic):
                continue

            current_conf = self.confidence[topic]
            resistance = 0.3 + current_conf * 0.7  # 0.3 to 1.0

            nudge = (
                (post_stance - current_pos)
                * author_trust
                * social_weight
                * novelty_mult
                * 0.08           # base learning rate
                / resistance     # high-confidence agents resist change
            )

            self.positions[topic] = clamp(current_pos + nudge, -1.0, 1.0)

    # Social reinforcement from own posts' engagement
    if likes_received > dislikes_received:
        boost = min(0.15, (likes - dislikes) * 0.03)
        # increase confidence (position doesn't change from own likes)
    elif dislikes_received > likes_received:
        drop = min(0.15, (dislikes - likes) * 0.03)
        # decrease confidence
```

### 11.4 Trust Updates

```python
def update_trust(self, other_agent_id, action):
    adjustments = {
        "like": +0.05,
        "dislike": -0.05,
        "follow": +0.10,
        "unfollow": -0.10,
        "mute": -0.20      # strongest signal
    }
    self.trust[other_id] = clamp(current + delta, 0.0, 1.0)
```

### 11.5 Stance Estimation Heuristic

`_estimate_stance(content)` — keyword matching, no LLM:

**Primary signals** (more reliable):
- Positive: support, agree, great, excellent, beneficial, important, necessary, progress, opportunity, innovative, promising, approve, endorse, welcome, positive, good news, well done, proud, celebrate, achievement
- Negative: oppose, disagree, terrible, harmful, dangerous, threat, unacceptable, disastrous, catastrophe, fail, wrong, corrupt, scandal, outrage, incompetent, reckless, protest, condemn, reject, concerned, worried

**Broad fallback** (attenuated by 0.6x):
- Positive: love, like, happy, hope, excited, better, best, awesome, amazing, cool, nice, interesting, helpful, thank, thanks, appreciate, win, success, improve, trust, confident, optimis, encourage, empower, brilliant, fantastic, incredible, wonderful, recommend, favor, advantage, benefit, gain
- Negative: hate, bad, sad, fear, angry, worse, worst, awful, horrible, stupid, ugly, annoying, disappoint, frustrat, problem, issue, risk, lose, loss, damage, distrust, pessimis, discourage, alarm, ridiculous, absurd, pathetic, disaster, blame, against, unfair, disadvantage, cost

**Final fallback**: Returns `0.0` (mild neutral) so posts always participate in belief updates. Never returns `None` for non-empty content (returning None would silently skip a post).

### 11.6 Topic Relevance Heuristic

`_content_relates_to_topic(content, topic)`:
- Direct substring match (case-insensitive)
- OR word-level overlap: any single keyword from topic found in content
- Low bar by design — over-broad matching is preferred to silent skips

### 11.7 Belief Context Injection into Agent

```python
def to_prompt_text(self) -> str:
    lines = ["# YOUR CURRENT BELIEFS AND STANCE",
             "These reflect your evolving understanding..."]
    for topic, position in self.positions.items():
        conf = self.confidence[topic]
        lines.append(f"- On **{topic}**: You are {stance_label} (confidence: {conf_label})")
    # Also lists trusted/distrusted agents (top 5)
```

This text is injected/replaced in the agent's system message before each round.

---

## 12. Recommendation System

Three modes selectable via `PlatformConfig.recsys_type`:

### 12.1 Random (`RecsysType.RANDOM`)

Each user gets `max_rec_post_len` randomly sampled posts. Used for testing.

### 12.2 Reddit Hot Score (`RecsysType.REDDIT`)

Hot score formula (identical to Reddit's actual algorithm):
```python
score = sign * log10(max(abs(upvotes - downvotes), 1)) + epoch_seconds / 45000
# epoch offset: 1134028003 (Reddit's founding)
```
All users see the same sorted-by-hot top posts. No personalization.

### 12.3 Twitter Personalized (`RecsysType.TWITTER`)

Uses `paraphrase-MiniLM-L6-v2` (SentenceTransformer):
1. Encode user bios (+ recent post appended to bio)
2. Encode post contents
3. Compute cosine similarity matrix (users × posts)
4. For each user: return top-K posts, excluding own posts

**Memory optimization**: Coarse filtering reduces post pool to 4000 before encoding.

### 12.4 TWHIN-BERT Personalized (`RecsysType.TWHIN`)

Uses `Twitter/twhin-bert-base`:
- Custom Twitter-domain model for better tweet understanding
- Same pipeline as Twitter but with HuggingFace model
- Supports `enable_like_score=True`: adjusts rankings based on user's like history

### 12.5 Recommendation Matrix Update

Updated after each round, before the next:
- `rec_matrix: List[List[post_id]]` — one list per user
- Passed to each platform's `update_rec_table()` method
- Platform stores matrix in SQLite for fast lookup during `to_text_prompt()`

---

## 13. Report Agent (ReACT)

`ReportAgent` generates a structured analytical report after simulation completes.

### 13.1 ReACT Loop Per Section

```
1. PLAN: Smart LLM generates table of contents outline
2. For each section:
   a. THOUGHT: "What do I need to know to write this section?"
   b. SEARCH: Call graph tools (InsightForge preferred, PanoramaSearch, QuickSearch)
   c. OBSERVE: Get simulation feed (actual posts, trades from SQLite)
   d. WRITE: LLM composes section text with citations
   e. REFLECT: LLM self-critiques: "Is this complete? What's missing?"
   f. If reflection finds gaps: repeat b-d (max_reflection_rounds times)
3. Assemble full report markdown
```

### 13.2 Available Tools

```python
tools = {
    "insight_forge": GraphToolsService.insight_forge,        # deep multi-dim search
    "panorama_search": GraphToolsService.panorama_search,    # broad coverage
    "quick_search": GraphToolsService.quick_search,          # fast semantic
    "search_simulation_feed": SimulationFeed.search,         # actual posts/trades
    "search_beliefs": BeliefTrajectory.search,               # agent opinion evolution
    "interview": SocialAgent.perform_interview,              # Q&A with specific agent
}
```

### 13.3 ReportLogger

Every action in report generation is logged to `agent_log.jsonl`:
```json
{"action": "search", "stage": "section_2_insight_forge", "query": "...", "elapsed_ms": 1234}
{"action": "write", "stage": "section_2", "word_count": 423}
{"action": "reflect", "stage": "section_2_reflection_1", "gap_found": true}
```

### 13.4 Report Format

Output: Markdown with:
- Cited graph entities (linked by UUID)
- Actual simulation quotes (post IDs with timestamps)
- Market price trajectory (Polymarket data)
- Belief trajectory summaries
- Platform-specific behavioral patterns

### 13.5 Interactive Chatbot

After report generation, users can ask follow-up questions via `/api/report/conversation`. The same ReACT agent handles questions with full access to graph tools and simulation feed. Conversation history is maintained per session.

---

## 14. Backend API Layer

### 14.1 Flask Application Factory

```python
def create_app():
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    neo4j_storage = Neo4jStorage(config)
    app.extensions['neo4j_storage'] = neo4j_storage

    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')

    @app.route('/health')
    def health(): return {'status': 'healthy'}

    # Request/response logging middleware
    @app.before_request / @app.after_request
```

### 14.2 Graph API Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/graph/ontology/generate` | Upload files + generate ontology |
| POST | `/api/graph/build` | Build knowledge graph (background) |
| GET | `/api/graph/project/<project_id>` | Get project metadata |
| GET | `/api/graph/task/<task_id>` | Poll background task progress |
| GET | `/api/graph/<graph_id>` | Get graph data (nodes + edges for viz) |

**`POST /api/graph/ontology/generate` input**:
```
Content-Type: multipart/form-data
files: [file1.pdf, file2.md]
simulation_requirement: "Simulate public reaction to..."
project_name: "My Project" (optional)
additional_context: "Focus on..." (optional)
```

**`POST /api/graph/build` input**:
```json
{
  "project_id": "uuid",
  "graph_name": "optional",
  "chunk_size": 500,
  "chunk_overlap": 50,
  "batch_size": 5
}
```

### 14.3 Simulation API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/simulation/entities/<graph_id>` | Get filtered entities from graph |
| POST | `/api/simulation/create` | Create simulation from project |
| POST | `/api/simulation/prepare` | Generate agent profiles (async) |
| POST | `/api/simulation/prepare/status` | Poll profile generation progress |
| POST | `/api/simulation/start` | Start simulation execution |
| POST | `/api/simulation/stop` | Stop running simulation |
| GET | `/api/simulation/<id>/run-status` | Real-time progress |
| GET | `/api/simulation/<id>/profiles` | Get generated profiles |
| GET | `/api/simulation/<id>/config` | Get simulation config |
| GET | `/api/simulation/<id>/posts` | Get posts/trades by platform and round |

**`GET /api/simulation/<id>/run-status` response**:
```json
{
  "status": "running",
  "current_round": 12,
  "total_rounds": 40,
  "simulated_hours": 6,
  "twitter_round": 12,
  "reddit_round": 12,
  "polymarket_round": 12,
  "total_actions": 847,
  "recent_actions": [...]
}
```

### 14.4 Report API Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/report/generate` | Generate report (async) |
| GET | `/api/report/<id>/status` | Poll generation progress |
| GET | `/api/report/<id>` | Get completed report |
| POST | `/api/report/<id>/conversation` | Chat with report agent |

### 14.5 Task Manager

All long-running operations (graph building, profile generation, report generation) use the `TaskManager`:

```python
@dataclass
class Task:
    task_id: str
    task_type: str
    status: str          # "pending" | "processing" | "completed" | "failed"
    progress: int        # 0-100
    metadata: Dict       # task-specific info
    result: Any          # output on completion
    error: str           # error message on failure
```

Tasks stored in-memory with optional disk backup. Frontend polls status every 2 seconds.

### 14.6 SimulationRunner

Key design: simulation runs as a **subprocess**, not a thread. This isolates the asyncio event loop (the simulation engine uses its own), prevents blocking the Flask server, and allows clean termination.

```python
class SimulationRunner:
    _run_states: Dict[str, SimulationRunState] = {}  # class-level, singleton
    _processes: Dict[str, subprocess.Popen] = {}

    @classmethod
    def start_simulation(cls, simulation_id, ...):
        # Write simulation config to disk
        # Spawn subprocess: python -m simulation_engine.run --simulation-id {id}
        # Register cleanup function on atexit

    @classmethod
    def get_run_state(cls, simulation_id):
        # Read actions.jsonl file written by subprocess
        # Parse recent actions, update in-memory RunState
        # Return current state

    @classmethod
    def stop_simulation(cls, simulation_id):
        # SIGTERM to subprocess
        # Update state to "stopped"
```

**`actions.jsonl` format** (written by the simulation engine subprocess):
```json
{"round": 3, "timestamp": "2024-01-15T14:23:01", "platform": "twitter", "agent_id": 7, "action": "create_post", "args": {"content": "This is..."}, "result": {"post_id": 42}}
{"round": 3, "timestamp": "2024-01-15T14:23:02", "platform": "polymarket", "agent_id": 12, "action": "buy_shares", "args": {"market_id": 1, "outcome": "YES", "amount_usd": 50.0}, "result": {"shares": 76.3, "new_price": 0.68}}
```

---

## 15. Frontend Architecture

### 15.1 Vue.js App Structure

```
frontend/
├── src/
│   ├── App.vue          # Root + global styles (design system)
│   ├── main.js          # Vue app init
│   ├── router/index.js  # Vue Router config
│   ├── views/           # Page-level components
│   ├── components/      # Reusable components
│   ├── api/             # Axios API clients
│   └── store/           # Global state (pendingUpload)
```

### 15.2 Routes

| Path | Component | Purpose |
|---|---|---|
| `/` | Home | Landing page |
| `/process/:projectId` | MainView | Steps 1-2: Graph + Agents |
| `/simulation/:simId` | SimulationView | Step 3: Setup |
| `/simulation/:simId/start` | SimulationRunView | Step 3: Execution |
| `/report/:reportId` | ReportView | Step 4: Report |
| `/interaction/:reportId` | InteractionView | Step 5: Agent chat |

### 15.3 MainView Layout

Split view with toggleable modes:
- **`graph`**: Full-width D3.js knowledge graph visualization
- **`split`**: Graph left + Workbench right (default)
- **`workbench`**: Full-width step controls

D3.js visualization: Force-directed physics simulation. Nodes colored by entity type. Hovering shows entity details. Clicking opens entity panel with relationships.

### 15.4 SimulationRunView

Key UI elements:
- Simulated time display (updating as rounds progress)
- Per-platform round counters
- Action feed (latest N actions across all platforms)
- Twitter/Reddit feed (latest posts)
- Polymarket price chart (line chart of YES price over rounds)
- Portfolio summary (top traders by P&L)
- Stop/pause controls

Polls `/api/simulation/{id}/run-status` every 2 seconds via `setInterval`.

### 15.5 Design System (Hyperstitions v2.0)

Evangelion-inspired dark theme:
```css
/* Colors */
--primary: #FF6B1A    /* orange */
--accent: #43C165     /* green */
--background: #0A0A0A /* near-black */
--surface: #141414    /* slightly lighter */
--text: #FAFAFA       /* near-white */
--muted: #666666      /* gray */

/* Spacing scale (1.4x modular) */
--space-1: 6px
--space-2: 11px
--space-3: 22px
--space-4: 34px
--space-5: 56px
--space-6: 84px

/* Typography */
--font-display: 'Young Serif'
--font-mono: 'Space Mono'

/* Effects */
@keyframes shimmer { ... }    /* loading states */
@keyframes pulse-border { ... } /* active elements */
@keyframes scan { ... }         /* scanning line effect */

/* Warning stripes divider */
.warning-stripes {
  background: repeating-linear-gradient(45deg, #FF6B1A, #FF6B1A 5px, transparent 5px, transparent 20px);
}
```

### 15.6 API Client Pattern

```javascript
// frontend/src/api/index.js
const service = axios.create({ baseURL: '/api', timeout: 30000 })

async function requestWithRetry(fn, maxRetries = 3, delay = 1000) {
  for (let i = 0; i < maxRetries; i++) {
    try { return await fn() }
    catch (e) {
      if (i === maxRetries - 1) throw e
      await sleep(delay)
    }
  }
}
```

---

## 16. Configuration System

### 16.1 `.env` File (project root)

```bash
# === LLM (Primary — bulk tasks: NER, profile gen) ===
LLM_PROVIDER=openai                        # "openai" | "claude-code"
LLM_API_KEY=sk-or-v1-...
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL_NAME=qwen/qwen3-235b-a22b-2507

# === LLM (Smart — intelligence-sensitive: ontology, reports) ===
SMART_PROVIDER=openai                      # optional, falls back to LLM_*
SMART_API_KEY=sk-or-v1-...
SMART_BASE_URL=https://openrouter.ai/api/v1
SMART_MODEL_NAME=anthropic/claude-sonnet-4

# === Embeddings ===
EMBEDDING_PROVIDER=openai                  # "openai" | "ollama"
EMBEDDING_MODEL=openai/text-embedding-3-small
EMBEDDING_BASE_URL=https://openrouter.ai/api
EMBEDDING_API_KEY=sk-or-v1-...
EMBEDDING_DIMENSIONS=768                   # must match model

# === Neo4j ===
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=WhaleSwarm

# === Simulation Defaults ===
WONDERWALL_DEFAULT_MAX_ROUNDS=10

# === Web Enrichment ===
WEB_ENRICHMENT_ENABLED=true
WEB_SEARCH_MODEL=                          # optional: "perplexity/sonar-pro"

# === Server ===
FLASK_HOST=0.0.0.0
FLASK_PORT=5001
FLASK_DEBUG=false
```

### 16.2 Local Ollama Mode

```bash
LLM_PROVIDER=openai
LLM_API_KEY=ollama                         # any non-empty value
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL_NAME=qwen3.5:27b

EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_BASE_URL=http://localhost:11434
EMBEDDING_DIMENSIONS=768

# Ollama Modelfile for extended context:
# FROM qwen3.5:27b
# PARAMETER num_ctx 32768
```

### 16.3 Claude Code Mode

```bash
LLM_PROVIDER=claude-code
CLAUDE_CODE_MODEL=claude-sonnet-4-20250514

# Still requires embeddings separately
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
```

---

## 17. Storage Architecture

### 17.1 Project Storage (File-based)

```
backend/uploads/projects/{project_id}/
├── project.json              # ProjectManager metadata
│   # {project_id, name, status, files[], ontology, graph_id, simulation_requirement}
├── files/
│   ├── document1.pdf
│   └── document2.md
└── extracted_text.txt        # concatenated text from all files
```

**Why file-based?** No additional database dependency, easy to inspect/backup, survives restarts, no migration burden.

### 17.2 Simulation Storage (File + SQLite)

```
backend/uploads/simulations/{simulation_id}/
├── simulation.json           # SimulationManager metadata
├── twitter_profiles.json     # OasisAgentProfile[] in twitter format
├── reddit_profiles.json      # OasisAgentProfile[] in reddit format
├── polymarket_profiles.json  # OasisAgentProfile[] in polymarket format
├── simulation_config.json    # Full SimulationConfig
├── twitter_simulation.db     # SQLite for Twitter platform
├── reddit_simulation.db      # SQLite for Reddit platform
├── polymarket_simulation.db  # SQLite for Polymarket platform
├── actions.jsonl             # Live action log (subprocess writes this)
└── trajectory.json           # Belief trajectory summaries
```

### 17.3 Report Storage

```
backend/uploads/reports/{report_id}/
├── report.md                 # Generated markdown report
└── agent_log.jsonl           # ReportAgent action log
```

### 17.4 SQLite Schema Overview

**Social Media (Twitter + Reddit)**:
```sql
user (user_id, agent_id, user_name, name, bio, created_at, num_followings, num_followers)
post (post_id, user_id, content, created_at, num_likes, num_dislikes)
comment (comment_id, post_id, user_id, content, created_at)
like (user_id, post_id, created_at)
dislike (user_id, post_id, created_at)  -- Reddit only
follow (follower_id, followee_id, created_at)
mute (user_id, muted_id, created_at)
report (user_id, post_id, reason, created_at)  -- Reddit only
repost (user_id, post_id, created_at)  -- Twitter only
quote_post (user_id, post_id, content, created_at)  -- Twitter only
trace (user_id, action, info JSON, created_at)  -- all actions log
```

**Polymarket**:
```sql
user (user_id, agent_id, user_name, name, bio, created_at, num_followings, num_followers)
portfolio (user_id, balance, updated_at)
position (position_id, user_id, market_id, outcome, shares)
market (market_id, creator_id, question, outcome_a, outcome_b, reserve_a, reserve_b, resolved, winning_outcome, created_at)
trade (trade_id, user_id, market_id, side, outcome, shares, price, cost, created_at)
comment (comment_id, market_id, creator_id, content, created_at)
trace (user_id, action, info JSON, created_at)
```

---

## 18. Performance Architecture

### 18.1 Parallelism Model

| Operation | Parallelism | Implementation |
|---|---|---|
| Chunk NER extraction | Parallel | ThreadPoolExecutor(batch_size workers) |
| Agent profile generation | Parallel batches | ThreadPoolExecutor |
| Sim config generation (agent configs) | Parallel batches | ThreadPoolExecutor |
| Platform execution | 3 platforms concurrent | asyncio.gather() |
| Agent turns within round | Concurrent | asyncio.gather() across active agents |
| Report sections | Sequential (by design) | Ordered for quality |

### 18.2 Key Optimizations

**Neo4j UNWIND batch insert**:
```cypher
UNWIND $entities AS entity
MERGE (e:Entity {uuid: entity.uuid, graph_id: $graph_id})
SET e += entity.properties
WITH e, entity
UNWIND entity.labels AS label
CALL apoc.create.addLabels(e, [label]) YIELD node
```
~10x faster than per-entity transactions.

**SQLite PRAGMA synchronous = OFF**:
Applied to all simulation databases. Removes fsync call after each write. Massive speedup for action-heavy simulations. Acceptable data loss risk: at most one round of data if process crashes.

**Recommendation matrix caching**:
- TF-IDF vectorizer and SentenceTransformer model loaded once, reused across rounds
- User profiles, post vectors incrementally updated (not recomputed from scratch)
- `u_items`, `t_items` global dicts maintained across round calls

**Context eviction**:
- `exposure_history` capped at 2000 entries, 500 evicted when exceeded
- Belief state uses O(1) hash lookups, not O(N) string comparisons

### 18.3 Model Loading Strategy

Recommendation models are globally cached:
```python
model = None           # paraphrase-MiniLM-L6-v2
twhin_tokenizer = None
twhin_model = None

def get_recsys_model(recsys_type):
    global model
    if model is None:
        model = SentenceTransformer('paraphrase-MiniLM-L6-v2', ...)
    return model
```

Models are GPU-accelerated when CUDA is available (`torch.device("cuda" if torch.cuda.is_available() else "cpu")`).

---

## 19. Key Design Decisions and Rationale

### 19.1 Belief State as Heuristics (Not LLM)

**Decision**: Belief states update via rule-based heuristics, not LLM calls.

**Why**: A simulation with 40 agents × 100 rounds × 3 platforms = 12,000 potential LLM calls just for belief updates. Heuristics are:
- Fast (microseconds vs seconds)
- Reproducible and inspectable
- Sufficient for capturing key dynamics: novelty amplification, social proof, confidence-driven resistance

**Tradeoff**: Beliefs don't capture nuanced semantic reasoning. An agent might be "swayed" by a post that is topically adjacent but not logically related.

### 19.2 Subprocess for Simulation (Not Thread)

**Decision**: the simulation engine runs as a subprocess, not a Python thread.

**Why**:
- the simulation engine uses `asyncio.run()` — needs its own event loop
- Flask is synchronous — running asyncio in a thread causes conflicts
- Subprocess isolation: crash in simulation doesn't crash Flask server
- Clean termination: `SIGTERM` to subprocess, no async cleanup needed
- IPC via filesystem: `actions.jsonl` is simple, inspectable, crash-safe

### 19.3 SQLite per Platform (Not Shared DB)

**Decision**: Each platform gets its own SQLite file.

**Why**:
- Platforms can run in parallel without locking conflicts
- Platform data is logically separate (Twitter users vs Polymarket traders)
- Easy to export/inspect individual platform data
- Schema migrations are platform-specific

### 19.4 File-Based Project State (Not PostgreSQL)

**Decision**: Project and simulation metadata stored in JSON files.

**Why**:
- Avoid requiring a second database beyond Neo4j
- Files are immediately inspectable
- Survive server restarts without startup migrations
- Natural isolation per project

**Tradeoff**: No transactions, no ACID guarantees. Two simultaneous writes could corrupt project.json. Acceptable given single-user desktop use case.

### 19.5 GraphStorage Interface (Not Direct Neo4j Calls)

**Decision**: All graph operations go through a `GraphStorage` interface.

**Why**:
- Originally used Zep Cloud; migrated to Neo4j without changing callers
- Future-proof: could add Memgraph, PostgreSQL with pgvector, etc.
- Testable: can mock storage in unit tests

### 19.6 Ontology-Guided NER (Not Open NER)

**Decision**: NER is ontology-constrained — only extracts entity types matching the simulation's ontology.

**Why**:
- Open NER would extract anything (dates, locations, abstract concepts)
- Simulation requires social media actors, not abstract entities
- Ontology ensures every entity becomes a plausible social media account
- Reduces graph noise and speeds up profile generation

### 19.7 CAMEL-AI ChatAgent as Agent Base

**Decision**: Agents extend `camel.agents.ChatAgent` rather than building from scratch.

**Why**:
- CAMEL-AI provides tool calling, multi-model support, message history management
- `scheduling_strategy='random_model'` enables load balancing across multiple LLM backends
- Memory management built in (context window compression)
- Well-tested async support (`astep()`, `_aget_model_response()`)

### 19.8 Constant-Product AMM with Real-Price Anchoring (Not Order Book, Not Pure Read-Only)

**Decision**: Keep the internal CFMM (x * y = k) but reset reserves to the real Polymarket CLOB price at the start of each round.

**Why CFMM, not order book**:
- Order books require matching counterparties — impossible with small agent swarms
- CFMM provides continuous liquidity at all price levels
- Prices always bounded in (0, 1) — valid probability interpretation
- Mint-and-swap / split-swap-and-burn mechanics correctly handle prediction market shares

**Why anchor to real price, not run the AMM standalone**:
- A standalone AMM is self-referential — the price reflects agent LLM biases, not reality
- Agents can drift into self-reinforcing bubbles over many rounds
- The internal price has no external validation

**Why keep the AMM at all, not just show agents the real CLOB price (read-only)**:
- Without trading, agents lose the ability to express conviction through action — they can only state opinions in text
- The social→market→social feedback loop (the most valuable emergent behavior) would be destroyed
- A read-only price gives you one signal (deliberation estimate). An anchored AMM gives you two: deliberation + market divergence
- The divergence between internal agent trading price and real market price is itself a novel, information-rich signal that pure deliberation cannot produce

### 19.9 Smart Model Routing

**Decision**: Dual LLM configuration — primary for bulk work, smart for intelligence work.

**Why**:
- NER on 100 text chunks: needs fast/cheap model (Qwen 235B via OpenRouter ≈ $0.003/M tokens)
- Generating ontology: needs high-quality reasoning (Claude Sonnet)
- Writing analytical report: needs best available model
- Cost optimization: 90% of LLM calls go to fast model, 10% to smart model

---

## 20. File Structure Reference

```
WhaleSwarm/
├── package.json                    # Root npm: concurrently runs frontend + backend
├── .env                            # All config (LLM, Neo4j, embeddings)
├── .env.example                    # Template
├── README.md                       # 381-line documentation
│
├── backend/
│   ├── run.py                      # Flask server entry point
│   ├── requirements.txt            # Python dependencies
│   │
│   ├── app/
│   │   ├── __init__.py             # Flask factory (create_app)
│   │   ├── config.py               # Config dataclass, env loading, validation
│   │   │
│   │   ├── api/
│   │   │   ├── graph.py            # /api/graph/* routes
│   │   │   ├── simulation.py       # /api/simulation/* routes
│   │   │   └── report.py           # /api/report/* routes
│   │   │
│   │   ├── models/
│   │   │   ├── project.py          # Project dataclass + ProjectManager
│   │   │   └── task.py             # Task dataclass + TaskManager
│   │   │
│   │   ├── services/
│   │   │   ├── ontology_generator.py    # Ontology from docs via Smart LLM
│   │   │   ├── graph_builder.py         # Chunking + parallel NER + Neo4j insert
│   │   │   ├── entity_reader.py         # Read filtered entities from graph
│   │   │   ├── oasis_profile_generator.py # Entity → agent profile
│   │   │   ├── simulation_config_generator.py # 4-step config generation
│   │   │   ├── simulation_manager.py    # SimulationState lifecycle
│   │   │   ├── simulation_runner.py     # Subprocess spawn + JSONL polling
│   │   │   ├── simulation_ipc.py        # Inter-process communication helpers
│   │   │   ├── graph_memory_updater.py  # Background Neo4j belief updates
│   │   │   ├── graph_tools.py           # InsightForge, PanoramaSearch, QuickSearch
│   │   │   ├── report_agent.py          # ReACT report generation
│   │   │   ├── text_processor.py        # Chunking, text preprocessing
│   │   │   └── web_enrichment.py        # Public figure enrichment
│   │   │
│   │   ├── storage/
│   │   │   ├── __init__.py              # GraphStorage interface
│   │   │   └── neo4j_storage.py         # Neo4j implementation
│   │   │
│   │   └── utils/
│   │       ├── llm_client.py            # OpenAI-compatible LLM client
│   │       ├── embedding_service.py     # Ollama/OpenAI embedding client
│   │       ├── ner_extractor.py         # NER via LLM
│   │       └── logger.py               # Logging setup
│   │
│   ├── simulation_engine/          # OASIS-based simulation engine
│   │   ├── clock/
│   │   │   └── clock.py            # Simulation time (Clock class)
│   │   │
│   │   ├── environment/
│   │   │   ├── env.py              # OasisEnv: main simulation orchestrator
│   │   │   ├── env_action.py       # Environment-level actions
│   │   │   └── make.py             # Factory functions
│   │   │
│   │   ├── simulations/
│   │   │   ├── base.py             # BasePlatform, BaseAction, BaseEnvironment,
│   │   │   │                       # BasePromptBuilder, SimulationConfig
│   │   │   │
│   │   │   ├── polymarket/
│   │   │   │   ├── platform.py     # PolymarketPlatform (SQLite + AMM)
│   │   │   │   ├── amm.py          # Constant-product AMM (quote_buy, quote_sell)
│   │   │   │   ├── environment.py  # PolymarketEnvironment (observation prompt)
│   │   │   │   ├── prompts.py      # PolymarketPromptBuilder (system prompt)
│   │   │   │   ├── actions.py      # PolymarketAction (buy/sell/browse tools)
│   │   │   │   └── schema/
│   │   │   │       ├── market.sql
│   │   │   │       ├── portfolio.sql
│   │   │   │       ├── position.sql
│   │   │   │       ├── trade.sql
│   │   │   │       └── comment.sql
│   │   │   │
│   │   │   └── social_media/
│   │   │       ├── prompts.py      # TwitterPromptBuilder, RedditPromptBuilder
│   │   │       └── schema/ (via social_platform)
│   │   │
│   │   ├── social_agent/
│   │   │   ├── agent.py            # SocialAgent (extends CAMEL ChatAgent)
│   │   │   ├── agent_action.py     # SocialAction (legacy Twitter/Reddit tools)
│   │   │   ├── agent_environment.py # SocialEnvironment (legacy)
│   │   │   ├── agent_graph.py      # AgentGraph (social network graph)
│   │   │   ├── agents_generator.py  # generate_agents(), generate_reddit_agents()
│   │   │   ├── belief_state.py     # BeliefState (heuristic belief tracking)
│   │   │   └── round_analyzer.py   # Per-round analysis helpers
│   │   │
│   │   └── social_platform/
│   │       ├── channel.py          # Channel (async message queue)
│   │       ├── platform.py         # Platform (legacy Twitter platform, large)
│   │       ├── platform_utils.py   # Platform utility methods
│   │       ├── recsys.py           # Recommendation systems (4 types)
│   │       ├── process_recsys_posts.py # Post vectorization for recsys
│   │       ├── database.py         # Database helpers
│   │       ├── typing.py           # ActionType enum, RecsysType enum
│   │       ├── config/
│   │       │   ├── user.py         # UserInfo dataclass
│   │       │   └── neo4j.py        # Neo4jConfig dataclass
│   │       └── schema/             # Core shared SQL schemas
│   │           ├── user.sql
│   │           ├── post.sql
│   │           ├── comment.sql
│   │           ├── like.sql
│   │           ├── dislike.sql
│   │           ├── follow.sql
│   │           ├── mute.sql
│   │           ├── report.sql
│   │           └── trace.sql
│   │
│   ├── uploads/                    # Runtime data (gitignored)
│   │   ├── projects/
│   │   ├── simulations/
│   │   └── reports/
│   │
│   └── scripts/
│       ├── test_full_pipeline.py
│       ├── test_3platform_interconnected.py
│       ├── test_polymarket.py
│       └── run_parallel_simulation.py
│
└── frontend/
    ├── package.json                # Vite, Vue, Axios, D3
    ├── vite.config.js              # Proxy /api → :5001
    ├── index.html
    └── src/
        ├── App.vue                 # Global styles (Hyperstitions design system)
        ├── main.js
        ├── router/index.js         # Vue Router
        ├── store/pendingUpload.js  # Global state
        ├── views/
        │   ├── MainView.vue        # Steps 1-2
        │   ├── SimulationView.vue  # Step 3 setup
        │   ├── SimulationRunView.vue # Step 3 execution (real-time)
        │   ├── ReportView.vue      # Step 4
        │   └── InteractionView.vue # Step 5 chatbot
        ├── components/
        │   ├── Step1GraphBuild.vue
        │   ├── Step2EnvSetup.vue
        │   ├── Step3Simulation.vue
        │   ├── Step4Report.vue
        │   ├── Step5Interaction.vue
        │   ├── GraphPanel.vue      # D3.js force graph
        │   └── HistoryDatabase.vue
        └── api/
            ├── index.js            # Axios base + retry
            ├── graph.js
            ├── simulation.js
            └── report.js
```

---

## Appendix A: Critical Implementation Notes

### A.1 What Makes GraphRAG "Work" Here

The term "GraphRAG" in WhaleSwarm refers to retrieval-augmented generation where the retrieval source is a knowledge graph rather than a flat vector store. The key differences from naive RAG:

1. **Structured relationships**: Not just "find similar text" but "find entities connected to this entity via specific relationship types"
2. **Entity-aware NER**: The graph knows entity *types*, not just names — a search for "CEO" returns only CEO-type nodes
3. **InsightForge sub-question decomposition**: Multi-hop reasoning by generating sub-questions, searching each, then synthesizing — mimics GraphRAG paper approach
4. **Hybrid search**: Combines embedding similarity (semantic) with graph traversal (structural)
5. **Ontology-constrained ingestion**: Ensures the graph is "agent-shaped" — every node can become a social media actor

### A.2 Why the Belief State Architecture is Critical

The belief state is what prevents agents from being "stateless NPCs". Without it:
- Each round the agent sees its feed and responds based purely on current context
- No memory of what it previously believed
- No dynamics (opinion polarization, echo chambers, conversion events)

With belief state:
- High-confidence agents resist persuasion (their position barely moves)
- Novel arguments have 3x the effect of repeated ones (prevents spam from working)
- Trust accumulates through positive interactions, decays through negative ones
- The belief state text is injected into the system message each round, creating continuity

### A.3 The AMM Design Guarantees

The AMM implementation has specific properties important to get right:
1. Prices are always valid probabilities (0 < p < 1, p_yes + p_no = 1)
2. Buying YES always increases the YES price
3. Buying NO always decreases the YES price
4. Each trade's effective price is bounded by current price and $1.00
5. The 2% cap prevents any single agent from moving prices more than ~4% per trade
6. Complete set mechanism ensures the market maker never runs out of liquidity
7. **Real-price anchoring preserves k** — when reserves are reset to match the real CLOB price, `k = reserve_a * reserve_b` stays constant. This means pool depth (slippage per dollar traded) is unchanged. Only the price point changes. Agent portfolios are NOT reset — positions carry across rounds with updated P&L.

### A.4 The Channel Pattern (Critical for Async Correctness)

The `Channel` class is the glue between agents (async Python) and platforms (also async Python). Key property: it supports **concurrent agents sharing a single platform channel** without race conditions because:
- Each message gets a unique `message_id`
- Agent awaits response with its specific `message_id`
- Platform responds to each message individually
- No shared mutable state between concurrent agent tasks

If you rebuild this, the Channel must be FIFO for platform dispatch but concurrent for agent responses.

### A.5 Cross-Platform Context Injection Timing

The order of operations in each round matters:
1. **Fetch real Polymarket CLOB price** via WebSocket
2. **Anchor internal AMM** — reset reserves to match real price (preserving k, preserving agent portfolios)
3. Simulation runner reads latest Twitter/Reddit posts
4. Summarizes into social context string
5. Injects into each Polymarket agent's `extra_observation_context`
6. Reads latest internal Polymarket prices (now anchored to real price)
7. Injects market prices into Twitter/Reddit agent system messages (via belief injection marker)
8. Run round (agents trade against the anchored AMM, pushing price away from real price)
9. Update belief states
10. **Record divergence** — internal AMM price vs. real CLOB price → `DivergenceTracker`

This ordering ensures: (a) the internal market starts grounded in reality each round, (b) Polymarket agents see fresh social sentiment, (c) social agents see fresh real-anchored prices, and (d) the divergence between agent trading and real market is captured after each round.

---

*End of PRD v1.0*
