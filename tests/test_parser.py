from shellinspector.parser import parse


def test_parse():
    commands = list(
        parse(
            "/dev/null",
            [
                "$ echo a",
                "# ignored",
                "a",
                "% ls",
                "file",
                "dir",
                "otherfile",
                "%~ ls dir",
                "file",
                "%_ ls dir",
                "file",
            ],
        )
    )

    assert len(commands) == 4
    assert commands[0].execution_mode == "run_command_user"
    assert commands[0].command == "echo a"
    assert commands[0].assert_mode == "literal"
    assert commands[0].expected == "a\n"
    assert commands[0].source_file == "/dev/null"
    assert commands[0].source_line_no == 1
    assert commands[1].execution_mode == "run_command_root"
    assert commands[1].command == "ls"
    assert commands[1].assert_mode == "literal"
    assert commands[1].expected == "file\ndir\notherfile\n"
    assert commands[1].source_file == "/dev/null"
    assert commands[1].source_line_no == 4
    assert commands[2].execution_mode == "run_command_root"
    assert commands[2].command == "ls dir"
    assert commands[2].assert_mode == "regex"
    assert commands[3].execution_mode == "run_command_root"
    assert commands[3].command == "ls dir"
    assert commands[3].assert_mode == "ignore"
