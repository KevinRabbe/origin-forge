from __future__ import annotations

import argparse
import json
from pathlib import Path

from .project_binding_inspection import BindingInspector
from .project_intelligence import ProjectIntelligenceError, ProjectIntelligenceService
from .project_models import (
    BindingStatus,
    DesignRuleCategory,
    DesignRuleStatus,
    EntityKind,
    EntityStatus,
    ImpactDirection,
    ImpactQuery,
    RelationStatus,
    RelationType,
)
from .runtime import OriginForgeRuntime, RuntimeInvariantError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.project_intelligence_cli",
        description="Read-only inspection of Origin Forge Project Intelligence.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="show Project Intelligence catalog counts")

    entity_list = commands.add_parser("entity-list", help="list semantic Entities")
    entity_list.add_argument("--kind", choices=[value.value for value in EntityKind])
    entity_list.add_argument("--status", choices=[value.value for value in EntityStatus])
    entity_show = commands.add_parser("entity-show", help="show one Entity")
    entity_show.add_argument("entity_id")

    relation_list = commands.add_parser("relation-list", help="list typed Entity relations")
    relation_list.add_argument("--entity")
    relation_list.add_argument("--status", choices=[value.value for value in RelationStatus])
    relation_show = commands.add_parser("relation-show", help="show one Entity relation")
    relation_show.add_argument("relation_id")

    binding_list = commands.add_parser("binding-list", help="list Entity bindings")
    binding_list.add_argument("--entity")
    binding_list.add_argument("--status", choices=[value.value for value in BindingStatus])
    binding_show = commands.add_parser("binding-show", help="show one Entity binding")
    binding_show.add_argument("binding_id")
    binding_inspect = commands.add_parser(
        "binding-inspect", help="inspect one FILE binding against current repository bytes"
    )
    binding_inspect.add_argument("binding_id")

    rule_list = commands.add_parser("rule-list", help="list structured Design Rules")
    rule_list.add_argument("--status", choices=[value.value for value in DesignRuleStatus])
    rule_list.add_argument("--category", choices=[value.value for value in DesignRuleCategory])
    rule_show = commands.add_parser("rule-show", help="show one Design Rule")
    rule_show.add_argument("rule_id")

    impact = commands.add_parser("impact", help="run deterministic bounded Entity impact analysis")
    impact.add_argument("root_entity_ids", nargs="+")
    impact.add_argument(
        "--relation-type",
        action="append",
        choices=[value.value for value in RelationType],
        dest="relation_types",
    )
    impact.add_argument(
        "--direction",
        choices=[value.value for value in ImpactDirection],
        default=ImpactDirection.BOTH.value,
    )
    impact.add_argument("--max-depth", type=int, default=4)
    impact.add_argument("--max-entities", type=int, default=256)
    impact.add_argument("--max-relations", type=int, default=1024)
    impact.add_argument("--max-bindings", type=int, default=1024)
    impact.add_argument("--max-rules", type=int, default=256)
    impact.add_argument("--no-bindings", action="store_true")
    impact.add_argument("--no-rules", action="store_true")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    intelligence = ProjectIntelligenceService(runtime)

    try:
        if args.command == "status":
            _print(
                {
                    "entities": len(intelligence.list_entities()),
                    "active_entities": len(
                        intelligence.list_entities(status=EntityStatus.ACTIVE)
                    ),
                    "relations": len(intelligence.list_relations()),
                    "active_relations": len(
                        intelligence.list_relations(status=RelationStatus.ACTIVE)
                    ),
                    "bindings": len(intelligence.list_bindings()),
                    "active_bindings": len(
                        intelligence.list_bindings(status=BindingStatus.ACTIVE)
                    ),
                    "design_rules": len(intelligence.list_design_rules()),
                    "active_design_rules": len(
                        intelligence.list_design_rules(status=DesignRuleStatus.ACTIVE)
                    ),
                    "model_execution_enabled": False,
                    "canonical_mutation_enabled": False,
                    "automatic_context_integration_enabled": False,
                }
            )
            return 0

        if args.command == "entity-list":
            _print(
                {
                    "entities": intelligence.list_entities(
                        kind=EntityKind(args.kind) if args.kind else None,
                        status=EntityStatus(args.status) if args.status else None,
                    )
                }
            )
            return 0
        if args.command == "entity-show":
            _print(intelligence.get_entity(args.entity_id))
            return 0

        if args.command == "relation-list":
            _print(
                {
                    "relations": intelligence.list_relations(
                        entity_id=args.entity,
                        status=RelationStatus(args.status) if args.status else None,
                    )
                }
            )
            return 0
        if args.command == "relation-show":
            _print(intelligence.get_relation(args.relation_id))
            return 0

        if args.command == "binding-list":
            _print(
                {
                    "bindings": intelligence.list_bindings(
                        entity_id=args.entity,
                        status=BindingStatus(args.status) if args.status else None,
                    )
                }
            )
            return 0
        if args.command == "binding-show":
            _print(intelligence.get_binding(args.binding_id))
            return 0
        if args.command == "binding-inspect":
            inspection = BindingInspector(intelligence).inspect(args.binding_id)
            _print(inspection.to_dict())
            return 0

        if args.command == "rule-list":
            _print(
                {
                    "design_rules": intelligence.list_design_rules(
                        status=DesignRuleStatus(args.status) if args.status else None,
                        category=DesignRuleCategory(args.category) if args.category else None,
                    )
                }
            )
            return 0
        if args.command == "rule-show":
            _print(intelligence.get_design_rule(args.rule_id))
            return 0

        if args.command == "impact":
            relation_types = (
                tuple(RelationType(value) for value in args.relation_types)
                if args.relation_types
                else tuple(RelationType)
            )
            report = intelligence.impact(
                ImpactQuery(
                    tuple(args.root_entity_ids),
                    relation_types=relation_types,
                    direction=ImpactDirection(args.direction),
                    max_depth=args.max_depth,
                    max_entities=args.max_entities,
                    max_relations=args.max_relations,
                    max_bindings=args.max_bindings,
                    max_rules=args.max_rules,
                    include_bindings=not args.no_bindings,
                    include_design_rules=not args.no_rules,
                )
            )
            _print(report.to_dict())
            return 0

    except KeyError as exc:
        _print({"error": "NOT_FOUND", "detail": str(exc)})
        return 3
    except (
        ProjectIntelligenceError,
        RuntimeInvariantError,
        OSError,
        ValueError,
    ) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
