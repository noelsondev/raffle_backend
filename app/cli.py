import argparse
import getpass

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Admin


def create_admin() -> None:
    name = input("Nombre: ").strip()
    email = input("Email: ").strip().lower()

    if not name:
        print("Error: el nombre es obligatorio.")
        return

    if not email:
        print("Error: el email es obligatorio.")
        return

    password = getpass.getpass("Contraseña: ")
    password_confirmation = getpass.getpass("Confirmar contraseña: ")

    if not password:
        print("Error: la contraseña es obligatoria.")
        return

    if password != password_confirmation:
        print("Error: las contraseñas no coinciden.")
        return

    with SessionLocal() as db:
        existing_admin = db.scalar(
            select(Admin).where(Admin.email == email)
        )

        if existing_admin:
            print("Error: ya existe un administrador con ese email.")
            return

        admin = Admin(
            name=name,
            email=email,
            password_hash=hash_password(password),
            is_active=True,
        )

        db.add(admin)
        db.commit()
        db.refresh(admin)

        print()
        print("Administrador creado correctamente.")
        print(f"ID: {admin.id}")
        print(f"Nombre: {admin.name}")
        print(f"Email: {admin.email}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CLI de Rifa Backend"
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "create-admin",
        help="Crear un administrador",
    )

    args = parser.parse_args()

    if args.command == "create-admin":
        create_admin()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()