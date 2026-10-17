"""Restricted RDF bridge and independent OWL-RL materialization crosscheck.

Only named classes, subclass edges, intersection antecedents with a named
subclass head, and pairwise disjointness are accepted. No imports, arbitrary
OWL, annotations, individuals, property rules, or external grants are accepted.
SHACL checks syntax only; the pure-set oracle is the experiment's authority.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import Iterable

from .oracle import Closure, HornRule, Ontology, PERMISSIONS, closure, seed_profiles


CLASS_NAMESPACE = "urn:ontology-boundary:class:"
POLICY_NAMESPACE = "urn:ontology-boundary:policy:"
CONTEXT_IRI = "urn:ontology-boundary:context"


def dependency_versions() -> dict[str, str]:
    return {name: version(name) for name in ("rdflib", "owlrl", "pyshacl")}


def ontology_to_rdf(ontology: Ontology):
    from rdflib import BNode, Graph, URIRef
    from rdflib.collection import Collection
    from rdflib.namespace import OWL, RDF, RDFS

    graph = Graph()

    def node(name):
        return URIRef((POLICY_NAMESPACE if name in PERMISSIONS else CLASS_NAMESPACE) + name)

    for name in sorted(ontology.classes) + list(PERMISSIONS):
        graph.add((node(name), RDF.type, OWL.Class))
    for sub, sup in ontology.subclass:
        graph.add((node(sub), RDFS.subClassOf, node(sup)))
    for index, rule in enumerate(ontology.rules):
        intersection = BNode(f"intersection-{index}")
        items = BNode(f"items-{index}")
        graph.add((intersection, RDF.type, OWL.Class))
        graph.add((intersection, OWL.intersectionOf, items))
        Collection(graph, items, [node(x) for x in sorted(rule.antecedents)])
        graph.add((intersection, RDFS.subClassOf, node(rule.head)))
    for left, right in ontology.disjoint:
        graph.add((node(left), OWL.disjointWith, node(right)))
    return graph


def ontology_from_rdf(graph) -> Ontology:
    """Compile an in-memory RDF graph, rejecting every unsupported triple.

    This does not load remote locations or follow owl:imports. A caller must
    not pass an already expanded OWL-RL graph: its extra axioms are unsupported.
    """
    from rdflib import BNode, Graph, URIRef
    from rdflib.namespace import OWL, RDF, RDFS

    if not isinstance(graph, Graph):
        raise ValueError("expected an in-memory RDFLib Graph")
    allowed_predicates = {RDF.type, RDFS.subClassOf, OWL.intersectionOf, OWL.disjointWith, RDF.first, RDF.rest}
    for subject, predicate, obj in graph:
        if predicate not in allowed_predicates:
            raise ValueError(f"unsupported RDF predicate: {predicate}")
        if predicate == RDF.type and obj != OWL.Class:
            raise ValueError("only owl:Class declarations are supported")
        if predicate == RDF.type and not isinstance(subject, (URIRef, BNode)):
            raise ValueError("class declaration subject must be IRI or blank node")
    declarations = set(graph.subjects(RDF.type, OWL.Class))

    def named(node, *, allow_permission=True):
        if not isinstance(node, URIRef):
            raise ValueError("expected a named class/head IRI")
        text = str(node)
        if text.startswith(CLASS_NAMESPACE):
            name = text[len(CLASS_NAMESPACE):]
            if name in PERMISSIONS:
                raise ValueError("policy heads must use the fixed policy namespace")
        elif allow_permission and text.startswith(POLICY_NAMESPACE) and text[len(POLICY_NAMESPACE):] in PERMISSIONS:
            name = text[len(POLICY_NAMESPACE):]
        else:
            raise ValueError("class/head is outside the fixed namespaces")
        if node not in declarations:
            raise ValueError("class/head IRI lacks owl:Class declaration")
        return name

    classes = set()
    for node in declarations:
        if isinstance(node, URIRef):
            name = named(node)
            if name not in PERMISSIONS:
                classes.add(name)
    intersections = set(graph.subjects(OWL.intersectionOf, None))
    if any(not isinstance(node, BNode) or node not in declarations for node in intersections):
        raise ValueError("intersection must be a declared anonymous owl:Class")
    anonymous_declarations = {x for x in declarations if isinstance(x, BNode)}
    if anonymous_declarations != intersections:
        raise ValueError("unsupported anonymous class declaration")
    consumed_lists = set()
    antecedents = {}
    for node in intersections:
        heads = list(graph.objects(node, OWL.intersectionOf))
        if len(heads) != 1:
            raise ValueError("intersection must have exactly one RDF list")
        cursor = heads[0]
        items, seen = [], set()
        while cursor != RDF.nil:
            if not isinstance(cursor, BNode) or cursor in seen:
                raise ValueError("intersection list must be finite, acyclic blank nodes")
            seen.add(cursor)
            consumed_lists.add(cursor)
            first, rest = list(graph.objects(cursor, RDF.first)), list(graph.objects(cursor, RDF.rest))
            if len(first) != 1 or len(rest) != 1:
                raise ValueError("RDF list node must have exactly one first/rest")
            items.append(named(first[0], allow_permission=False))
            cursor = rest[0]
        if not items or len(items) != len(set(items)):
            raise ValueError("intersection antecedents must be nonempty and unique")
        if not list(graph.objects(node, RDFS.subClassOf)):
            raise ValueError("intersection has no named rule head")
        antecedents[node] = frozenset(items)
    if set(graph.subjects(RDF.first, None)) != consumed_lists or set(graph.subjects(RDF.rest, None)) != consumed_lists:
        raise ValueError("unused or malformed RDF list triples")
    subclass, rules, disjoint = [], [], []
    for sub, sup in graph.subject_objects(RDFS.subClassOf):
        head = named(sup)
        if sub in intersections:
            rules.append(HornRule(antecedents[sub], head))
        else:
            subclass.append((named(sub, allow_permission=False), head))
    for left, right in graph.subject_objects(OWL.disjointWith):
        disjoint.append((named(left, allow_permission=False), named(right, allow_permission=False)))
    # Guard nonsensical placements of the otherwise allowlisted predicates.
    for subject, predicate, obj in graph:
        if predicate in (RDF.first, RDF.rest) and subject not in consumed_lists:
            raise ValueError("list predicate on a non-list node")
        if predicate == OWL.intersectionOf and subject not in intersections:
            raise ValueError("unsupported intersection placement")
    return Ontology(classes, subclass, rules, disjoint)


def parse_ontology(data: str, *, format: str = "turtle") -> Ontology:
    """Parse supplied bytes/text only; supported formats cannot import contexts."""
    from rdflib import Graph
    if format not in ("turtle", "nt") or not isinstance(data, str):
        raise ValueError("only supplied Turtle or N-Triples text is supported")
    return ontology_from_rdf(Graph().parse(data=data, format=format))


def validate_rdf_syntax(graph) -> dict:
    """Combine explicit fragment rejection with SHACL structure validation."""
    from rdflib import Graph
    from pyshacl import validate

    try:
        ontology_from_rdf(graph)
    except (ValueError, TypeError) as error:
        return {"conforms": False, "fragment_supported": False, "errors": [str(error)],
                "authority_decision": False}
    shapes = Graph().parse(data='''
      @prefix sh: <http://www.w3.org/ns/shacl#> .
      @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
      @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
      @prefix owl: <http://www.w3.org/2002/07/owl#> .
      [] a sh:NodeShape; sh:targetClass owl:Class;
         sh:nodeKind sh:BlankNodeOrIRI;
         sh:property [sh:path rdfs:subClassOf; sh:nodeKind sh:IRI];
         sh:property [sh:path owl:disjointWith; sh:nodeKind sh:IRI];
         sh:property [sh:path owl:intersectionOf; sh:nodeKind sh:BlankNode; sh:maxCount 1].
      [] a sh:NodeShape; sh:targetSubjectsOf rdf:first;
         sh:nodeKind sh:BlankNode;
         sh:property [sh:path rdf:first; sh:minCount 1; sh:maxCount 1; sh:nodeKind sh:IRI];
         sh:property [sh:path rdf:rest; sh:minCount 1; sh:maxCount 1; sh:nodeKind sh:BlankNodeOrIRI].
    ''', format="turtle")
    conforms, _, report = validate(graph, shacl_graph=shapes, inference="none", advanced=False,
                                   js=False, do_owl_imports=False, inplace=False)
    return {"conforms": bool(conforms), "fragment_supported": True,
            "errors": [] if conforms else [str(report)], "authority_decision": False,
            "inference": "none", "external_imports": False}


def owlrl_closure(ontology: Ontology, seed_types: Iterable[str]) -> Closure:
    """Independent OWL-RL inference, restricted projection and fail-closed gate."""
    from rdflib import URIRef
    from rdflib.namespace import RDF
    from owlrl import DeductiveClosure, OWLRL_Semantics

    if isinstance(seed_types, (str, bytes)):
        raise ValueError("expected a collection of seed classes")
    seeds = frozenset(seed_types)
    if not seeds.issubset(ontology.classes):
        raise ValueError("unknown seed class or permission")
    graph = ontology_to_rdf(ontology)
    context = URIRef(CONTEXT_IRI)
    for seed in seeds:
        graph.add((context, RDF.type, URIRef(CLASS_NAMESPACE + seed)))
    DeductiveClosure(OWLRL_Semantics, axiomatic_triples=False, datatype_axioms=False).expand(graph)
    types = set(graph.objects(context, RDF.type))
    classes = frozenset(name for name in ontology.classes if URIRef(CLASS_NAMESPACE + name) in types)
    derived = frozenset(name for name in PERMISSIONS if URIRef(POLICY_NAMESPACE + name) in types)
    conflicts = tuple((a, b) for a, b in ontology.disjoint if a in classes and b in classes)
    # Materializer iterations are intentionally not conflated with oracle rounds.
    return Closure(seeds, classes, derived, derived if not conflicts else frozenset(), conflicts, -1)


def crosscheck_profile(ontology: Ontology, seed_types: Iterable[str]) -> dict:
    if isinstance(seed_types, (str, bytes)):
        raise ValueError("expected a collection of seed classes")
    seeds = frozenset(seed_types)
    reference, materialized = closure(ontology, seeds), owlrl_closure(ontology, seeds)
    fields = ("seed_types", "class_types", "derived_permissions", "permissions", "inconsistencies")
    matches = {name: getattr(reference, name) == getattr(materialized, name) for name in fields}
    return {"matches": all(matches.values()), "field_matches": matches,
            "reference": reference.to_dict(), "owlrl": materialized.to_dict(),
            "versions": dependency_versions()}


def crosscheck_ontology(ontology: Ontology, public_classes: Iterable[str]) -> dict:
    profiles = seed_profiles(public_classes)
    checks = [crosscheck_profile(ontology, p) for p in profiles]
    syntax = validate_rdf_syntax(ontology_to_rdf(ontology))
    return {"matches": syntax["conforms"] and all(c["matches"] for c in checks),
            "syntax": syntax, "profiles_checked": len(checks), "profiles": checks,
            "scope": "declared finite seed profiles only; not a universal OWL entailment test"}
