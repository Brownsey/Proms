import subprocess
import sys


def main() -> None:
    commands = [
        ["ruff", "check", "."],
        ["ruff", "format", "--check", "."],
        ["ty", "check"],
        ["pytest"],
    ]
    for command in commands:
        subprocess.run([sys.executable, "-m", *command], check=True)


if __name__ == "__main__":
    main()
