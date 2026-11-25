"""Explicit project selection; private runtime state lives outside source control."""
import hashlib
import os
from pathlib import Path


def paths():
    value = os.environ.get("AI_HUB_PROJECT", "")
    if not value:
        raise RuntimeError("Defina AI_HUB_PROJECT com o caminho absoluto do projeto antes de iniciar.")
    project = Path(value).expanduser()
    if not project.is_absolute() or not project.is_dir():
        raise RuntimeError("AI_HUB_PROJECT precisa ser um diretório absoluto existente.")
    project = project.resolve()
    key = hashlib.sha256(str(project).encode()).hexdigest()[:16]
    data = Path(os.environ.get("AI_HUB_HOME", str(Path.home() / ".multi-ai-hub" / key))).expanduser()
    if not data.is_absolute():
        raise RuntimeError("AI_HUB_HOME precisa ser um caminho absoluto.")
    data = data.resolve()
    source = Path(__file__).resolve().parent
    if data == project or project in data.parents or data == source or source in data.parents:
        raise RuntimeError("AI_HUB_HOME deve ficar fora do projeto e da instalação do hub.")
    return project, data


PROJECT, DATA = paths()
