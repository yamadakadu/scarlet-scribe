#!/usr/bin/env python3
"""PreToolUse hook for Read/Grep: keeps secret files (.env, keys) out of the agents' context."""

import sys

from _common import block, is_secret_file, read_payload


def main() -> int:
    tool_input = read_payload().get("tool_input", {})
    targets = [tool_input.get(k) for k in ("file_path", "path", "glob")]
    hits = [t for t in targets if t and is_secret_file(t.rstrip("/"))]
    if hits:
        return block(
            [f"Leitura de arquivo de segredos bloqueada: {', '.join(hits)}."],
            "Use o .env.example para saber quais variáveis existem. Se precisar confirmar "
            "um valor, peça ao Carlos.",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
