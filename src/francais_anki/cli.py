from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .anki_connect import AnkiConnectClient, sync_notes
from .builder import build_package, prepare_notes
from .config import AppPaths
from .models import DeckInput, TtsOptions
from .utils import configure_logging, get_logger, load_json
from .voice_discovery import discover_voices


@dataclass
class FileStats:
    path: Path
    total_notes: int = 0
    prepared_notes: int = 0
    failed_notes: int = 0
    anki_created: int = 0
    anki_updated: int = 0
    anki_skipped: int = 0

DEFAULT_TTS_OPTIONS = TtsOptions()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gera decks do Anki com audio em frances e sincronizacao opcional via AnkiConnect."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--input",
        type=Path,
        help="Caminho para o JSON de entrada.",
    )
    input_group.add_argument(
        "--input-dir",
        type=Path,
        help="Diretorio com arquivos JSON para processamento em lote (busca recursiva).",
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
    parser.add_argument(
        "--tts-connect-timeout",
        type=int,
        default=DEFAULT_TTS_OPTIONS.connect_timeout,
        help="Timeout de conexao do edge-tts em segundos.",
    )
    parser.add_argument(
        "--tts-receive-timeout",
        type=int,
        default=DEFAULT_TTS_OPTIONS.receive_timeout,
        help="Timeout de leitura do edge-tts em segundos.",
    )
    parser.add_argument(
        "--tts-retries",
        type=int,
        default=DEFAULT_TTS_OPTIONS.retries,
        help="Quantidade de retries por voz antes de trocar para fallback.",
    )
    parser.add_argument(
        "--tts-final-retry-pass",
        dest="tts_final_retry_pass",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_TTS_OPTIONS.final_retry_pass,
        help="Ativa uma segunda passada para reprocessar apenas notas com falha de audio.",
    )
    return parser


def discover_input_files(input_path: Path) -> list[Path]:
    resolved_input = input_path.resolve()
    if resolved_input.is_file():
        return [resolved_input]
    if not resolved_input.is_dir():
        raise FileNotFoundError(f"Caminho de entrada nao encontrado: {resolved_input}")

    json_files = sorted(path for path in resolved_input.rglob("*.json") if path.is_file())
    if not json_files:
        raise FileNotFoundError(f"Nenhum arquivo JSON encontrado em: {resolved_input}")
    return json_files


def process_input_file(
    input_path: Path,
    *,
    paths: AppPaths,
    skip_ankiconnect: bool,
    tts_options: TtsOptions,
    voice_catalog,
) -> tuple[int, FileStats]:
    logger = get_logger()
    file_stats = FileStats(path=input_path)

    logger.info("Carregando entrada JSON de %s", input_path)
    payload = load_json(input_path)
    deck_input = DeckInput.from_dict(payload, voice_catalog)

    if not deck_input.notes:
        logger.error("Nenhuma nota foi encontrada no JSON informado: %s", input_path)
        return 1, file_stats

    file_stats.total_notes = len(deck_input.notes)
    prepare_result = prepare_notes(deck_input, paths.media_dir, tts_options)
    file_stats.prepared_notes = len(prepare_result.prepared_notes)
    file_stats.failed_notes = len(prepare_result.failed_notes)

    if not prepare_result.prepared_notes:
        logger.error(
            "Nenhuma nota com audio foi gerada para %s; pacote .apkg nao sera criado.",
            input_path,
        )
        return 1, file_stats

    package_path = build_package(
        deck_input,
        prepare_result.prepared_notes,
        paths.apkg_dir,
        paths.media_dir,
    )
    logger.info("Pacote .apkg disponivel em %s", package_path)

    if skip_ankiconnect:
        logger.info("Tentativa via AnkiConnect pulada por parametro.")
        return 0, file_stats

    client = AnkiConnectClient()
    try:
        available = client.is_available()
    except requests.RequestException:
        available = False

    if not available:
        logger.warning("AnkiConnect indisponivel. O .apkg foi gerado normalmente.")
        return 0, file_stats

    anki_stats = sync_notes(client, deck_input, prepare_result.prepared_notes, paths.media_dir)
    file_stats.anki_created = anki_stats.created
    file_stats.anki_updated = anki_stats.updated
    file_stats.anki_skipped = anki_stats.skipped
    logger.info(
        "AnkiConnect concluido: %s criadas, %s atualizadas, %s ignoradas.",
        anki_stats.created,
        anki_stats.updated,
        anki_stats.skipped,
    )
    return 0, file_stats


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    paths = AppPaths(project_root=args.project_root.resolve())
    paths.ensure()
    log_path = configure_logging(paths.logs_dir)
    logger = get_logger()

    logger.info("Descobrindo vozes disponiveis via edge-tts...")
    voice_catalog = discover_voices()
    logger.info("Voices descobertas: FR-FR=%d, FR-Extended=%d, FR-CA=%d",
                len(voice_catalog.fr_fr_voices),
                len(voice_catalog.fr_extended_voices),
                len(voice_catalog.fr_ca_voices))

    tts_options = TtsOptions(
        connect_timeout=max(1, args.tts_connect_timeout),
        receive_timeout=max(1, args.tts_receive_timeout),
        retries=max(0, args.tts_retries),
        final_retry_pass=bool(args.tts_final_retry_pass),
    )
    logger.info(
        "Configuracao TTS: connect_timeout=%ss, receive_timeout=%ss, retries=%s, final_retry_pass=%s",
        tts_options.connect_timeout,
        tts_options.receive_timeout,
        tts_options.retries,
        tts_options.final_retry_pass,
    )

    input_target = args.input_dir or args.input
    input_files = discover_input_files(input_target)
    total_files = len(input_files)
    logger.info("Processando %s arquivo(s) JSON de %s", total_files, input_target.resolve())

    failed_inputs: list[Path] = []
    all_stats: list[FileStats] = []
    for file_index, input_file in enumerate(input_files, start=1):
        logger.info(
            "--- [arquivo %d/%d] %s ---",
            file_index,
            total_files,
            input_file.name,
        )
        try:
            exit_code, file_stats = process_input_file(
                input_file,
                paths=paths,
                skip_ankiconnect=args.skip_ankiconnect,
                tts_options=tts_options,
                voice_catalog=voice_catalog,
            )
        except Exception:
            logger.exception("Falha inesperada ao processar %s", input_file)
            exit_code, file_stats = 1, FileStats(path=input_file)

        all_stats.append(file_stats)
        if exit_code != 0:
            failed_inputs.append(input_file)

    # Resumo final
    total_notes = sum(s.total_notes for s in all_stats)
    total_prepared = sum(s.prepared_notes for s in all_stats)
    total_failed = sum(s.failed_notes for s in all_stats)
    total_anki_created = sum(s.anki_created for s in all_stats)
    total_anki_updated = sum(s.anki_updated for s in all_stats)
    total_anki_skipped = sum(s.anki_skipped for s in all_stats)

    logger.info("=" * 60)
    logger.info("RESUMO FINAL")
    logger.info("  Arquivos processados : %d/%d", total_files - len(failed_inputs), total_files)
    logger.info("  Frases com audio     : %d/%d", total_prepared, total_notes)
    logger.info("  Frases com falha     : %d", total_failed)
    if not args.skip_ankiconnect:
        logger.info(
            "  AnkiConnect          : %d criadas, %d atualizadas, %d ignoradas",
            total_anki_created,
            total_anki_updated,
            total_anki_skipped,
        )
    if failed_inputs:
        logger.error(
            "  Arquivos com falha   : %s",
            ", ".join(p.name for p in failed_inputs),
        )
    logger.info("  Log salvo em         : %s", log_path)
    logger.info("=" * 60)

    if failed_inputs:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
