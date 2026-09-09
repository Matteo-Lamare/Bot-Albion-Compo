"""Point d'entree FastAPI : middleware de session, routes API, frontend statique."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from .catalogue import CHEMIN_CATALOGUE, importer as importer_catalogue
from .config import settings
from .database import Base, SessionLocal, engine
from .models import Membre, ObjetAlbion, RoleMembre, StatutCompo, TypeContenu
from .auth import hacher_mot_de_passe
from .routers import admin, auth, catalogue, compos
from .validation import ErreurLigne

FRONTEND_DIR = settings.base_dir / "frontend"


# Colonnes ajoutees apres coup : SQLite les accepte a chaud, ce qui evite de
# repartir d'une base vide a chaque evolution du modele.
COLONNES_AJOUTEES = {
    "compos": {"discord_messages": "TEXT"},
}


def migrer_schema() -> None:
    """Ajoute les colonnes manquantes des bases creees par une version anterieure."""
    with engine.begin() as connexion:
        for table, colonnes in COLONNES_AJOUTEES.items():
            existantes = {
                ligne[1]
                for ligne in connexion.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            }
            if not existantes:
                continue  # table pas encore creee : create_all s'en charge
            for nom, type_sql in colonnes.items():
                if nom not in existantes:
                    connexion.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {nom} {type_sql}")
                    print(f"[init] Colonne ajoutee : {table}.{nom}")


def initialiser_base() -> None:
    """Cree les tables et le compte admin initial si la base est vide."""
    migrer_schema()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.scalar(select(Membre).limit(1)) is None:
            db.add(
                Membre(
                    pseudo=settings.admin_pseudo,
                    mot_de_passe_hash=hacher_mot_de_passe(settings.admin_password),
                    role=RoleMembre.admin,
                )
            )
            db.commit()
            print(f"[init] Compte admin cree : {settings.admin_pseudo}")

        # Le catalogue Albion est charge au premier demarrage ; ensuite, seul
        # `python manage.py importer-catalogue` le rafraichit.
        if db.scalar(select(ObjetAlbion).limit(1)) is None and CHEMIN_CATALOGUE.exists():
            compte = importer_catalogue(db)
            print(f"[init] Catalogue Albion charge : {compte['objets']} objets, "
                  f"{compte['sorts']} sorts")


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialiser_base()
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="compos_session",
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=settings.cookie_secure,
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(catalogue.router)
app.include_router(compos.router)


@app.exception_handler(RequestValidationError)
async def erreurs_de_validation(_: Request, exception: RequestValidationError) -> JSONResponse:
    """Transforme les erreurs Pydantic en messages lisibles pour le frontend."""
    details = []
    for erreur in exception.errors():
        chemin = [str(element) for element in erreur["loc"] if element not in ("body",)]
        details.append({"champ": ".".join(chemin), "message": erreur["msg"]})
    return JSONResponse(status_code=422, content={"detail": "Validation echouee", "erreurs": details})


@app.exception_handler(ErreurLigne)
async def erreurs_de_ligne(_: Request, exception: ErreurLigne) -> JSONResponse:
    """Meme format que les erreurs Pydantic, pour un frontend qui n'a qu'un cas a traiter."""
    return JSONResponse(
        status_code=422,
        content={"detail": "Validation echouee", "erreurs": exception.erreurs},
    )


@app.get("/api/meta", tags=["meta"])
def meta() -> dict:
    """Enumerations et regles de slots, consommees par le frontend."""
    return {
        "types_contenu": [t.value for t in TypeContenu],
        "statuts": [s.value for s in StatutCompo],
        "roles": [r.value for r in RoleMembre],
    }


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def page_connexion() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/bibliotheque", include_in_schema=False)
def page_bibliotheque() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "bibliotheque.html")


@app.get("/compo", include_in_schema=False)
def page_compo() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "compo.html")


@app.get("/admin", include_in_schema=False)
def page_admin() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "admin.html")
