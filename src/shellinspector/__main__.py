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


def get_ssh_config(target_host):
    if target_host == "vagrant":
        return {
            "server": "127.0.0.1",
            "username": "root",
            "port": get_vagrant_sshport(),
        }
    else:
        return {
            "server": target_host,
            "username": "root",
            "port": 22,
        }


def run_spec_file(runner, path, sshconfig):
    print(f"running {path}")

    spec_file = Path(path).resolve()

    if not spec_file.exists():
        print(f"file {spec_file} does not exist")
        return False

    lines = spec_file.read_text().splitlines()
    errors, commands = parse(spec_file, lines)

    if errors:
        print("parsing failed")
        print("\n".join(errors))
        return False

    return runner.run(commands, sshconfig)


def run(target_host, spec_files):
    sshconfig = get_ssh_config(target_host)
    success = True
    runner = ShellRunner()

    for spec_file in spec_files:
        success &= run_spec_file(runner, spec_file, sshconfig)

    return 0 if success else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--target-host",
        default="vagrant",
    )
    parser.add_argument(
        "spec_files",
        nargs="+",
    )

    args = parser.parse_args()

    return args


def main():
    args = parse_args()
    return run(**vars(args))


if __name__ == "__main__":
    sys.exit(main())
