from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

from .anki_connect import AnkiConnectClient, sync_notes
from .builder import build_package, prepare_notes
from .config import AppPaths
from .models import DeckInput
from .utils import configure_logging, get_logger, load_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gera decks do Anki com audio em frances e sincronizacao opcional via AnkiConnect."
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Caminho para o JSON de entrada.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Diretorio raiz do projeto. Padrao: diretorio atual.",
    )
    parser.add_argument(
        "--skip-ankiconnect",
        action="store_true",
        help="Pula a tentativa de importacao/atualizacao via AnkiConnect.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    paths = AppPaths(project_root=args.project_root.resolve())
    paths.ensure()
    log_path = configure_logging(paths.logs_dir)
    logger = get_logger()

    logger.info("Carregando entrada JSON de %s", args.input)
    payload = load_json(args.input.resolve())
    deck_input = DeckInput.from_dict(payload)

    if not deck_input.notes:
        logger.error("Nenhuma nota foi encontrada no JSON informado.")
        return 1

    prepared_notes = prepare_notes(deck_input, paths.media_dir)
    package_path = build_package(deck_input, prepared_notes, paths.apkg_dir, paths.media_dir)
    logger.info("Pacote .apkg disponivel em %s", package_path)
    logger.info("Log salvo em %s", log_path)

    if args.skip_ankiconnect:
        logger.info("Tentativa via AnkiConnect pulada por parametro.")
        return 0

    client = AnkiConnectClient()
    try:
        available = client.is_available()
    except requests.RequestException:
        available = False

    if not available:
        logger.warning("AnkiConnect indisponivel. O .apkg foi gerado normalmente.")
        return 0

    stats = sync_notes(client, deck_input, prepared_notes, paths.media_dir)
    logger.info(
        "AnkiConnect concluido: %s criadas, %s atualizadas, %s ignoradas.",
        stats.created,
        stats.updated,
        stats.skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
