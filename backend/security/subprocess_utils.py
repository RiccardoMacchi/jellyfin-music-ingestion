"""
Wrapper sicuro per l'esecuzione di processi esterni (ffmpeg, ffprobe).

Regole:
- MAI shell=True, MAI concatenazione di stringhe: solo liste di argomenti.
- Timeout obbligatorio su ogni chiamata.
- Nessun parametro proveniente dall'utente viene passato come flag; i valori
  utente (titoli, path) sono sempre passati come argomento posizionale/valore,
  mai interpretati come opzione.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from backend.config import settings


class SubprocessError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"Comando fallito ({returncode}): {' '.join(cmd)}\n{stderr[-2000:]}")


@dataclass
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


async def run_subprocess(cmd: list[str], timeout: int | None = None) -> ProcessResult:
    """Esegue `cmd` (lista di argomenti, mai stringa) con timeout e senza shell."""
    if not isinstance(cmd, list) or not cmd:
        raise ValueError("cmd deve essere una lista non vuota di argomenti")

    timeout = timeout or settings.subprocess_timeout_seconds

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise SubprocessError(cmd, -1, "timeout scaduto")

    result = ProcessResult(
        returncode=proc.returncode or 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )
    if result.returncode != 0:
        raise SubprocessError(cmd, result.returncode, result.stderr)
    return result
