import argparse
import logging
import os
import re
import sys
from pathlib import Path

from termcolor import colored

from shellinspector.__about__ import __version__
from shellinspector.logging import get_logger
from shellinspector.parser import FixtureScope
from shellinspector.parser import parse
from shellinspector.reporter import ConsoleReporter
from shellinspector.runner import ShellRunner

LOGGER = get_logger(Path(__file__).name)


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


def run(target_host, spec_file_paths, identity, tags, verbose, skip_retry):
    ssh_config = get_ssh_config(target_host)
    ssh_config["ssh_key"] = identity

    tags = tags.split(",") if tags else []

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

    passed_spec_file_paths = spec_file_paths

    if not skip_retry:
        try:
            with open(".si-retry") as f:
                spec_file_paths = [p.strip() for p in f.readlines()]

            os.unlink(".si-retry")
            print("Found .si-retry, only running spec files listed there.")
        except FileNotFoundError:
            pass

    si_user_values = {}
    handled_fixtures = set()

    # Parse files
    for spec_file_path in spec_file_paths:
        spec_file = parse_spec_file(spec_file_path)

        if spec_file is None or spec_file.errors:
            continue

        if tags and not any(t in spec_file.tags for t in tags):
            continue

        if spec_file.examples:
            for example in spec_file.examples:
                spec_files.append(spec_file.as_example(example))
        else:
            spec_files.append(spec_file)

    # run RUN scoped fixtures (pre)
    for spec_file in spec_files:
        if (
            not spec_file.fixture_specfile_pre
            or spec_file.fixture_scope != FixtureScope.RUN
            or spec_file.fixture_specfile_pre.path in handled_fixtures
        ):
            continue

        handled_fixtures.add(spec_file.fixture_specfile_pre.path)

        print()
        print(
            "run-scoped fixture: " + spec_file.fixture_specfile_pre.get_pretty_string()
        )
        sessions = set()
        file_success = runner.run(spec_file.fixture_specfile_pre, sessions)

        if not file_success:
            print(colored(f"Fixture {spec_file.fixture} failed", "red"))
            return 1

        for session in sessions:
            try:
                si_user_values[
                    spec_file.fixture_specfile_pre.path
                ] = session.get_environment()["SI_USER"]
                break
            except Exception:
                pass

            session.pop_state()

        print()

    failed_spec_files = []

    print(f"Testing {len(spec_files)} spec files, including examples:")

    # run actual tests
    for spec_file in spec_files:
        if len(spec_files) > 1:
            print()
            print(spec_file.get_pretty_string())

        if (
            spec_file.fixture_specfile_pre
            and spec_file.fixture_specfile_pre.path in si_user_values
        ):
            si_user = si_user_values[spec_file.fixture_specfile_pre.path]
            spec_file.environment["SI_USER"] = si_user

        file_success = runner.run(spec_file)
        if not file_success:
            failed_spec_files.append(spec_file)
        success = success & file_success

    # run RUN scoped fixtures (post)
    for spec_file in spec_files:
        if (
            not spec_file.fixture_specfile_post
            or spec_file.fixture_scope != FixtureScope.RUN
            or spec_file.fixture_specfile_post.path in handled_fixtures
        ):
            continue

        handled_fixtures.add(spec_file.fixture_specfile_post.path)

        print()
        print(
            "run-scoped fixture: " + spec_file.fixture_specfile_post.get_pretty_string()
        )
        file_success = runner.run(spec_file.fixture_specfile_post)

        if not file_success:
            print(colored(f"Fixture {spec_file.fixture} failed", "red"))
            success = False

    if len(spec_files) > 1:
        print()
        if success:
            print(colored("All spec files succeeded.", "green"))
        else:
            print(colored(f"Some ({len(failed_spec_files)}) spec files failed:", "red"))

            for spec_file in failed_spec_files:
                print(f"* {spec_file.get_pretty_string()}")

    if failed_spec_files and len(passed_spec_file_paths) > 1 and not skip_retry:
        with open(".si-retry", "w") as f:
            f.write("\n".join(str(s.path) for s in failed_spec_files) + "\n")

        print()
        print("Wrote .si-retry file, the next run will only run these spec files.")

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
        "--tags",
        required=False,
        help="only run spec files which list the given tags in their frontmatter",
    )
    parser.add_argument(
        "--skip-retry",
        action="store_true",
        default=False,
        help="do not write or respect .si-retry files, i.e. always run all files provided",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=__version__,
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
        logging.root.setLevel(logging.DEBUG)

    logging.debug("parsed args %s", args)

    return run(**vars(args))


if __name__ == "__main__":
    sys.exit(main())
