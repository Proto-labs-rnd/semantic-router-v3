#!/usr/bin/env python3
"""
Domain-Augmented Embeddings Router V3

Instead of fine-tuning nomic-embed-text (not supported by Ollama),
this approach adds a domain adaptation layer on top of the base embeddings:

1. Homelab vocabulary expansion (synonyms, abbreviations, French↔English)
2. Multi-example centroid embeddings per route
3. Domain-specific keyword boosting
4. French normalization layer

Architecture:
  Query → French normalize → Vocabulary expand → Embed → 
  Route centroids similarity → Keyword boost → Score → Route
"""

import json
import re
import time
import hashlib
import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field

# ── Configuration ──────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"
CACHE_FILE = "/tmp/embedding_cache_v3.json"

# ── Homelab Domain Vocabulary ──────────────────────────────────────────────
# Maps domain-specific terms to their canonical concepts
# This bridges the gap between general-purpose embeddings and homelab semantics

HOMELAB_VOCAB = {
    # Docker & Containers
    "docker": "container orchestration deployment",
    "container": "containerized application docker",
    "compose": "docker-compose multi-container deployment",
    "docker-compose": "multi-container orchestration",
    "stack": "docker-compose deployment stack services",
    "volume": "docker persistent storage volume mount",
    "image": "container image build pull",
    "dind": "docker-in-docker container",
    "podman": "container runtime alternative docker",
    "k8s": "kubernetes container orchestration",
    "namespace": "kubernetes namespace isolation",
    
    # Monitoring & Observability
    "monitoring": "monitoring observability metrics alerts",
    "grafana": "monitoring dashboard visualization grafana",
    "prometheus": "metrics collection prometheus monitoring",
    "alertmanager": "alert routing notification prometheus",
    "loki": "log aggregation loki grafana",
    "telegraf": "metrics collection telegraf influxdb",
    "influxdb": "time series database metrics",
    "zabbix": "infrastructure monitoring zabbix alerts",
    "uptime": "service availability monitoring uptime",
    "healthcheck": "container health check monitoring",
    "ping": "network connectivity monitoring ping",
    
    # Security
    "security": "security hardening firewall vulnerability",
    "firewall": "network security firewall iptables ufw",
    "traefik": "reverse proxy traefik ssl tls routing",
    "nginx": "reverse proxy nginx web server ssl",
    "ssl": "ssl tls certificate https encryption",
    "certbot": "ssl certificate let's encrypt certbot",
    "auth": "authentication authorization security login",
    "2fa": "two-factor authentication security totp",
    "vpn": "virtual private network wireguard tailscale",
    "wireguard": "vpn wireguard tunnel security",
    "tailscale": "vpn tailscale mesh network zerotier",
    "fail2ban": "intrusion prevention fail2ban ssh security",
    "trivy": "container security vulnerability scanner",
    "adguard": "dns ad blocking adguardhome security",
    
    # Infrastructure
    "deploy": "deployment service launch container",
    "restart": "service restart container reload",
    "backup": "backup restore data persistence",
    "restic": "backup restic incremental encrypted",
    "migration": "service migration data transfer",
    "scale": "scaling resources capacity",
    "network": "network configuration dns dhcp vlan",
    "dns": "domain name system resolution",
    "reverse-proxy": "reverse proxy load balancer",
    "load-balancer": "load balancing traffic distribution",
    
    # RPi & Hardware
    "rpi": "raspberry pi arm sbc single board",
    "arm64": "arm64 aarch64 raspberry pi architecture",
    "cortex": "raspberry pi 5 cortex main server",
    "gpio": "general purpose io raspberry pi hardware",
    "sbc": "single board computer raspberry pi",
    
    # Dev & Tools
    "git": "version control git repository",
    "ci": "continuous integration automation",
    "cd": "continuous deployment automation pipeline",
    "mcp": "model context protocol ai tools integration",
    "api": "application programming interface rest",
    "webhook": "http callback webhook notification",
    "cron": "scheduled task cron job automation",
    "script": "automation script bash python",
    
    # AI & Models
    "ollama": "local ai model serving ollama llama",
    "llm": "large language model ai ollama",
    "embedding": "text embedding vector semantic",
    "phi3": "microsoft phi3 small language model",
    "qwen": "alibaba qwen language model",
    "nomic": "nomic embed text embedding model",
    "rag": "retrieval augmented generation ai",
    "tokenizer": "text tokenization nlp model",
    "inference": "model inference prediction ai",
    
    # Message Bus & Agents
    "message": "agent message communication bus",
    "route": "message routing agent dispatch",
    "handler": "message handler agent request",
    "bus": "message bus inter-agent communication",
    "mesh": "agent mesh network communication",
    "agent": "ai agent autonomous assistant",
    "swarm": "agent swarm collective intelligence",
    
    # French → English normalization map
    "surveille": "monitoring watch observe",
    "déploye": "deploy launch install",
    "installe": "install setup configure",
    "configure": "configure setup install",
    "sécurise": "secure harden protect",
    "vérifie": "verify check validate",
    "analyse": "analyze examine investigate",
    "teste": "test validate benchmark",
    "lance": "launch start run",
    "arrête": "stop shutdown halt",
    "redémarre": "restart reboot reload",
    "mets à jour": "update upgrade patch",
    "sauvegarde": "backup save persist",
    "restaure": "restore recover backup",
    "diagnostique": "diagnose troubleshoot debug",
    "optimise": "optimize improve enhance",
    "sécurise": "secure harden protect security",
    "veille": "research technology watch trend monitor",
}

# ── Route Definitions with Multi-Example Concepts ──────────────────────────

ROUTE_CONCEPTS = {
    "monitoring": [
        "monitoring dashboard metrics alerts grafana prometheus",
        "service health check uptime ping observability",
        "surveille les services monitoring alertes",
        "check service status health availability",
        "watch observe metrics performance graphs",
        "system performance monitoring cpu memory disk",
        "alert notification monitoring threshold",
    ],
    "security_alert": [
        "security alert vulnerability breach intrusion",
        "firewall block suspicious activity threat",
        "ssl certificate expired tls security",
        "fail2ban ban intrusion attempt ssh brute force",
        "trivy vulnerability scan container security",
        "security hardening audit compliance",
        "alerte sécurité intrusion vulnérabilité",
    ],
    "dev_request": [
        "develop code feature build implement",
        "debug fix bug error crash issue",
        "test unit integration validation benchmark",
        "git commit push merge branch repository",
        "api endpoint route handler middleware",
        "script automation tooling bash python",
        "développe code feature implémente",
    ],
    "ops_request": [
        "deploy service container docker stack",
        "restart reload service configuration update",
        "backup restore data persistence volume",
        "scale resources capacity load balance",
        "migration transfer move reconfigure",
        "install setup configure provision",
        "déploie installe configure service",
    ],
    "research_query": [
        "research documentation best practice guide",
        "how to tutorial explain learn understand",
        "compare evaluate benchmark alternative",
        "veille technology news update trend",
        "documentation reference manual specification",
        "recherche documentation guide tutoriel",
        "explain how works architecture design",
    ],
    "experiment_request": [
        "experiment test prototype proof of concept",
        "try attempt explore investigate novel",
        "benchmark measure evaluate performance",
        "poc mvp prototype validation testing",
        "sandbox playground isolated environment",
        "expérimente teste prototype validation",
        "innovate research explore new approach",
    ],
    "infrastructure_health": [
        "infrastructure server network dns dhcp",
        "hardware cpu memory disk temperature",
        "docker container status running stopped",
        "network connectivity ping latency bandwidth",
        "resource usage capacity planning",
        "rpi raspberry pi arm cortex sbc",
        "infrastructure réseau matériel performance",
    ],
    "agent_communication": [
        "agent message route handler bus mesh",
        "send message notify broadcast dispatch",
        "inter-agent communication protocol mesh",
        "agent identity skill capability routing",
        "message bus sqlite queue delivery",
        "agent message communication inter-agent",
        "route dispatch message handler queue",
    ],
}

# ── Keyword Override Rules ─────────────────────────────────────────────────
# These provide deterministic routing for unambiguous keywords

# IMPORTANT: Keywords here should be UNAMBIGUOUS — remove terms that appear in multiple contexts
# "docker" can be ops or infrastructure, "monitoring" can be a target or a domain, etc.
# Only use keywords that STRONGLY signal one specific route.

KEYWORD_OVERRIDES = {
    "monitoring": ["grafana", "prometheus", "alertmanager", "dashboard", "surveille"],
    "security_alert": ["firewall", "fail2ban", "trivy", "vulnerability", 
                       "intrusion", "breach", "ssl", "tls", "certbot"],
    "dev_request": ["debug", "bug", "git", "commit", "api endpoint", 
                    "feature request", "développe", "implémente", "code review"],
    "ops_request": ["déploie", "redémarre", "backup", 
                    "sauvegarde", "restore", "restaure", "migration"],
    "research_query": ["how to", "explain", "documentation", 
                       "guide", "tutorial", "compare", "veille", "tutoriel", "best practice"],
    "experiment_request": ["experiment", "expérimente", "poc", 
                          "prototype", "sandbox", "essaie"],
    "infrastructure_health": ["cpu", "memory",
                              "disk", "temperature", "rpi",
                              "latency", "bandwidth"],
    "agent_communication": ["message bus", "mesh", "handler", 
                           "dispatch", "broadcast"],
}


@dataclass
class RoutingResult:
    route: str
    confidence: float
    scores: Dict[str, float]
    method: str  # "keyword_override", "embedding", "hybrid"
    latency_ms: float


class DomainAugmentedRouter:
    """V3 Router with domain-augmented embeddings."""
    
    def __init__(self, ollama_url: str = OLLAMA_URL):
        self.ollama_url = ollama_url
        self.embedding_cache = self._load_cache()
        self.route_centroids: Dict[str, np.ndarray] = {}
        self.route_examples: Dict[str, List[np.ndarray]] = {}
        self._initialized = False
    
    def _load_cache(self) -> Dict[str, List[float]]:
        """Load embedding cache from disk."""
        try:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def _save_cache(self):
        """Save embedding cache to disk."""
        with open(CACHE_FILE, 'w') as f:
            json.dump(self.embedding_cache, f)
    
    def _cache_key(self, text: str) -> str:
        """Generate cache key for text."""
        return hashlib.md5(text.encode()).hexdigest()
    
    async def get_embedding(self, text: str) -> np.ndarray:
        """Get embedding for text, using cache when available."""
        cache_key = self._cache_key(text)
        
        if cache_key in self.embedding_cache:
            return np.array(self.embedding_cache[cache_key])
        
        import urllib.request
        import json as _json
        
        url = f"{self.ollama_url}/api/embed"
        data = _json.dumps({
            "model": EMBED_MODEL,
            "input": text
        }).encode()
        
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read().decode())
            embedding = result["embeddings"][0]
        
        self.embedding_cache[cache_key] = embedding
        self._save_cache()
        return np.array(embedding)
    
    def get_embedding_sync(self, text: str) -> np.ndarray:
        """Synchronous embedding retrieval."""
        cache_key = self._cache_key(text)
        
        if cache_key in self.embedding_cache:
            return np.array(self.embedding_cache[cache_key])
        
        import urllib.request
        import json as _json
        
        url = f"{self.ollama_url}/api/embed"
        data = _json.dumps({
            "model": EMBED_MODEL,
            "input": text
        }).encode()
        
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read().decode())
            embedding = result["embeddings"][0]
        
        self.embedding_cache[cache_key] = embedding
        self._save_cache()
        return np.array(embedding)
    
    def expand_query(self, query: str) -> str:
        """Expand query with domain vocabulary."""
        words = query.lower().split()
        expanded_terms = set()
        
        for word in words:
            # Check direct vocab match
            if word in HOMELAB_VOCAB:
                expanded_terms.add(HOMELAB_VOCAB[word])
            # Check partial match
            for key, value in HOMELAB_VOCAB.items():
                if key in word or word in key:
                    expanded_terms.add(value)
                    break
        
        if expanded_terms:
            return query + " " + " ".join(expanded_terms)
        return query
    
    def normalize_french(self, query: str) -> str:
        """Normalize French-specific terms."""
        q = query.lower()
        # French normalization patterns
        replacements = [
            (r"surveille\s+(\w+)", r"monitoring \1"),
            (r"déploie\s+(\w+)", r"deploy \1"),
            (r"installe\s+(\w+)", r"install \1"),
            (r"configure\s+(\w+)", r"configure \1"),
            (r"sécurise\s+(\w+)", r"secure \1"),
            (r"vérifie\s+(\w+)", r"verify \1"),
            (r"analyse\s+(\w+)", r"analyze \1"),
            (r"teste\s+(\w+)", r"test \1"),
            (r"lance\s+(\w+)", r"launch \1"),
            (r"arrête\s+(\w+)", r"stop \1"),
            (r"redémarre\s+(\w+)", r"restart \1"),
            (r"sécurise\s+(\w+)", r"secure harden \1"),
            (r"veille\s+(\w+)", r"research technology watch \1"),
        ]
        for pattern, replacement in replacements:
            q = re.sub(pattern, replacement, q)
        return q
    
    def keyword_check(self, query: str) -> Optional[Tuple[str, float]]:
        """Check for strong keyword matches. Returns (route, boost) or None."""
        q = query.lower()
        route_scores = {}
        
        for route, keywords in KEYWORD_OVERRIDES.items():
            score = 0.0
            for keyword in keywords:
                if keyword in q:
                    # Longer keyword matches get higher score
                    score += len(keyword.split()) * 0.3
            if score > 0:
                route_scores[route] = score
        
        if route_scores:
            best_route = max(route_scores, key=route_scores.get)
            best_score = route_scores[best_route]
            if best_score >= 0.3:  # Threshold for keyword override
                return best_route, min(best_score, 1.0)
        
        return None
    
    def detect_action_verb(self, query: str) -> Optional[str]:
        """Detect French action verbs that override topic-based routing.
        
        Key insight: "installe monitoring" → ops (install action) not monitoring (topic)
        But: "vérifie le firewall" → security (firewall topic) not monitoring (vérifie action)
        
        Strategy: Action verbs are only authoritative for ops-like actions.
        For ambiguous verbs (vérifie, surveille), let the embedding decide.
        """
        q = query.lower().strip()
        
        # Strong action verbs → always override (ops actions)
        ops_verbs = {
            "installe", "install", "déploie", "deploy", "configure",
            "redémarre", "restart", "lance", "launch", "arrête",
            "sauvegarde", "restaure", "backup",
        }
        # Topic-specific action verbs → only override if no strong topic signal
        topic_verbs = {
            "sécurise": "security_alert",
            "benchmark": "experiment_request",
        }
        # Weak action verbs → DON'T override, let embeddings decide
        # "vérifie", "surveille", "analyse" — context-dependent
        
        for verb in ops_verbs:
            if q.startswith(verb + " ") or q.startswith(verb + "s"):
                return "ops_request"
        
        for verb, route in topic_verbs.items():
            if q.startswith(verb + " ") or q.startswith(verb + "s"):
                return route
        
        return None

    def initialize(self):
        """Pre-compute route centroids from multi-example concepts."""
        if self._initialized:
            return
        
        print("🔄 Initializing route centroids...")
        for route, concepts in ROUTE_CONCEPTS.items():
            embeddings = []
            for concept in concepts:
                emb = self.get_embedding_sync(concept)
                embeddings.append(emb)
                print(f"  ✓ {route}: embedded '{concept[:50]}...'")
            
            self.route_examples[route] = embeddings
            # Compute centroid (mean of all example embeddings)
            self.route_centroids[route] = np.mean(embeddings, axis=0)
        
        self._initialized = True
        print(f"✅ Initialized {len(self.route_centroids)} route centroids")
    
    def route(self, query: str) -> RoutingResult:
        """Route a query to the best matching route."""
        start = time.time()
        
        if not self._initialized:
            self.initialize()
        
        # Step 1: Normalize French
        normalized = self.normalize_french(query)
        
        # Step 1: Detect action verbs on ORIGINAL query (before normalization changes it)
        action_route = self.detect_action_verb(query)
        
        # Step 2: Normalize French
        normalized = self.normalize_french(query)
        
        # Step 3: Check keyword overrides (strong matches)
        kw_result = self.keyword_check(normalized)
        
        # Step 4: Expand query with domain vocabulary
        expanded = self.expand_query(normalized)
        
        # Step 4: Get embedding for expanded query
        query_emb = self.get_embedding_sync(expanded)
        
        # Step 5: Compute similarity to all route centroids
        scores = {}
        for route, centroid in self.route_centroids.items():
            similarity = float(np.dot(query_emb, centroid) / 
                             (np.linalg.norm(query_emb) * np.linalg.norm(centroid)))
            scores[route] = similarity
        
        # Step 6: Also check max-similarity to individual examples
        max_scores = {}
        for route, examples in self.route_examples.items():
            max_sim = 0.0
            for example_emb in examples:
                sim = float(np.dot(query_emb, example_emb) / 
                           (np.linalg.norm(query_emb) * np.linalg.norm(example_emb)))
                max_sim = max(max_sim, sim)
            max_scores[route] = max_sim
        
        # Step 7: Combine centroid (40%) + max-example (30%) + keyword (30%) + action verb boost
        combined_scores = {}
        for route in scores:
            centroid_score = scores.get(route, 0)
            max_score = max_scores.get(route, 0)
            kw_score = 0.0
            if kw_result and kw_result[0] == route:
                kw_score = kw_result[1]
            action_boost = 0.5 if action_route == route else 0.0
            
            combined = centroid_score * 0.4 + max_score * 0.3 + kw_score * 0.3 + action_boost
            combined_scores[route] = combined
        
        # Step 8: Select best route
        best_route = max(combined_scores, key=combined_scores.get)
        best_score = combined_scores[best_route]
        
        # Determine method
        method = "hybrid"
        if action_route and action_route == best_route:
            method = "action_verb"
        elif kw_result and kw_result[0] == best_route and kw_result[1] >= 0.5:
            method = "keyword_override"
        elif kw_result is None and action_route is None:
            method = "embedding"
        
        latency = (time.time() - start) * 1000
        
        return RoutingResult(
            route=best_route,
            confidence=best_score,
            scores=combined_scores,
            method=method,
            latency_ms=latency
        )


def run_benchmark():
    """Run comprehensive benchmark against known test cases."""
    
    # Test cases: (query, expected_route)
    test_cases = [
        # Monitoring
        ("Check monitoring dashboard", "monitoring"),
        ("Surveille les services", "monitoring"),
        ("Grafana alerts not working", "monitoring"),
        ("Show me the metrics", "monitoring"),
        ("Alertes de monitoring", "monitoring"),
        
        # Security
        ("Security alert: suspicious activity", "security_alert"),
        ("Vérifie le firewall", "security_alert"),
        ("SSL certificate expired", "security_alert"),
        ("Trivy scan found vulnerabilities", "security_alert"),
        ("Sécurise le serveur", "security_alert"),
        
        # Dev
        ("Debug the API endpoint", "dev_request"),
        ("Fix the bug in handler", "dev_request"),
        ("Write a new script", "dev_request"),
        ("Code review needed", "dev_request"),
        ("Développe une nouvelle feature", "dev_request"),
        
        # Ops
        ("Deploy the new stack", "ops_request"),
        ("Redémarre le container", "ops_request"),
        ("Backup the database", "ops_request"),
        ("Déploie monitoring sur cortex", "ops_request"),
        ("Installe le nouveau service", "ops_request"),
        ("Configure le reverse proxy", "ops_request"),
        
        # Research
        ("Research best practices for Docker", "research_query"),
        ("How to setup WireGuard VPN", "research_query"),
        ("Explain the architecture", "research_query"),
        ("Compare Ollama vs vLLM", "research_query"),
        ("Veille technologique", "research_query"),
        
        # Experiment
        ("Test the new embedding approach", "experiment_request"),
        ("Benchmark the model performance", "experiment_request"),
        ("Try the prototype", "experiment_request"),
        ("Expérimente avec nomic-embed", "experiment_request"),
        ("Validate the POC", "experiment_request"),
        
        # Infrastructure
        ("Server CPU usage too high", "infrastructure_health"),
        ("Network latency issues", "infrastructure_health"),
        ("Disk space running low", "infrastructure_health"),
        ("Docker container status check", "infrastructure_health"),
        ("RPi temperature monitoring", "infrastructure_health"),
        
        # Agent Communication
        ("Route this message to Tachikoma", "agent_communication"),
        ("Send message via bus", "agent_communication"),
        ("Agent mesh communication", "agent_communication"),
        ("Broadcast to all agents", "agent_communication"),
        ("Dispatch handler for route", "agent_communication"),
    ]
    
    print("=" * 80)
    print("BENCHMARK: Domain-Augmented Embeddings Router V3")
    print("=" * 80)
    
    router = DomainAugmentedRouter()
    router.initialize()
    
    correct = 0
    total = len(test_cases)
    results = []
    
    for query, expected in test_cases:
        result = router.route(query)
        is_correct = result.route == expected
        if is_correct:
            correct += 1
        
        status = "✅" if is_correct else "❌"
        results.append({
            "query": query,
            "expected": expected,
            "got": result.route,
            "correct": is_correct,
            "confidence": result.confidence,
            "method": result.method,
            "latency_ms": result.latency_ms
        })
        
        print(f"{status} '{query}' → {result.route} (expected: {expected}, "
              f"conf: {result.confidence:.3f}, method: {result.method}, "
              f"latency: {result.latency_ms:.1f}ms)")
    
    accuracy = correct / total * 100
    avg_latency = sum(r["latency_ms"] for r in results) / len(results)
    method_counts = {}
    for r in results:
        method_counts[r["method"]] = method_counts.get(r["method"], 0) + 1
    
    print("\n" + "=" * 80)
    print(f"RESULTS: {correct}/{total} = {accuracy:.1f}% accuracy")
    print(f"Average latency: {avg_latency:.1f}ms")
    print(f"Methods used: {method_counts}")
    print("=" * 80)
    
    # Show failures
    failures = [r for r in results if not r["correct"]]
    if failures:
        print("\n❌ Failures:")
        for f in failures:
            print(f"  '{f['query']}' → got '{f['got']}' (expected '{f['expected']}')")
    
    # Save results
    benchmark_data = {
        "accuracy": accuracy,
        "correct": correct,
        "total": total,
        "avg_latency_ms": avg_latency,
        "method_counts": method_counts,
        "results": results,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    
    with open("benchmark-v3-results.json", "w") as f:
        json.dump(benchmark_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n📊 Results saved to benchmark-v3-results.json")
    
    return accuracy


# Edge cases from V2 that failed
EDGE_CASES = [
    ("installe monitoring", "ops_request"),  # V2: wrong → dev_request
    ("déploie security", "ops_request"),      # V2: wrong → infrastructure_health
    ("configure le firewall", "ops_request"),
    ("sécurise le serveur docker", "security_alert"),
    ("redémarre le service monitoring", "ops_request"),
]


def run_edge_case_benchmark():
    """Test specifically the edge cases that V2 got wrong."""
    print("\n" + "=" * 80)
    print("EDGE CASE BENCHMARK: V2 Failure Cases")
    print("=" * 80)
    
    router = DomainAugmentedRouter()
    router.initialize()
    
    correct = 0
    for query, expected in EDGE_CASES:
        result = router.route(query)
        is_correct = result.route == expected
        if is_correct:
            correct += 1
        
        status = "✅" if is_correct else "❌"
        print(f"{status} '{query}' → {result.route} (expected: {expected}, "
              f"conf: {result.confidence:.3f}, method: {result.method})")
    
    print(f"\nEdge cases: {correct}/{len(EDGE_CASES)} = {correct/len(EDGE_CASES)*100:.1f}%")
    return correct


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--edge":
        run_edge_case_benchmark()
    elif len(sys.argv) > 1 and sys.argv[1] == "--route":
        router = DomainAugmentedRouter()
        router.initialize()
        query = " ".join(sys.argv[2:])
        result = router.route(query)
        print(f"Route: {result.route} (confidence: {result.confidence:.3f}, method: {result.method})")
    else:
        run_benchmark()
