from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path

from .adapters.llamacpp import LlamaCppAdapter, LlamaCppError
from .config import load_config
from .context_preview import build_context_preview
from .doctor import inspect_project
from .orchestration_cli import main as bounded_attempt_main
from .patches import PatchValidationError
from .production_goal_bootstrap_operator import (
    GoalBootstrapOperatorBlocked,
    GoalBootstrapOperatorError,
    bootstrap_goal_once,
    inspect_goal_bootstrap_status_readonly,
    recover_goal_once,
)
from .production_manager_advance_bounded import advance_production_manager_bounded
from .production_manager_advance_status import inspect_manager_advance_status_readonly
from .repository import RepositoryAccessError
from .review import inspect_task_review, record_task_review_decision
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .sandbox import SandboxPolicyError, SandboxUnavailable
from .sandbox_factory import create_sandbox_backend
from .sandbox_verification import SandboxedWorkspaceVerifier
from .service import StaleRevision, VerificationRequired
from .state import FlowStatus, GoalStatus, InvalidTransition, RunStatus, TaskStatus
from .worker import LocalPatchWorker


def _enum_value(enum_type: type[StrEnum], value: str):
    try:
        return enum_type(value.upper())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise argparse.ArgumentTypeError(f"expected one of: {allowed}") from exc


def _goal_status(value: str) -> GoalStatus:
    return _enum_value(GoalStatus, value)


def _flow_status(value: str) -> FlowStatus:
    return _enum_value(FlowStatus, value)


def _task_status(value: str) -> TaskStatus:
    return _enum_value(TaskStatus, value)


def _run_status(value: str) -> RunStatus:
    status = _enum_value(RunStatus, value)
    if status == RunStatus.RUNNING:
        raise argparse.ArgumentTypeError("run finish requires a terminal status")
    return status


def _print(value, *, stream=None) -> None:
    print(
        json.dumps(value, indent=2, sort_keys=True, default=str),
        file=stream or sys.stdout,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="origin-forge")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root (default: current directory)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init", help="initialize Origin Forge state")
    init_parser.add_argument("--name", help="project name (default: directory name)")
    sub.add_parser("status", help="show durable runtime status")
    doctor = sub.add_parser("doctor", help="inspect project readiness without changing state")
    doctor.add_argument("--strict", action="store_true", help="return failure when any readiness check fails")

    recover_parser = sub.add_parser(
        "recover", help="inspect or reconcile interrupted RUNNING records"
    )
    recover_parser.add_argument("--apply", action="store_true")

    manager = sub.add_parser(
        "manager", help="inspect or explicitly advance governed production"
    ).add_subparsers(dest="manager_command", required=True)
    manager.add_parser("status", help="show read-only governed Manager status")
    manager.add_parser(
        "advance", help="perform exactly one fixed bounded Manager invocation"
    )
    sub.add_parser(
        "advance", help="perform exactly one fixed bounded Manager invocation"
    )
    context = sub.add_parser("context", help="inspect bounded Task context")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    context_preview = context_sub.add_parser(
        "preview", help="preview selected context without starting an attempt"
    )
    context_preview.add_argument("task_id")
    context_mode = context_preview.add_mutually_exclusive_group(required=True)
    context_mode.add_argument("--file", action="append", dest="files")
    context_mode.add_argument("--auto-context", action="store_true")
    context_preview.add_argument("--seed-file", action="append", default=[], dest="seed_files")
    context_preview.add_argument("--structural-context", action="store_true")
    context_preview.add_argument("--semantic-context", action="store_true")

    attempt = sub.add_parser("attempt", help="run exactly one bounded coding attempt")
    attempt.add_argument("task_id")
    attempt_mode = attempt.add_mutually_exclusive_group(required=True)
    attempt_mode.add_argument("--file", action="append", dest="files")
    attempt_mode.add_argument("--auto-context", action="store_true")
    attempt.add_argument("--seed-file", action="append", default=[], dest="seed_files")
    attempt.add_argument("--structural-context", action="store_true")
    attempt.add_argument("--semantic-context", action="store_true")
    attempt.add_argument("--base-url", default="http://127.0.0.1:8080")
    attempt.add_argument("--model", default="local-model")
    attempt.add_argument("--api-key", default="no-key")
    attempt.add_argument("--timeout", type=float, default=300.0)
    attempt.add_argument("--max-tokens", type=int, default=4096)
    attempt.add_argument("--temperature", type=float, default=0.2)
    attempt.add_argument("--allow-remote", action="store_true")
    review = sub.add_parser("review", help="inspect reviewable Task evidence")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    review_inspect = review_sub.add_parser("inspect", help="inspect one Task review projection")
    review_inspect.add_argument("task_id")
    for action in ("accept", "reject", "refine", "replace"):
        review_action = review_sub.add_parser(action, help=f"record a human {action} decision")
        review_action.add_argument("task_id")
        review_action.add_argument("--rationale", required=True)

    goal = sub.add_parser("goal", help="manage goals").add_subparsers(
        dest="goal_command", required=True
    )
    goal_create = goal.add_parser("create")
    goal_create.add_argument("objective")
    goal_create.add_argument("--success", action="append", default=[])
    goal_create.add_argument("--constraint", action="append", default=[])
    goal_create.add_argument("--priority", type=int, default=0)
    goal.add_parser("list")
    goal_show = goal.add_parser("show")
    goal_show.add_argument("goal_id")
    goal_inspect = goal.add_parser("inspect", help="inspect one goal (read-only alias for show)")
    goal_inspect.add_argument("goal_id")
    goal_transition = goal.add_parser("transition")
    goal_transition.add_argument("goal_id")
    goal_transition.add_argument("status", type=_goal_status)
    goal_transition.add_argument("--revision", required=True, type=int)
    goal_bootstrap = goal.add_parser(
        "bootstrap", help="inspect, start, or recover one governed Goal bootstrap"
    ).add_subparsers(dest="goal_bootstrap_command", required=True)
    goal_bootstrap_status = goal_bootstrap.add_parser(
        "status", help="show read-only bootstrap status for one explicit Goal"
    )
    goal_bootstrap_status.add_argument("goal_id")
    goal_bootstrap_start = goal_bootstrap.add_parser(
        "start", help="perform exactly one fresh governed bootstrap invocation"
    )
    goal_bootstrap_start.add_argument("goal_id")
    goal_bootstrap_recover = goal_bootstrap.add_parser(
        "recover", help="perform exactly one explicit governed recovery invocation"
    )
    goal_bootstrap_recover.add_argument("goal_id")

    flow = sub.add_parser("flow", help="manage flows").add_subparsers(
        dest="flow_command", required=True
    )
    flow_create = flow.add_parser("create")
    flow_create.add_argument("goal_id")
    flow_create.add_argument("--controller")
    flow_list = flow.add_parser("list")
    flow_list.add_argument("--goal")
    flow_show = flow.add_parser("show")
    flow_show.add_argument("flow_id")
    flow_inspect = flow.add_parser("inspect", help="inspect one flow (read-only alias for show)")
    flow_inspect.add_argument("flow_id")
    flow_transition = flow.add_parser("transition")
    flow_transition.add_argument("flow_id")
    flow_transition.add_argument("status", type=_flow_status)
    flow_transition.add_argument("--revision", required=True, type=int)

    task = sub.add_parser("task", help="manage tasks").add_subparsers(
        dest="task_command", required=True
    )
    task_create = task.add_parser("create")
    task_create.add_argument("flow_id")
    task_create.add_argument("objective")
    task_create.add_argument("--parent")
    task_create.add_argument("--accept", action="append", default=[])
    task_create.add_argument("--constraint", action="append", default=[])
    task_create.add_argument("--capability", action="append", default=[])
    task_create.add_argument("--priority", type=int, default=0)
    task_list = task.add_parser("list")
    task_list.add_argument("--flow")
    task_show = task.add_parser("show")
    task_show.add_argument("task_id")
    task_inspect = task.add_parser("inspect", help="inspect one task (read-only alias for show)")
    task_inspect.add_argument("task_id")
    task_transition = task.add_parser("transition")
    task_transition.add_argument("task_id")
    task_transition.add_argument("status", type=_task_status)
    task_transition.add_argument("--revision", required=True, type=int)

    run = sub.add_parser("run", help="manage runs").add_subparsers(
        dest="run_command", required=True
    )
    run_start = run.add_parser("start")
    run_start.add_argument("task_id")
    run_start.add_argument("--role", default="EXECUTOR")
    run_start.add_argument("--model-profile")
    run_list = run.add_parser("list")
    run_list.add_argument("--task")
    run_finish = run.add_parser("finish")
    run_finish.add_argument("run_id")
    run_finish.add_argument("status", type=_run_status)
    run_finish.add_argument("--failure-reason")
    run_show = run.add_parser("show")
    run_show.add_argument("run_id")
    run_inspect = run.add_parser("inspect", help="inspect one run (read-only alias for show)")
    run_inspect.add_argument("run_id")

    verify = sub.add_parser("verify", help="record and inspect verification").add_subparsers(
        dest="verify_command", required=True
    )
    verify_record = verify.add_parser("record")
    verify_record.add_argument("target_type", choices=["GOAL", "FLOW", "TASK", "RUN"])
    verify_record.add_argument("target_id")
    verify_record.add_argument("status", choices=["PASS", "FAIL", "INCONCLUSIVE", "SKIPPED", "BLOCKED"])
    verify_record.add_argument("--type", dest="verification_type", required=True)
    verify_record.add_argument("--verifier", required=True)
    verify_record.add_argument("--run-id")
    verify_list = verify.add_parser("list")
    verify_list.add_argument("target_type", choices=["GOAL", "FLOW", "TASK", "RUN"])
    verify_list.add_argument("target_id")

    worker = sub.add_parser("worker", help="run bounded local model workers").add_subparsers(
        dest="worker_command", required=True
    )
    worker_propose = worker.add_parser(
        "propose", help="ask a local llama.cpp model for a non-applied patch proposal"
    )
    worker_propose.add_argument("task_id")
    worker_propose.add_argument("--file", action="append", required=True, dest="files")
    worker_propose.add_argument("--base-url", default="http://127.0.0.1:8080")
    worker_propose.add_argument("--model", default="local-model")
    worker_propose.add_argument("--api-key", default="no-key")
    worker_propose.add_argument("--timeout", type=float, default=300.0)
    worker_propose.add_argument("--max-tokens", type=int, default=4096)
    worker_propose.add_argument("--temperature", type=float, default=0.2)
    worker_propose.add_argument("--allow-remote", action="store_true")

    sandbox = sub.add_parser("sandbox", help="inspect and run configured sandbox verification").add_subparsers(
        dest="sandbox_command", required=True
    )
    sandbox.add_parser("status", help="show configured sandbox backend status")
    sandbox_verify = sandbox.add_parser(
        "verify", help="run required approved verification commands for an AUDITED workspace"
    )
    sandbox_verify.add_argument("workspace_id")

    return parser


def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)

    if args.command == "init":
        _print(runtime.initialize(args.name))
        return 0
    if args.command == "status":
        _print(runtime.status())
        return 0
    if args.command == "doctor":
        result = inspect_project(args.project_root)
        _print(result)
        return 0 if result["ready"] or not args.strict else 1
    if args.command == "recover":
        raw = runtime.recover() if args.apply else runtime.recovery_findings()
        _print({"applied": bool(args.apply), "findings": [item.__dict__ for item in raw]})
        return 0 if args.apply or not raw else 1
    if args.command == "manager":
        if args.manager_command == "status":
            _print(inspect_manager_advance_status_readonly(runtime).to_dict())
            return 0
        if args.manager_command == "advance":
            _print(advance_production_manager_bounded(runtime).to_dict())
            return 0
    if args.command == "advance":
        _print(advance_production_manager_bounded(runtime).to_dict())
        return 0
    if args.command == "context" and args.context_command == "preview":
        if args.seed_files and not args.auto_context:
            raise ValueError("--seed-file requires --auto-context")
        _print(
            build_context_preview(
                runtime,
                args.task_id,
                selected_paths=args.files,
                auto_context=args.auto_context,
                seed_paths=args.seed_files,
                structural_context=args.structural_context,
                semantic_context=args.semantic_context,
            )
        )
        return 0
    if args.command == "attempt":
        forwarded = ["--project-root", str(args.project_root), args.task_id]
        if args.auto_context:
            forwarded.append("--auto-context")
        else:
            for path in args.files or []:
                forwarded.extend(["--file", path])
        for path in args.seed_files:
            forwarded.extend(["--seed-file", path])
        for flag in ("--structural-context", "--semantic-context", "--allow-remote"):
            if getattr(args, flag.removeprefix("--").replace("-", "_")):
                forwarded.append(flag)
        forwarded.extend(
            [
                "--base-url", args.base_url,
                "--model", args.model,
                "--api-key", args.api_key,
                "--timeout", str(args.timeout),
                "--max-tokens", str(args.max_tokens),
                "--temperature", str(args.temperature),
            ]
        )
        return bounded_attempt_main(forwarded)
    if args.command == "review":
        if args.review_command == "inspect":
            _print(inspect_task_review(runtime, args.task_id))
            return 0
        decision_id = record_task_review_decision(
            runtime,
            args.task_id,
            args.review_command,
            rationale=args.rationale,
        )
        _print({"decision_id": decision_id, "action": args.review_command})
        return 0

    if args.command == "goal":
        if args.goal_command == "bootstrap":
            if args.goal_bootstrap_command == "status":
                _print(inspect_goal_bootstrap_status_readonly(runtime, args.goal_id).to_dict())
                return 0
            if args.goal_bootstrap_command == "start":
                _print(bootstrap_goal_once(runtime, args.goal_id).to_dict())
                return 0
            if args.goal_bootstrap_command == "recover":
                _print(recover_goal_once(runtime, args.goal_id).to_dict())
                return 0
        if args.goal_command == "create":
            goal_id = runtime.create_goal(
                args.objective,
                success_criteria=args.success,
                constraints=args.constraint,
                priority=args.priority,
            )
            _print(runtime.get_goal(goal_id))
            return 0
        if args.goal_command == "list":
            _print(runtime.list_goals())
            return 0
        if args.goal_command in {"show", "inspect"}:
            _print(runtime.get_goal(args.goal_id))
            return 0
        if args.goal_command == "transition":
            runtime.transition_goal(args.goal_id, args.status, expected_revision=args.revision)
            _print(runtime.get_goal(args.goal_id))
            return 0

    if args.command == "flow":
        if args.flow_command == "create":
            flow_id = runtime.create_flow(args.goal_id, controller=args.controller)
            _print(runtime.get_flow(flow_id))
            return 0
        if args.flow_command == "list":
            _print(runtime.list_flows(args.goal))
            return 0
        if args.flow_command in {"show", "inspect"}:
            _print(runtime.get_flow(args.flow_id))
            return 0
        if args.flow_command == "transition":
            runtime.transition_flow(args.flow_id, args.status, expected_revision=args.revision)
            _print(runtime.get_flow(args.flow_id))
            return 0

    if args.command == "task":
        if args.task_command == "create":
            task_id = runtime.create_task(
                args.flow_id,
                args.objective,
                parent_task_id=args.parent,
                acceptance_criteria=args.accept,
                constraints=args.constraint,
                required_capabilities=args.capability,
                priority=args.priority,
            )
            _print(runtime.get_task(task_id))
            return 0
        if args.task_command == "list":
            _print(runtime.list_tasks(args.flow))
            return 0
        if args.task_command in {"show", "inspect"}:
            _print(runtime.get_task(args.task_id))
            return 0
        if args.task_command == "transition":
            runtime.transition_task(args.task_id, args.status, expected_revision=args.revision)
            _print(runtime.get_task(args.task_id))
            return 0

    if args.command == "run":
        if args.run_command == "start":
            run_id = runtime.start_run(
                args.task_id,
                role=args.role,
                model_profile=args.model_profile,
            )
            _print(runtime.get_run(run_id))
            return 0
        if args.run_command == "list":
            _print(runtime.list_runs(args.task))
            return 0
        if args.run_command == "finish":
            runtime.finish_run(args.run_id, args.status, failure_reason=args.failure_reason)
            _print(runtime.get_run(args.run_id))
            return 0
        if args.run_command in {"show", "inspect"}:
            _print(runtime.get_run(args.run_id))
            return 0

    if args.command == "verify":
        if args.verify_command == "record":
            verification_id = runtime.record_verification(
                args.target_type,
                args.target_id,
                verification_type=args.verification_type,
                verifier=args.verifier,
                status=args.status,
                run_id=args.run_id,
            )
            _print({"verification_id": verification_id})
            return 0
        if args.verify_command == "list":
            _print(runtime.list_verifications(args.target_type, args.target_id))
            return 0

    if args.command == "sandbox":
        config = load_config(runtime.project_root)
        backend = create_sandbox_backend(runtime, config)
        if args.sandbox_command == "status":
            available = backend.available()
            _print(
                {
                    "backend": backend.backend_id,
                    "available": available,
                    "network_allowed": config.sandbox_network,
                    "image": config.sandbox_image,
                    "provenance": dict(backend.provenance),
                    "guarantees": {
                        "filesystem_isolated": backend.guarantees.filesystem_isolated,
                        "process_isolated": backend.guarantees.process_isolated,
                        "host_secrets_isolated": backend.guarantees.host_secrets_isolated,
                        "network_controlled": backend.guarantees.network_controlled,
                    },
                }
            )
            return 0 if available else 1
        if args.sandbox_command == "verify":
            result = SandboxedWorkspaceVerifier(runtime, backend).verify(args.workspace_id)
            _print(
                {
                    "workspace_id": result.workspace_id,
                    "passed": result.passed,
                    "results": [
                        {
                            "category": item.category,
                            "command_name": item.command_name,
                            "verification_id": item.verification_id,
                            "passed": item.passed,
                            "sandbox_result": asdict(item.sandbox_result)
                            if item.sandbox_result is not None
                            else None,
                        }
                        for item in result.results
                    ],
                }
            )
            return 0 if result.passed else 1

    if args.command == "worker" and args.worker_command == "propose":
        adapter = LlamaCppAdapter(
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
            timeout_seconds=args.timeout,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            allow_remote=args.allow_remote,
        )
        result = LocalPatchWorker(runtime, adapter).execute(
            args.task_id, selected_paths=args.files, model_profile=args.model
        )
        _print(
            {
                "run_id": result.run_id,
                "context_artifact_id": result.context_artifact_id,
                "response_artifact_id": result.response_artifact_id,
                "proposal_artifact_id": result.proposal_artifact_id,
                "proposal": result.proposal.to_dict(),
                "applied": False,
            }
        )
        return 0

    raise AssertionError("unhandled command")


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except KeyError as exc:
        _print({"error": "NOT_FOUND", "message": str(exc)}, stream=sys.stderr)
        return 3
    except GoalBootstrapOperatorBlocked as exc:
        _print(
            {
                "error": "GOAL_BOOTSTRAP_BLOCKED",
                "decision": exc.decision.value,
                "message": exc.detail,
            },
            stream=sys.stderr,
        )
        return 4
    except (InvalidTransition, StaleRevision) as exc:
        _print({"error": "INVALID_STATE", "message": str(exc)}, stream=sys.stderr)
        return 4
    except GoalBootstrapOperatorError as exc:
        _print({"error": "GOAL_BOOTSTRAP_ERROR", "message": str(exc)}, stream=sys.stderr)
        return 5
    except RuntimeInvariantError as exc:
        _print({"error": "INVARIANT_VIOLATION", "message": str(exc)}, stream=sys.stderr)
        return 5
    except VerificationRequired as exc:
        _print({"error": "VERIFICATION_REQUIRED", "message": str(exc)}, stream=sys.stderr)
        return 6
    except (PatchValidationError, RepositoryAccessError) as exc:
        _print({"error": "PROPOSAL_REJECTED", "message": str(exc)}, stream=sys.stderr)
        return 8
    except LlamaCppError as exc:
        _print({"error": "MODEL_ERROR", "message": str(exc)}, stream=sys.stderr)
        return 9
    except SandboxUnavailable as exc:
        _print({"error": "SANDBOX_UNAVAILABLE", "message": str(exc)}, stream=sys.stderr)
        return 10
    except SandboxPolicyError as exc:
        _print({"error": "SANDBOX_POLICY", "message": str(exc)}, stream=sys.stderr)
        return 11
    except ValueError as exc:
        _print({"error": "INVALID_INPUT", "message": str(exc)}, stream=sys.stderr)
        return 7
