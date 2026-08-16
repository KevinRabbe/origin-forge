from pathlib import Path

path = Path("src/origin_forge/production_dispatch_invocation_pixelorama.py")
text = path.read_text()
old = "from .lineage import OriginForgeLineage\nfrom .pixelorama_cli_export import PixeloramaCliExportRequest\n"
new = "from .lineage import OriginForgeLineage\nfrom .path_policy import portable_relative_path\nfrom .pixelorama_cli_export import PixeloramaCliExportRequest\n"
if old not in text:
    raise RuntimeError("Phase 48F path-policy import anchor missing")
text = text.replace(old, new, 1)
old = '''    raw = request.source_path_or_uri
    if "://" in raw or "\\x00" in raw:
        raise ProductionDispatchInvocationError(
            "Pixelorama source Artifact must be a local project file"
        )
    relative = Path(raw)
    if relative.is_absolute() or relative.suffix.lower() != ".pxo":
        raise ProductionDispatchInvocationError(
            "Pixelorama source Artifact must be a relative .pxo project file"
        )
'''
new = '''    raw = request.source_path_or_uri
    try:
        portable = portable_relative_path(raw)
    except ValueError as exc:
        raise ProductionDispatchInvocationError(
            "Pixelorama source Artifact must be one canonical portable project file"
        ) from exc
    relative = Path(portable.as_posix())
    if relative.suffix.lower() != ".pxo":
        raise ProductionDispatchInvocationError(
            "Pixelorama source Artifact must be a relative .pxo project file"
        )
'''
if old not in text:
    raise RuntimeError("Phase 48F path-policy materializer anchor missing")
text = text.replace(old, new, 1)
path.write_text(text)
