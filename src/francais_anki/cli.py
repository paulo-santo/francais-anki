from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

from .anki_connect import AnkiConnectClient, sync_notes
from .builder import build_package, prepare_notes
from .config import AppPaths
from .models import DeckInput, TtsOptions
from .utils import configure_logging, get_logger, load_json
from .voice_discovery import discover_voices

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
) -> int:
    logger = get_logger()
    logger.info("Carregando entrada JSON de %s", input_path)
    payload = load_json(input_path)
    deck_input = DeckInput.from_dict(payload, voice_catalog)

    if not deck_input.notes:
        logger.error("Nenhuma nota foi encontrada no JSON informado: %s", input_path)
        return 1

    prepare_result = prepare_notes(deck_input, paths.media_dir, tts_options)
    if not prepare_result.prepared_notes:
        logger.error(
            "Nenhuma nota com audio foi gerada para %s; pacote .apkg nao sera criado.",
            input_path,
        )
        return 1

    package_path = build_package(
        deck_input,
        prepare_result.prepared_notes,
        paths.apkg_dir,
        paths.media_dir,
    )
    logger.info("Pacote .apkg disponivel em %s", package_path)

    if skip_ankiconnect:
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

    stats = sync_notes(client, deck_input, prepare_result.prepared_notes, paths.media_dir)
    logger.info(
        "AnkiConnect concluido: %s criadas, %s atualizadas, %s ignoradas.",
        stats.created,
        stats.updated,
        stats.skipped,
    )
    return 0


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
    logger.info("Processando %s arquivo(s) JSON de %s", len(input_files), input_target.resolve())

    failed_inputs: list[Path] = []
    for input_file in input_files:
        logger.info("Iniciando processamento de %s", input_file)
        try:
            exit_code = process_input_file(
                input_file,
                paths=paths,
                skip_ankiconnect=args.skip_ankiconnect,
                tts_options=tts_options,
                voice_catalog=voice_catalog,
            )
        except Exception:
            logger.exception("Falha inesperada ao processar %s", input_file)
            exit_code = 1

        if exit_code != 0:
            failed_inputs.append(input_file)

    logger.info("Log salvo em %s", log_path)
    if failed_inputs:
        logger.error(
            "Processamento concluido com falhas em %s arquivo(s): %s",
            len(failed_inputs),
            ", ".join(str(path) for path in failed_inputs),
        )
        return 1

    logger.info("Processamento concluido com sucesso para %s arquivo(s).", len(input_files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
