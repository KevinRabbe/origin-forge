from __future__ import annotations

import argparse
import json
import sys
from enum import StrEnum
from pathlib import Path

from .adapters.llamacpp import LlamaCppAdapter, LlamaCppError
from .config import load_config
from .patches import PatchValidationError
from .repository import RepositoryAccessError
from .sandbox import SandboxPolicyError, SandboxUnavailable
from .sandbox_factory import create_sandbox_backend
from .sandbox_verification import SandboxedWorkspaceVerifier
from .runtime import OriginForgeRuntime, RuntimeInvariantError
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

    recover_parser = sub.add_parser(
        "recover", help="inspect or reconcile interrupted RUNNING records"
    )
    recover_parser.add_argument("--apply", action="store_true")

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
    goal_transition = goal.add_parser("transition")
    goal_transition.add_argument("goal_id")
    goal_transition.add_argument("status", type=_goal_status)
    goal_transition.add_argument("--revision", required=True, type=int)

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
    if args.command == "recover":
        raw = runtime.recover() if args.apply else runtime.recovery_findings()
        _print({"applied": bool(args.apply), "findings": [item.__dict__ for item in raw]})
        return 0 if args.apply or not raw else 1

    if args.command == "goal":
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
        if args.goal_command == "show":
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
        if args.flow_command == "show":
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
        if args.task_command == "show":
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
        if args.run_command == "show":
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
                            "sandbox_result": item.sandbox_result,
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
    except (InvalidTransition, StaleRevision) as exc:
        _print({"error": "INVALID_STATE", "message": str(exc)}, stream=sys.stderr)
        return 4
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
