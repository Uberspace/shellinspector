import argparse
import re
import sys
from pathlib import Path

from shellinspector.parser import parse
from shellinspector.runner import ShellRunner


def get_vagrant_sshport():
    inventory_file = (
        Path(__file__).parent
        / "../.vagrant/provisioners/ansible/inventory/vagrant_ansible_inventory"
    )

    if not inventory_file.exists():
        return None

    content = inventory_file.read_text()
    return int(re.search("ansible_port=([0-9]+)", content)[1])


def run_spec_file(runner, path, sshconfig):
    print(f"running {path}")

    spec_file = Path(path).resolve()

    if not spec_file.exists():
        print(f"file {spec_file} does not exist")
        return False

    lines = spec_file.read_text().splitlines()
    commands = parse(spec_file, lines)

    if commands is False:
        print("parsing failed")
        return False

    return runner.run(commands, sshconfig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--target-host",
        default="vagrant",
    )
    parser.add_argument(
        "test_files",
        nargs="+",
    )

    args = parser.parse_args()

    if args.target_host == "vagrant":
        sshconfig = {
            "server": "127.0.0.1",
            "username": "root",
            "port": get_vagrant_sshport(),
        }
    else:
        sshconfig = {
            "server": args.target_host,
            "username": "root",
            "port": 22,
        }

    success = True
    runner = ShellRunner()

    for spec_file in args.test_files:
        success &= run_spec_file(runner, spec_file, sshconfig)

    sys.exit(0 if success else 1)
