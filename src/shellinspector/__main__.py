import argparse
import logging
import re
import sys
from pathlib import Path

from shellinspector.parser import parse
from shellinspector.reporter import ConsoleReporter
from shellinspector.runner import ShellRunner

LOGGER = logging.getLogger(Path(__file__).name)


def get_vagrant_sshport():
    inventory_file = Path(
        ".vagrant/provisioners/ansible/inventory/vagrant_ansible_inventory"
    )

    if not inventory_file.exists():
        return None

    content = inventory_file.read_text()
    port = re.search("ansible_port=([0-9]+)", content)
    if not port:
        raise Exception(
            "vagrant_ansible_inventory is invalid, could not find ansible_port"
        )
    return int(port[1])


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


def parse_spec_file(path):
    LOGGER.debug("parsing %s", path)

    spec_file = Path(path).resolve()

    if not spec_file.exists():
        LOGGER.error("file %s does not exist", spec_file)
        return None

    with open(spec_file) as f:
        specfile = parse(spec_file, f)

    for i, command in enumerate(specfile.commands):
        LOGGER.debug("command[%s]: %s", i, command.short)

    if specfile.errors:
        for error in specfile.errors:
            LOGGER.error(
                "%s:%s: %s, %s",
                error.source_file.name,
                error.source_line_no,
                error.source_line,
                error.message,
            )

    return specfile


def run(target_host, spec_file_paths, identity, verbose):
    ssh_config = get_ssh_config(target_host)
    ssh_config["ssh_key"] = identity

    context = {
        "SI_TARGET": ssh_config["server"],
        "SI_TARGET_SSH_USERNAME": ssh_config["username"],
        "SI_TARGET_SSH_PORT": ssh_config["port"],
    }

    LOGGER.debug("SSH config: %s", ssh_config)

    runner = ShellRunner(ssh_config, context)
    runner.add_reporter(ConsoleReporter())
    success = True

    spec_files = []

    for spec_file_path in spec_file_paths:
        spec_file = parse_spec_file(spec_file_path)

        if spec_file is None or spec_file.errors:
            continue

        if spec_file.examples:
            for example in spec_file.examples:
                spec_files.append(spec_file.as_example(example))
        else:
            spec_files.append(spec_file)

    for spec_file in spec_files:
        if len(spec_files) > 1:
            if spec_file.applied_example:
                example_str = ",".join(
                    f"{k}={v}" for k, v in spec_file.applied_example.items()
                )
                print(f"{spec_file.path} (w/ {example_str})")
            else:
                print(f"{spec_file.path}")

        success = success & runner.run(spec_file)

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
        "spec_file_paths",
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
