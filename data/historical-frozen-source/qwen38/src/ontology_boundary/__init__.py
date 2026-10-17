"""Finite ontology boundary oracle; no model or network actions."""

from .oracle import (
    Closure, ExternalGrant, FIELDS, HornRule, MAX_PUBLIC_CLASSES, Ontology,
    PERMISSIONS, closure, compare_flow_eligibility, compare_ontologies,
    flow_decision, seed_profiles,
)
from .rdf_adapter import (
    CLASS_NAMESPACE, POLICY_NAMESPACE, crosscheck_ontology, crosscheck_profile,
    dependency_versions, ontology_from_rdf, ontology_to_rdf, owlrl_closure,
    parse_ontology, validate_rdf_syntax,
)

__all__ = [
    "Closure", "ExternalGrant", "FIELDS", "HornRule", "MAX_PUBLIC_CLASSES", "Ontology",
    "PERMISSIONS", "closure", "compare_flow_eligibility", "compare_ontologies",
    "flow_decision", "seed_profiles", "CLASS_NAMESPACE", "POLICY_NAMESPACE",
    "crosscheck_ontology", "crosscheck_profile", "dependency_versions", "ontology_from_rdf",
    "ontology_to_rdf", "owlrl_closure", "parse_ontology", "validate_rdf_syntax",
]
