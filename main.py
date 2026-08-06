"""Atalho para quem prefere `python main.py` ao comando `leitor-cb`.

A implementação está em src/leitor_cb/adapters/cli.py.
"""

from leitor_cb.adapters.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
