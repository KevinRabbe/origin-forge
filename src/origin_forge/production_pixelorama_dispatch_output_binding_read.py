from __future__ import annotations

from .ids import IdKind, validate_id
from .production_pixelorama_dispatch_output_binding_models import PixeloramaDispatchOutputBinding
from .production_pixelorama_dispatch_output_binding_store import (
    PixeloramaDispatchOutputBindingStoreError,
    _binding_from_row,
    _require_execution_relation,
)
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime


class PixeloramaDispatchOutputBindingReadError(RuntimeError):
    pass


def read_pixelorama_dispatch_output_binding(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> PixeloramaDispatchOutputBinding:
    """Read and revalidate one immutable execution→Pixelorama-output relation."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(execution_id, str) or not validate_id(
        execution_id, IdKind.DISPATCH_EXECUTION
    ):
        raise PixeloramaDispatchOutputBindingReadError(
            "execution_id must be a valid DISPEXEC ID"
        )
    try:
        with production_read_connection(runtime) as conn:
            project_row = conn.execute(
                "SELECT id FROM projects WHERE root_path = ?",
                (str(runtime.project_root),),
            ).fetchone()
            if project_row is None:
                raise PixeloramaDispatchOutputBindingReadError(
                    "project is not initialized for current repository root"
                )
            row = conn.execute(
                "SELECT * FROM pixelorama_dispatch_output_bindings WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise PixeloramaDispatchOutputBindingReadError(
                    "Pixelorama dispatch-output binding does not exist"
                )
            try:
                binding = _binding_from_row(row)
                _require_execution_relation(conn, project_row["id"], binding)
            except PixeloramaDispatchOutputBindingStoreError as exc:
                raise PixeloramaDispatchOutputBindingReadError(str(exc)) from exc
            return binding
    except PixeloramaDispatchOutputBindingReadError:
        raise
    except ProductionReadGuardError as exc:
        raise PixeloramaDispatchOutputBindingReadError(str(exc)) from exc
