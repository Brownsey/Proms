import subprocess


def main() -> None:
    commands = [
        ["uv", "run", "--locked", "ruff", "check", "."],
        ["uv", "run", "--locked", "ruff", "format", "--check", "."],
        ["uv", "run", "--locked", "ty", "check"],
        ["uv", "run", "--locked", "pytest"],
    ]
    for command in commands:
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
