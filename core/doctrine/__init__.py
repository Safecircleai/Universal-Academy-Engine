"""UAE v4 — Doctrine Sovereignty Layer core modules."""
from core.doctrine.precedence_engine import PrecedenceEngine, PrecedenceViolation
from core.doctrine.conflict_detector import ConflictDetector, DoctrineConflict
from core.doctrine.dependency_graph import DoctrineDependencyGraph

__all__ = [
    "PrecedenceEngine",
    "PrecedenceViolation",
    "ConflictDetector",
    "DoctrineConflict",
    "DoctrineDependencyGraph",
]
