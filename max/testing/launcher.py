import argparse
import logging
import sys
import os


def main():
    """
    Main launcher script for the video chat application.
    Provides a unified interface for running the application, tests, and diagnostics.
    """
    parser = argparse.ArgumentParser(description="Video Chat System Launcher")
    parser.add_argument("--config", default="config.ini", help="Path to config file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # App command
    app_parser = subparsers.add_parser(
        "app", help="Run the main video chat application"
    )

    # Test command
    test_parser = subparsers.add_parser("test", help="Run network connectivity tests")

    # Diagnostics command
    diag_parser = subparsers.add_parser("diagnose", help="Run network diagnostics")

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # Check if config file exists
    if not os.path.exists(args.config):
        logging.error(f"Config file not found: {args.config}")
        sys.exit(1)

    # Execute the requested command
    if args.command == "app" or args.command is None:
        logging.info("Starting video chat application")
        from main import main as run_app

        run_app()

    elif args.command == "test":
        logging.info("Running network connectivity test")
        from max.testing.network_test import test_connection

        success = test_connection(args.config, args.debug)
        sys.exit(0 if success else 1)

    elif args.command == "diagnose":
        logging.info("Running network diagnostics")
        from max.testing.diagnostics import run_network_diagnostics, print_diagnostic_results

        results = run_network_diagnostics(args.config)
        print_diagnostic_results(results)

        # Exit with code based on connectivity
        if results["remote_ping"]["success"] and results["remote_port_check"]:
            sys.exit(0)  # Success
        else:
            sys.exit(1)  # Network issues detected


if __name__ == "__main__":
    main()
