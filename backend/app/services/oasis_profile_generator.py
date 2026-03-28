"""Agent profile generation from knowledge graph entities."""
import json
import logging
import random
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set

from app.config import Config
from app.models.task import TaskManager
from app.services.entity_reader import EntityReader
from app.services.web_enrichment import WebEnricher
from app.storage.neo4j_storage import Neo4jStorage
from app.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

# Baseline metrics by entity type
BASELINE_METRICS = {
    "MediaOutlet":   {"karma": 15000, "followers": 50000, "friends": 500,  "posts": 10000},
    "Journalist":    {"karma": 8000,  "followers": 20000, "friends": 1000, "posts": 8000},
    "CEO":           {"karma": 5000,  "followers": 15000, "friends": 500,  "posts": 3000},
    "Politician":    {"karma": 10000, "followers": 30000, "friends": 800,  "posts": 5000},
    "Organization":  {"karma": 12000, "followers": 40000, "friends": 600,  "posts": 7000},
    "Professor":     {"karma": 3000,  "followers": 5000,  "friends": 800,  "posts": 4000},
    "Company":       {"karma": 8000,  "followers": 25000, "friends": 400,  "posts": 6000},
    "Student":       {"karma": 800,   "followers": 300,   "friends": 400,  "posts": 500},
    "Person":        {"karma": 1500,  "followers": 1000,  "friends": 500,  "posts": 2000},
}

RISK_TOLERANCES = ["conservative", "moderate", "aggressive"]
MBTI_TYPES = [
    "INTJ", "INTP", "ENTJ", "ENTP",
    "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ",
    "ISTP", "ISFP", "ESTP", "ESFP",
]

PROFILE_GEN_PROMPT = """Generate a social media profile for this entity from a knowledge graph.

Entity name: {name}
Entity type: {entity_type}
Summary: {summary}
Related entities: {relations}

Generate a JSON profile with these fields:
{{
  "bio": "A short Twitter/Reddit bio (max 160 chars)",
  "persona": "A detailed 2-3 sentence character description for an AI agent playing this person on social media. Include their perspective, communication style, and likely opinions.",
  "age": <integer 18-80>,
  "gender": "<male/female/non-binary>",
  "mbti": "<MBTI type>",
  "country": "<2-letter country code>",
  "profession": "<their profession>",
  "interested_topics": ["topic1", "topic2", "topic3"],
  "risk_tolerance": "<conservative/moderate/aggressive>"
}}"""


@dataclass
class OasisAgentProfile:
    user_id: str = ""
    user_name: str = ""
    name: str = ""
    bio: str = ""
    persona: str = ""
    karma: int = 0
    friend_count: int = 0
    follower_count: int = 0
    statuses_count: int = 0
    risk_tolerance: str = "moderate"
    age: int = 30
    gender: str = "male"
    mbti: str = "INTJ"
    country: str = "US"
    profession: str = ""
    interested_topics: List[str] = field(default_factory=list)
    source_entity_uuid: str = ""

    def __post_init__(self):
        if not self.user_id:
            self.user_id = str(uuid.uuid4())[:8]

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
            "user_char": self.persona,
            "following_count": self.friend_count,
            "followers_count": self.follower_count,
            "statuses_count": self.statuses_count,
        }

    def to_polymarket_format(self) -> Dict:
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "risk_tolerance": self.risk_tolerance,
            "user_profile": self.persona,
        }


class OasisProfileGenerator:
    def __init__(
        self,
        config: Config,
        storage: Neo4jStorage,
        llm_client: LLMClient,
    ):
        self.config = config
        self.storage = storage
        self.llm = llm_client
        self.enricher = WebEnricher(llm_client, config)
        self.entity_reader = EntityReader(storage)

    def generate_profiles(
        self,
        graph_id: str,
        task_id: str = None,
        batch_size: int = 5,
    ) -> List[OasisAgentProfile]:
        """Generate agent profiles from all entities in a graph."""
        entities = self.entity_reader.get_entities(graph_id)
        total = len(entities)
        logger.info(f"Generating profiles for {total} entities")

        if task_id:
            TaskManager.update(task_id, status="processing", progress=5)

        profiles = []
        processed = 0

        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = {}
            for entity in entities:
                future = executor.submit(self._generate_one, entity, graph_id)
                futures[future] = entity

            for future in as_completed(futures):
                try:
                    profile = future.result()
                    if profile:
                        profiles.append(profile)
                except Exception as e:
                    entity = futures[future]
                    logger.warning(f"Profile gen failed for {entity.get('name')}: {e}")

                processed += 1
                if task_id:
                    progress = int(5 + (processed / total) * 90)
                    TaskManager.update(task_id, progress=progress)

        if task_id:
            TaskManager.update(
                task_id, progress=90,
                result={"profile_count": len(profiles)},
            )

        logger.info(f"Generated {len(profiles)} profiles")
        return profiles

    def generate_replacement_profiles(
        self,
        graph_id: str,
        count: int,
        exclude_entity_uuids: Set[str],
    ) -> List[OasisAgentProfile]:
        """Generate profiles for replacement agents, excluding existing entities."""
        entities = self.entity_reader.get_entities(graph_id)
        available = [e for e in entities if e["uuid"] not in exclude_entity_uuids]
        random.shuffle(available)
        selected = available[:count]

        profiles = []
        for entity in selected:
            profile = self._generate_one(entity, graph_id)
            if profile:
                profiles.append(profile)
        return profiles

    def _generate_one(self, entity: Dict, graph_id: str) -> Optional[OasisAgentProfile]:
        """Generate a single agent profile from an entity."""
        name = entity["name"]
        entity_type = entity.get("type", "Person")
        summary = entity.get("summary", "")
        entity_uuid = entity["uuid"]

        # Web enrichment
        if self.enricher.should_enrich(entity_type, summary):
            summary = self.enricher.enrich(name, entity_type, summary)

        # Get edges for context
        edges = self.storage.get_entity_edges(entity_uuid, graph_id)
        relations_str = "; ".join(
            [f"{e.get('other_name', '?')} ({e.get('name', 'related')})" for e in edges[:10]]
        ) if edges else "None"

        # Graph degree for social metric scaling
        degree = len(edges)
        degree_multiplier = 1.0 + min(degree, 10) * 0.2  # 1.0 to 3.0

        # Generate profile via LLM
        messages = [
            {"role": "system", "content": "You generate social media profiles. Return valid JSON only."},
            {"role": "user", "content": PROFILE_GEN_PROMPT.format(
                name=name, entity_type=entity_type,
                summary=summary, relations=relations_str,
            )},
        ]

        try:
            data = self.llm.complete_json(messages, smart=False, temperature=0.7)
            if isinstance(data, list):
                data = data[0] if data else {}
            if not isinstance(data, dict):
                data = {}
        except Exception as e:
            logger.warning(f"LLM profile gen failed for {name}: {e}, using defaults")
            data = {}

        # Get baseline metrics for entity type
        baselines = BASELINE_METRICS.get(entity_type, BASELINE_METRICS["Person"])

        # Create username from name
        user_name = name.lower().replace(" ", "_").replace(".", "")[:20]

        profile = OasisAgentProfile(
            user_name=user_name,
            name=name,
            bio=data.get("bio", f"{entity_type}: {summary[:100]}")[:160],
            persona=data.get("persona", f"{name} is a {entity_type}. {summary}"),
            karma=int(baselines["karma"] * degree_multiplier),
            friend_count=int(baselines["friends"] * degree_multiplier),
            follower_count=int(baselines["followers"] * degree_multiplier),
            statuses_count=int(baselines["posts"] * degree_multiplier),
            risk_tolerance=data.get("risk_tolerance", random.choice(RISK_TOLERANCES)),
            age=data.get("age", random.randint(22, 65)),
            gender=data.get("gender", random.choice(["male", "female"])),
            mbti=data.get("mbti", random.choice(MBTI_TYPES)),
            country=data.get("country", "US"),
            profession=data.get("profession", entity_type),
            interested_topics=data.get("interested_topics", []),
            source_entity_uuid=entity_uuid,
        )
        return profile
