"""
router/router.py
Cerveau du bridge : routing intelligent entre les handlers Grok.
"""

import re
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger("grok-mcp-bridge.router")


class TaskType(str, Enum):
    DISPATCH   = "dispatch"
    CRITIQUE   = "critique"
    CODE_TEST  = "code_test"
    RESEARCH   = "research"


@dataclass
class RouteDecision:
    task_type: TaskType
    confidence: float
    reasoning: str


# Patterns pondérés (poids plus élevé = plus discriminant)
_CRITIQUE_PATTERNS = [
    (r"\b(critique|critiqu|review|audit|analyse critique|évaluation critique)\b", 2.0),
    (r"\b(risque|risk|faiblesse|danger|faille|problème majeur)\b", 2.2),
    (r"\b(stratégie|strategy|business plan|décision|que penses-tu|ton avis)\b", 1.6),
    (r"\b(améliorer|optimiser|recommandation|points faibles)\b", 1.3),
]

_CODE_TEST_PATTERNS = [
    (r"\b(debug|débug|fix|corrige|bug|erreur|traceback|exception|TypeError)\b", 2.5),
    (r"\b(test|tester|pytest|unittest|run|exécute|lance)\b", 1.8),
    (r"```(python|py|javascript|js|bash|sql)", 2.8),           # Bloc de code fort
    (r"\b(def |class |import |function |pip install|npm)\b", 1.4),
]

_RESEARCH_PATTERNS = [
    (r"\b(recherche|search|veille|trouve|cherche|market|marché|tendance)\b", 1.8),
    (r"\b(prix|price|tarif|cours|évolution|trend|concurrent|competitor)\b", 2.0),
    (r"\b(202[5-6]|actualité|news|récent)\b", 1.5),
    (r"\b(distillerie|distillery|cooperage|whisky|whiskey|bourbon|scotch)\b", 1.7),
    (r"\b(fût|fûts|barrique|barriques|cask|casks|tonnelier|tonnellerie|maturation)\b", 2.2),
]


def _score_patterns(text: str, patterns: list[tuple[str, float]]) -> float:
    """Scoring pondéré intelligent."""
    text_lower = text.lower()
    total_score = 0.0
    max_possible = 0.0
    for pattern, weight in patterns:
        max_possible += weight
        if re.search(pattern, text_lower):
            total_score += weight
    return total_score / max_possible if max_possible > 0 else 0.0


def route(prompt: str, explicit_task: Optional[str] = None) -> RouteDecision:
    """
    Décide du meilleur handler pour le prompt.
    """
    # 1. Routing explicite (prioritaire)
    if explicit_task:
        mapping = {
            "critique": TaskType.CRITIQUE,
            "review":   TaskType.CRITIQUE,
            "code":     TaskType.CODE_TEST,
            "test":     TaskType.CODE_TEST,
            "debug":    TaskType.CODE_TEST,
            "research": TaskType.RESEARCH,
            "search":   TaskType.RESEARCH,
            "market":   TaskType.RESEARCH,
        }
        task = mapping.get(explicit_task.lower().strip())
        if task:
            logger.info(f"Explicit routing → {task.value}")
            return RouteDecision(
                task_type=task,
                confidence=1.0,
                reasoning=f"Routing explicite : {explicit_task}"
            )

    # 2. Scoring automatique
    scores = {
        TaskType.CRITIQUE:  _score_patterns(prompt, _CRITIQUE_PATTERNS),
        TaskType.CODE_TEST: _score_patterns(prompt, _CODE_TEST_PATTERNS),
        TaskType.RESEARCH:  _score_patterns(prompt, _RESEARCH_PATTERNS),
    }

    best_task = max(scores, key=lambda t: scores[t])
    best_score = scores[best_task]

    # Seuil plus réaliste
    if best_score >= 0.45:
        decision = RouteDecision(
            task_type=best_task,
            confidence=round(best_score, 2),
            reasoning=f"Auto-routing fort ({best_task.value} = {best_score:.2f})"
        )
    else:
        decision = RouteDecision(
            task_type=TaskType.DISPATCH,
            confidence=0.65,
            reasoning=f"Aucun signal fort détecté (max={best_score:.2f}) → dispatch générique"
        )

    logger.info(f"Route → {decision.task_type.value} | confidence={decision.confidence} | {decision.reasoning}")
    return decision
