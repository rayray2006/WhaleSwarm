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
    # Individuals
    "Politician":       {"karma": 10000, "followers": 30000, "friends": 800,  "posts": 5000},
    "Journalist":       {"karma": 8000,  "followers": 20000, "friends": 1000, "posts": 8000},
    "Analyst":          {"karma": 4000,  "followers": 8000,  "friends": 600,  "posts": 5000},
    "Activist":         {"karma": 6000,  "followers": 12000, "friends": 1500, "posts": 7000},
    "Diplomat":         {"karma": 3000,  "followers": 10000, "friends": 400,  "posts": 2000},
    "MilitaryOfficial": {"karma": 2000,  "followers": 5000,  "friends": 300,  "posts": 1500},
    "Researcher":       {"karma": 3000,  "followers": 5000,  "friends": 800,  "posts": 4000},
    "Investor":         {"karma": 5000,  "followers": 15000, "friends": 500,  "posts": 3000},
    "Trader":           {"karma": 4000,  "followers": 8000,  "friends": 600,  "posts": 6000},
    "Influencer":       {"karma": 12000, "followers": 50000, "friends": 2000, "posts": 10000},
    "Executive":        {"karma": 5000,  "followers": 15000, "friends": 500,  "posts": 3000},
    "CEO":              {"karma": 5000,  "followers": 15000, "friends": 500,  "posts": 3000},
    "Professor":        {"karma": 3000,  "followers": 5000,  "friends": 800,  "posts": 4000},
    "Student":          {"karma": 800,   "followers": 300,   "friends": 400,  "posts": 500},
    "Commentator":      {"karma": 7000,  "followers": 15000, "friends": 800,  "posts": 9000},
    "Lawyer":           {"karma": 2500,  "followers": 4000,  "friends": 600,  "posts": 2000},
    "Person":           {"karma": 1500,  "followers": 1000,  "friends": 500,  "posts": 2000},
    "GameDeveloper":    {"karma": 6000,  "followers": 10000, "friends": 500,  "posts": 4000},
    "Engineer":         {"karma": 3000,  "followers": 4000,  "friends": 700,  "posts": 3000},
    "Designer":         {"karma": 3500,  "followers": 6000,  "friends": 600,  "posts": 3500},
    "ContentCreator":   {"karma": 10000, "followers": 30000, "friends": 1500, "posts": 8000},
    "Athlete":          {"karma": 8000,  "followers": 25000, "friends": 500,  "posts": 3000},
    "Coach":            {"karma": 4000,  "followers": 8000,  "friends": 600,  "posts": 2500},
    # Institutions
    "MediaOutlet":      {"karma": 15000, "followers": 50000, "friends": 500,  "posts": 10000},
    "Company":          {"karma": 8000,  "followers": 25000, "friends": 400,  "posts": 6000},
    "NGO":              {"karma": 6000,  "followers": 15000, "friends": 500,  "posts": 5000},
    "ThinkTank":        {"karma": 5000,  "followers": 10000, "friends": 400,  "posts": 4000},
    "GovernmentAgency": {"karma": 8000,  "followers": 30000, "friends": 300,  "posts": 5000},
    "Organization":     {"karma": 12000, "followers": 40000, "friends": 600,  "posts": 7000},
    "Studio":           {"karma": 10000, "followers": 40000, "friends": 300,  "posts": 5000},
    "Publisher":        {"karma": 8000,  "followers": 30000, "friends": 400,  "posts": 6000},
    "League":           {"karma": 12000, "followers": 50000, "friends": 500,  "posts": 8000},
}

# Types that represent institutions (not individual people)
GROUP_ENTITY_TYPES = {
    "mediaoutlet", "company", "ngo", "thinktank", "governmentagency",
    "organization", "institution", "agency", "platform", "network",
    "fund", "exchange", "consortium", "coalition", "studio", "publisher",
    "league",
}

RISK_TOLERANCES = ["conservative", "moderate", "aggressive"]
MBTI_TYPES = [
    "INTJ", "INTP", "ENTJ", "ENTP",
    "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ",
    "ISTP", "ISFP", "ESTP", "ESFP",
]

INDIVIDUAL_TYPE_KEYWORDS = {
    "founder", "forecaster", "user", "trader", "influencer", "analyst",
    "advisor", "leader", "critic", "advocate", "commentator", "blogger",
    "developer", "engineer", "designer", "coach", "athlete", "creator",
}

INDIVIDUAL_SYSTEM_PROMPT = (
    "You are an expert character writer creating social media personas for a "
    "multi-agent simulation. Your personas must feel like REAL people — messy, "
    "opinionated, contradictory, specific. Avoid generic corporate-speak or "
    "balanced-sounding descriptions. Every person has biases, blind spots, and "
    "strong feelings about something. Lean into those. Return valid JSON only."
)

GROUP_SYSTEM_PROMPT = (
    "You are an expert in institutional communications creating official social "
    "media account personas for a multi-agent simulation. Institutional accounts "
    "have a distinct voice — formal but not robotic, on-message but not "
    "tone-deaf. They hedge on controversies, amplify achievements, and deflect "
    "criticism with practiced diplomacy. Return valid JSON only."
)

INDIVIDUAL_PROFILE_PROMPT = """Generate a deep social media persona for this person. They will be an AI agent on Twitter, Reddit, and Polymarket prediction markets.

Name: {name}
Role: {entity_type}
Background: {summary}
Connected to: {relations}

Write a DETAILED character profile (at least 800 characters for the persona field). Cover ALL of these:
1. BACKGROUND: Who they are, what shaped them, what they've experienced
2. PERSONALITY: MBTI-aligned traits, how they think, emotional patterns
3. COMMUNICATION STYLE: How they write online — formal, combative, sarcastic, analytical, emotional? Do they use data? Memes? Personal anecdotes?
4. BIASES & BLIND SPOTS: What they overweight, what they ignore, where their reasoning breaks down
5. WHAT CHANGES THEIR MIND: What evidence or events would make them update their beliefs?
6. BREAKING NEWS REACTION: Do they post immediately? Wait for analysis? Jump to conclusions? Share hot takes?
7. PREDICTION MARKET BEHAVIOR: Are they a momentum trader, contrarian, or fundamentals-based? Do they panic sell?

Return JSON:
{{
  "bio": "Twitter bio in their voice, max 160 chars — witty, opinionated, revealing",
  "persona": "800-1200 character detailed character description covering all 7 points above. Be vivid and specific. This is the agent's entire personality.",
  "age": <integer 18-80>,
  "gender": "<male/female/non-binary>",
  "mbti": "<MBTI type>",
  "country": "<2-letter country code>",
  "profession": "<their profession>",
  "interested_topics": ["topic1", "topic2", "topic3", "topic4", "topic5"],
  "risk_tolerance": "<conservative/moderate/aggressive>"
}}"""

GROUP_PROFILE_PROMPT = """Generate an institutional social media persona. This organization runs official accounts on Twitter, Reddit, and Polymarket.

Organization: {name}
Type: {entity_type}
Background: {summary}
Connected to: {relations}

Write a communications playbook (at least 600 characters for the persona field). Cover:
1. INSTITUTIONAL VOICE: How do they frame issues publicly? Neutral? Advocacy? Authoritative?
2. EDITORIAL STANCE: What positions do they take? What do they amplify or downplay?
3. CONTROVERSY HANDLING: How do they respond to criticism or breaking news?
4. RED LINES: What topics do they avoid? What would make them break from their usual tone?
5. MARKET BEHAVIOR: If this institution traded on prediction markets, what would their strategy be?

Return JSON:
{{
  "bio": "Official Twitter bio, max 160 chars — institutional but with character",
  "persona": "600-900 character institutional communications playbook covering all 5 points above.",
  "country": "<2-letter country code>",
  "profession": "{entity_type}",
  "interested_topics": ["topic1", "topic2", "topic3", "topic4", "topic5"],
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
                    progress = int(5 + (processed / total) * 40)
                    TaskManager.update(task_id, progress=progress)

        if task_id:
            TaskManager.update(
                task_id, progress=45,
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

    def _is_group(self, entity_type: str) -> bool:
        """Classify entity type as group/institution vs individual person."""
        lower = entity_type.lower()
        if lower in GROUP_ENTITY_TYPES:
            return True
        for kw in INDIVIDUAL_TYPE_KEYWORDS:
            if kw in lower:
                return False
        return False

    def _build_entity_context(self, entity: Dict, graph_id: str) -> str:
        """Build rich multi-layer context for an entity before persona generation."""
        parts = []
        entity_uuid = entity["uuid"]
        summary = entity.get("summary", "")

        if summary:
            parts.append(f"Summary: {summary}")

        attrs = entity.get("attributes")
        if attrs and isinstance(attrs, dict):
            attr_lines = [f"  {k}: {v}" for k, v in list(attrs.items())[:10]]
            if attr_lines:
                parts.append("Attributes:\n" + "\n".join(attr_lines))

        edges = self.storage.get_entity_edges(entity_uuid, graph_id)
        if edges:
            edge_lines = []
            for e in edges[:20]:
                other = e.get("other_name", "?")
                rel = e.get("name", "related_to")
                fact = e.get("fact", "")
                line = f"  {entity['name']} --[{rel}]--> {other}"
                if fact:
                    line += f" | {fact}"
                edge_lines.append(line)
            parts.append("Relationships:\n" + "\n".join(edge_lines))

        if self.enricher.should_enrich(entity.get("type", ""), summary):
            enriched = self.enricher.enrich(entity["name"], entity.get("type", ""), summary)
            if enriched and enriched != summary:
                parts.append(f"Background: {enriched}")

        combined = "\n\n".join(parts)
        return combined[:3000]

    def _infer_risk_tolerance(self, entity_type: str, name: str, mbti: str, profession: str) -> str:
        """Cascading heuristic for risk tolerance based on multiple signals."""
        name_lower = name.lower()
        high_keywords = {"hedge fund", "venture", "trading", "defi", "prediction market", "crypto"}
        low_keywords = {"treasury", "stablecoin", "regulator", "compliance"}

        for kw in high_keywords:
            if kw in name_lower:
                return "aggressive"
        for kw in low_keywords:
            if kw in name_lower:
                return "conservative"

        et = entity_type.lower()
        if et in {"governmentagency", "ngo", "university"}:
            return "conservative"

        if mbti:
            if mbti[1:3] == "NT" or mbti.endswith("P"):
                return "aggressive"
            if mbti[1:3] == "SF" or mbti.endswith("J"):
                return "conservative"

        prof = profession.lower()
        if any(kw in prof for kw in ["trader", "investor", "entrepreneur", "founder"]):
            return "aggressive"
        if any(kw in prof for kw in ["accountant", "official", "lawyer", "regulator"]):
            return "conservative"

        return random.choice(["conservative", "moderate", "moderate", "aggressive"])

    def _degree_factor(self, degree: int, name: str) -> float:
        """Graph-degree scaling with deterministic name-hash jitter."""
        base = min(3.0, 1.0 + (max(0, degree - 1)) * 0.15)
        jitter = 0.85 + (hash(name) % 30) / 100.0
        return base * jitter

    def _generate_one(self, entity: Dict, graph_id: str) -> Optional[OasisAgentProfile]:
        """Generate a single agent profile from an entity with rich context."""
        name = entity["name"]
        entity_type = entity.get("type", "Person")
        entity_uuid = entity["uuid"]

        context = self._build_entity_context(entity, graph_id)

        edges = self.storage.get_entity_edges(entity_uuid, graph_id)
        degree = len(edges)
        relations_str = "; ".join(
            [f"{e.get('other_name', '?')} ({e.get('name', 'related')})" for e in edges[:15]]
        ) if edges else "None"

        is_group = self._is_group(entity_type)
        sys_prompt = GROUP_SYSTEM_PROMPT if is_group else INDIVIDUAL_SYSTEM_PROMPT
        user_prompt = (GROUP_PROFILE_PROMPT if is_group else INDIVIDUAL_PROFILE_PROMPT).format(
            name=name,
            entity_type=entity_type,
            summary=context[:2000],
            relations=relations_str,
        )

        data = {}
        temps = [0.7, 0.6, 0.5]
        for attempt, temp in enumerate(temps):
            try:
                result = self.llm.complete_json(
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    smart=False,
                    temperature=temp,
                )
                if isinstance(result, list):
                    result = result[0] if result else {}
                if isinstance(result, dict) and result.get("persona"):
                    data = result
                    break
            except Exception:
                if attempt == len(temps) - 1:
                    logger.warning("Profile gen failed for %s after %d attempts", name, len(temps))

        baselines = BASELINE_METRICS.get(entity_type, BASELINE_METRICS["Person"])
        user_name = name.lower().replace(" ", "_").replace(".", "")[:20]
        factor = self._degree_factor(degree, name)

        mbti = data.get("mbti", random.choice(MBTI_TYPES))
        profession = data.get("profession", entity_type)

        if is_group:
            age = 30
            gender = "other"
            risk = data.get("risk_tolerance", self._infer_risk_tolerance(entity_type, name, mbti, profession))
        else:
            age = data.get("age", random.randint(22, 65))
            gender = data.get("gender", random.choice(["male", "female"]))
            risk = data.get("risk_tolerance", self._infer_risk_tolerance(entity_type, name, mbti, profession))

        summary_fallback = entity.get("summary", "")
        profile = OasisAgentProfile(
            user_name=user_name,
            name=name,
            bio=data.get("bio", f"{entity_type}: {summary_fallback[:100]}")[:160],
            persona=data.get("persona", f"{name} is a {entity_type}. {summary_fallback}"),
            karma=int(baselines["karma"] * factor),
            friend_count=int(baselines["friends"] * factor),
            follower_count=int(baselines["followers"] * factor),
            statuses_count=int(baselines["posts"] * factor),
            risk_tolerance=risk,
            age=age,
            gender=gender,
            mbti=mbti,
            country=data.get("country", "US"),
            profession=profession,
            interested_topics=data.get("interested_topics", []),
            source_entity_uuid=entity_uuid,
        )
        return profile

    # ------------------------------------------------------------------
    # Background population generation
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Archetype-based batch definitions for population diversity
    # ------------------------------------------------------------------

    _ARCHETYPES = [
        {
            "label": "informed_professionals",
            "count_pct": 0.20,
            "instruction": (
                "These are educated professionals who follow the topic closely. "
                "Mix: lawyers, doctors, engineers, professors, financial analysts, "
                "policy wonks, military veterans. They read long-form analysis, "
                "cite sources in arguments, and have nuanced but firm positions. "
                "Some are hawkish, some dovish. They trade prediction markets "
                "based on research and hold positions for days."
            ),
        },
        {
            "label": "retail_traders",
            "count_pct": 0.15,
            "instruction": (
                "Day traders, crypto bros, finance Twitter people, WallStreetBets "
                "types. They watch charts, follow whale wallets, love leverage, "
                "and talk in trading jargon (WAGMI, NFA, bags, diamond hands). "
                "Some are sophisticated quant types; others are pure gambling "
                "addicts. They react FAST to breaking news — buy the rumor, "
                "sell the news. Prone to FOMO and panic selling."
            ),
        },
        {
            "label": "concerned_citizens",
            "count_pct": 0.20,
            "instruction": (
                "Regular working people who care about this topic because it "
                "affects their lives. Nurses, teachers, factory workers, "
                "small business owners, retirees, parents. They get news from "
                "TV, Facebook, and family group chats. Their opinions are "
                "shaped by personal experience more than data. Emotionally "
                "reactive. Some are scared, some are angry, some are hopeful. "
                "They dabble in prediction markets with small bets."
            ),
        },
        {
            "label": "young_digital_natives",
            "count_pct": 0.15,
            "instruction": (
                "Gen Z and young millennials (18-28). College students, "
                "baristas, junior developers, TikTok creators, gamers. "
                "They communicate in memes, use slang, are chronically online. "
                "Their politics are strong but often inconsistent. They trade "
                "prediction markets like a game. Short attention spans but "
                "occasionally go deep on a topic that captures them."
            ),
        },
        {
            "label": "skeptics_and_contrarians",
            "count_pct": 0.15,
            "instruction": (
                "People who distrust mainstream narratives. Mix of: libertarians, "
                "conspiracy-adjacent thinkers, anti-establishment types, "
                "alternative media consumers, former intelligence/military who "
                "'know how the game is really played.' They question every "
                "official statement, look for hidden agendas, and love saying "
                "'I told you so.' Some are sharp analysts; others are cranks. "
                "They bet AGAINST consensus on prediction markets."
            ),
        },
        {
            "label": "international_observers",
            "count_pct": 0.15,
            "instruction": (
                "People from countries directly or indirectly affected. Include "
                "perspectives from Global South, Eastern Europe, Middle East, "
                "East Asia, Latin America, Africa. Each person's view is shaped "
                "by their country's relationship to the topic. A Turkish "
                "shopkeeper sees it differently than a Polish border guard or "
                "a Nigerian energy analyst. They bring context outsiders miss."
            ),
        },
    ]

    def generate_background_population(
        self,
        count: int,
        simulation_requirement: str,
        stakeholder_names: List[str],
        task_id: str = None,
    ) -> List[OasisAgentProfile]:
        """Generate a diverse population of 'regular person' agents.

        Uses themed archetype batches to ensure genuine diversity rather
        than 100 variations of the same centrist professional.
        """
        logger.info("Generating %d background agents across %d archetypes",
                     count, len(self._ARCHETYPES))

        all_profiles: List[OasisAgentProfile] = []
        generated = 0

        for archetype in self._ARCHETYPES:
            batch_count = max(1, int(count * archetype["count_pct"]))
            if len(all_profiles) + batch_count > count:
                batch_count = count - len(all_profiles)
            if batch_count <= 0:
                break

            batch_num = 0
            while batch_num < batch_count:
                chunk = min(5, batch_count - batch_num)
                prompt = self._build_archetype_prompt(
                    chunk, archetype, simulation_requirement,
                    stakeholder_names, len(all_profiles),
                )

                try:
                    result = self.llm.complete_json(
                        messages=[
                            {"role": "system", "content": (
                                "You are a character writer creating realistic social "
                                "media user profiles. Every person must be vividly "
                                "specific — a real human with a messy life, strong "
                                "opinions, contradictions, and a particular way of "
                                "talking online. NO generic balanced profiles. "
                                "Return a JSON array."
                            )},
                            {"role": "user", "content": prompt},
                        ],
                        smart=False,
                        temperature=0.95,
                        max_tokens=8192,
                    )

                    if isinstance(result, dict):
                        result = result.get("profiles", result.get("agents",
                                    result.get("people", result.get("users", []))))
                    if not isinstance(result, list):
                        result = []

                    for item in result[:chunk]:
                        if not isinstance(item, dict):
                            continue
                        all_profiles.append(self._item_to_profile(item))

                except Exception:
                    logger.exception("Archetype batch '%s' failed, using fallback",
                                     archetype["label"])
                    for _ in range(chunk):
                        all_profiles.append(self._random_background_profile(
                            simulation_requirement, len(all_profiles),
                        ))

                batch_num += chunk
                generated += chunk
                if task_id:
                    pct = int(50 + (generated / count) * 40)
                    TaskManager.update(task_id, progress=min(pct, 90))

            logger.info("Archetype '%s': %d agents (total %d/%d)",
                        archetype["label"], batch_count, len(all_profiles), count)

        return all_profiles[:count]

    def _build_archetype_prompt(
        self,
        count: int,
        archetype: Dict,
        requirement: str,
        stakeholder_names: List[str],
        offset: int,
    ) -> str:
        return f"""Generate {count} people for a social media simulation.

ARCHETYPE: {archetype['label'].upper().replace('_', ' ')}
{archetype['instruction']}

For EACH person, create a complete character. Focus 80% on WHO THEY ARE as a person,
and only 20% on their connection to the simulation topic.

1. FULL NAME — realistic, culturally appropriate for their background
2. AGE — appropriate for the archetype
3. COUNTRY — 2-letter code
4. PROFESSION — specific job title, not just a category
5. GENDER — male, female, or non-binary
6. MBTI — pick one that fits the character
7. BIO — Twitter/Reddit bio in THEIR voice. Max 160 chars. About them as a person, not the topic.
8. PERSONA — 800-1200 characters. Write this like a casting brief for an actor:
   - Their life story in 2-3 sentences (where they grew up, what shaped them, what drives them)
   - Their personality: how they talk online, what they care about day-to-day
   - Their blind spots, contradictions, pet peeves
   - How they argue (data-driven? emotional? sarcastic? earnest? combative? lurker who rarely posts?)
   - One quirky detail that makes them memorable
   - At the end, one sentence on their gut instinct or passing opinion about: {requirement}
9. RISK TOLERANCE — conservative, moderate, or aggressive
10. INTERESTED TOPICS — 4-6 topics personal to them (hobbies, career, causes they follow)

This is batch #{offset // 5 + 1}. Every person must be UNIQUE.

Return JSON array:
[
  {{
    "name": "Full Name",
    "age": <int>,
    "gender": "<male/female/non-binary>",
    "mbti": "<MBTI>",
    "country": "<2-letter code>",
    "profession": "<specific job title>",
    "bio": "<their voice, max 160 chars>",
    "persona": "<800-1200 char character brief>",
    "risk_tolerance": "<conservative/moderate/aggressive>",
    "interested_topics": ["topic1", "topic2", "topic3", "topic4"]
  }}
]"""

    def _item_to_profile(self, item: Dict) -> OasisAgentProfile:
        name = item.get("name", f"User-{random.randint(1000, 9999)}")
        user_name = name.lower().replace(" ", "_").replace(".", "")[:20]

        base_karma = random.randint(100, 4000)
        base_followers = random.randint(20, 2000)

        mbti = item.get("mbti", random.choice(MBTI_TYPES))
        profession = item.get("profession", "Person")
        risk = item.get("risk_tolerance",
                        self._infer_risk_tolerance("Person", name, mbti, profession))

        return OasisAgentProfile(
            user_name=user_name,
            name=name,
            bio=item.get("bio", f"{profession}")[:160],
            persona=item.get("persona", f"{name} is a {profession}."),
            karma=base_karma,
            friend_count=random.randint(50, 600),
            follower_count=base_followers,
            statuses_count=random.randint(50, 3000),
            risk_tolerance=risk,
            age=item.get("age", random.randint(20, 65)),
            gender=item.get("gender", random.choice(["male", "female"])),
            mbti=mbti,
            country=item.get("country", random.choice(
                ["US", "UK", "IN", "DE", "BR", "JP", "NG", "CA", "PL", "TR", "KR", "MX", "PH", "AU"]
            )),
            profession=profession,
            interested_topics=item.get("interested_topics", []),
            source_entity_uuid="",
        )

    def _random_background_profile(self, requirement: str, index: int) -> OasisAgentProfile:
        first_names = [
            "James", "Maria", "Wei", "Priya", "Ahmed", "Sophie", "Carlos",
            "Yuki", "Olga", "Kwame", "Sarah", "Raj", "Emma", "Liam",
            "Fatima", "Diego", "Aiko", "Ivan", "Nina", "Tariq",
            "Chloe", "Hassan", "Mei", "Andrei", "Amara", "Kenji",
        ]
        last_names = [
            "Smith", "Garcia", "Chen", "Patel", "Kim", "Mueller", "Santos",
            "Tanaka", "Petrov", "Okafor", "Johnson", "Singh", "Brown",
            "Lopez", "Nakamura", "Ivanov", "Williams", "Ali", "Sato", "Park",
            "Dubois", "Osei", "Morales", "Johansson", "Novak", "Takahashi",
        ]
        professions = [
            "software engineer", "nurse", "high school teacher", "day trader",
            "PhD student", "retired army sergeant", "freelance journalist",
            "tax accountant", "long-haul truck driver", "bakery owner",
            "marketing coordinator", "data analyst", "line cook",
            "electrician", "immigration lawyer", "dental hygienist",
            "warehouse supervisor", "yoga instructor", "auto mechanic",
            "social worker", "real estate agent", "bartender",
        ]
        countries = ["US", "UK", "IN", "DE", "BR", "JP", "NG", "CA", "AU", "KR", "FR", "MX", "PL", "TR", "PH"]

        name = f"{random.choice(first_names)} {random.choice(last_names)}"
        profession = random.choice(professions)
        country = random.choice(countries)
        age = random.randint(19, 68)
        gender = random.choice(["male", "female"])
        mbti = random.choice(MBTI_TYPES)

        return OasisAgentProfile(
            user_name=name.lower().replace(" ", "_")[:20],
            name=name,
            bio=f"{profession.title()} | {country} | Opinions are my own",
            persona=(
                f"{name} is a {age}-year-old {profession} from {country}. "
                f"MBTI: {mbti}. Gets news from a mix of social media and TV. "
                f"Has strong opinions shaped by personal experience rather than "
                f"formal analysis. Trades prediction markets with small stakes, "
                f"mostly on gut feeling. Quick to share hot takes but rarely "
                f"follows up. Argues passionately then moves on."
            ),
            karma=random.randint(100, 2000),
            friend_count=random.randint(50, 400),
            follower_count=random.randint(20, 1000),
            statuses_count=random.randint(50, 2000),
            risk_tolerance=random.choice(RISK_TOLERANCES),
            age=age,
            gender=gender,
            mbti=mbti,
            country=country,
            profession=profession,
            interested_topics=[],
            source_entity_uuid="",
        )
