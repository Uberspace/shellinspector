import argparse
import logging
import re
import sys
from pathlib import Path

from shellinspector.parser import parse
from shellinspector.reporter import print_runner_event
from shellinspector.runner import RunnerEvent
from shellinspector.runner import ShellRunner

LOGGER = logging.getLogger(Path(__file__).name)


def get_vagrant_sshport():
    inventory_file = Path(
        ".vagrant/provisioners/ansible/inventory/vagrant_ansible_inventory"
    )

    if not inventory_file.exists():
        return None

    content = inventory_file.read_text()
    return int(re.search("ansible_port=([0-9]+)", content)[1])


def get_ssh_config(target_host):
    if target_host == "vagrant":
        return {
            "server": "127.0.0.1",
            "username": "root",
            "port": get_vagrant_sshport(),
        }
    else:
        host, _, port = target_host.partition(":")
        return {
            "server": host,
            "username": "root",
            "port": port or 22,
        }


def run_spec_file(runner, path, sshconfig):
    LOGGER.info("handling %s", path)

    spec_file = Path(path).resolve()

    if not spec_file.exists():
        LOGGER.error("file %s does not exist", spec_file)
        return False

    lines = spec_file.read_text().splitlines()
    errors, commands = parse(spec_file, lines)

    if errors:
        for error in errors:
            LOGGER.error(
                "%s:%s: %s, %s",
                error.source_file.name,
                error.source_line_no,
                error.source_line,
                error.message,
            )

        return False

    for i, command in enumerate(commands):
        LOGGER.debug("command[%s]: %s", i, command.short())

    context = {
        "SI_TARGET": sshconfig["server"],
        "SI_TARGET_SSH_USERNAME": sshconfig["username"],
        "SI_TARGET_SSH_PORT": sshconfig["port"],
    }

    return runner.run(commands, sshconfig, context)


def run(target_host, spec_files, identity, verbose):
    sshconfig = get_ssh_config(target_host)

    LOGGER.debug("SSH config: %s", sshconfig)

    runner = ShellRunner(identity)
    success = True

    for spec_file in spec_files:
        event = None
        run = run_spec_file(runner, spec_file, sshconfig)

        if run is False:
            break

        for event in run:
            print_runner_event(event[0], event[1], **event[2])

        success = success & (event == RunnerEvent.RUN_SUCCEEDED)

    return 0 if success else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--target-host",
        default="vagrant",
        help="remote host, format: hostname[:port], e.g. '127.0.0.1:22' or '127.0.0.1'",
    )
    parser.add_argument(
        "--identity",
        "-i",
        required=False,
        help="path to a SSH private key to be used for authentication",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "spec_files",
        nargs="+",
    )

    args = parser.parse_args()

    return args


def main():
    args = parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    logging.debug("parsed args %s", args)

    return run(**vars(args))


if __name__ == "__main__":
    sys.exit(main())
