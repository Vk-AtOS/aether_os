"""Phase p04a_backend_codegen — generate backend code from architecture."""
from aether_os.phases.p04a_backend_codegen.supervisor_agent import BackendCodegenSupervisor

# Alias so callers that import BackendCodegenPhase also work
BackendCodegenPhase = BackendCodegenSupervisor

__all__ = ["BackendCodegenSupervisor", "BackendCodegenPhase"]
