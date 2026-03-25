#!/usr/bin/env python3
"""Telegram Music Downloader CLI entrypoint."""

import argparse
import asyncio
import sys

from logger import emit_session_lines, emit_session_message, log_exception
from session_runner import SessionRunner, config_exists


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Telegram Music Downloader")
    parser.add_argument(
        "--config", "-c", default="src/config.yaml", help="Config file path"
    )
    parser.add_argument(
        "--max-files",
        "-m",
        type=int,
        default=0,
        help="Maximum files to download (0 = unlimited)",
    )
    parser.add_argument(
        "--stats", "-s", action="store_true", help="Show statistics only"
    )
    parser.add_argument(
        "--cleanup", action="store_true", help="Clean up tracker from missing files"
    )
    parser.add_argument(
        "--progress", "-p", action="store_true", help="Show current download progress"
    )
    parser.add_argument(
        "--workers", "-w", type=int, help="Override number of concurrent workers"
    )
    return parser


async def run_cli(args) -> None:
    if not config_exists(args.config):
        print(f"Config file not found: {args.config}")
        print("Create config.yaml with your Telegram credentials and channel list")
        sys.exit(1)

    runner = None
    try:
        runner = SessionRunner(args.config)

        if args.workers:
            runner.config._config["download"]["concurrent_downloads"] = args.workers
            emit_session_message(
                f"Using {args.workers} concurrent workers (overridden from command line)",
                logger=runner.logger,
            )

        if args.stats:
            await runner.show_statistics()
        elif args.cleanup:
            removed = await runner.cleanup_tracker()
            emit_session_message(
                f"Cleaned up {removed} missing file entries", logger=runner.logger
            )
        elif args.progress:
            await runner.show_progress()
        else:
            await runner.initialize_client()
            await runner.show_statistics()
            results = await runner.run_download_session(args.max_files)

            emit_session_lines(
                [
                    "",
                    "=== Session Results ===",
                    f"Channels processed: {results['channels_processed']}",
                    f"Messages processed: {results['total_messages_processed']}",
                    f"Files found: {results['total_files_found']}",
                    f"Files downloaded: {results['total_files_downloaded']}",
                    f"Files skipped: {results['total_files_skipped']}",
                    f"Files failed: {results['total_files_failed']}",
                ],
                logger=runner.logger,
            )

            if runner.download_coordinator:
                runner.download_monitor.display_summary()
    except KeyboardInterrupt:
        if runner and runner.logger:
            emit_session_message(
                "Interrupted by user. Exiting...", logger=runner.logger
            )
        else:
            print("\nInterrupted by user. Exiting...")
    except Exception as exc:
        if runner and runner.logger:
            log_exception(f"Error: {exc}", logger=runner.logger)
        else:
            print(f"\nError: {exc}")
            import traceback

            traceback.print_exc()
        sys.exit(1)
    finally:
        if runner:
            await runner.close()


async def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    await run_cli(args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...")
    except RuntimeError as exc:
        if "Event loop is closed" not in str(exc):
            raise
