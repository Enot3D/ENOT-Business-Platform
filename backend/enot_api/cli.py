import argparse
from getpass import getpass
from time import sleep

from sqlalchemy import select

from .db import session_factory, transaction_lock
from .importer import publish
from .models import User
from .security import PASSWORD_HASHER
from .worker import work_once


def main() -> None:
    parser = argparse.ArgumentParser(prog="enot_api")
    commands = parser.add_subparsers(dest="command", required=True)
    dataset = commands.add_parser("import")
    dataset.add_argument("--version", default="task-002-003-pilot-1")
    user = commands.add_parser("create-user")
    user.add_argument("login")
    worker = commands.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if args.command == "worker":
        if args.once:
            work_once()
        else:
            try:
                while True:
                    if not work_once():
                        sleep(1)
            except KeyboardInterrupt:
                return
        return

    with session_factory().begin() as db:
        if args.command == "import":
            row = publish(db, args.version)
            message = f"Dataset {row.version}: {row.id} ({row.manifest_sha256})"
        else:
            if not 1 <= len(args.login) <= 128 or not args.login.strip():
                parser.error("Login must contain 1–128 characters")
            password = getpass("Password: ")
            if not 12 <= len(password) <= 256 or password != getpass(
                "Repeat password: "
            ):
                parser.error("Use a matching password of 12–256 characters")
            transaction_lock(db, f"create-user:{args.login}")
            if db.scalar(select(User.id).where(User.login == args.login)):
                parser.error("Login already exists")
            db.add(User(login=args.login, password_hash=PASSWORD_HASHER.hash(password)))
            message = "Account created"
    print(message)


if __name__ == "__main__":
    main()
