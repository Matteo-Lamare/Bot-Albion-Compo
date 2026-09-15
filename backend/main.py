"""Point d'entree FastAPI : middleware de session, routes API, frontend statique."""
from __future__ import annotations

from contextlib import asynccontextmanager
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select
from starlette.middleware.sessions import SessionMiddleware

from .catalogue import CHEMIN_CATALOGUE, importer as importer_catalogue
from .config import settings
from .database import Base, SessionLocal, engine
from .models import Membre, ObjetAlbion, RoleMembre, StatutCompo, TypeContenu
from .auth import hacher_mot_de_passe
from .routers import admin, auth, catalogue, compos
from .validation import ErreurLigne

FRONTEND_DIR = settings.base_dir / "frontend"
COLONNES_AJOUTEES = {
    "compos": {"discord_messages": "TEXT"},
    "membres": {"dernier_acces": "TIMESTAMP WITH TIME ZONE"},
}
TABLES_SUPPRIMEES = ("inscriptions", "settings")


def _migrer_contraintes_type_contenu(connexion) -> None:
    """Met a jour une ancienne CHECK SQLAlchemy qui ne connait pas les nouveaux types."""
    if connexion.dialect.name != "postgresql":
        return
    inspecteur = inspect(connexion)
    if "compos" not in inspecteur.get_table_names():
        return

    valeurs = ", ".join(
        "'" + valeur.value.replace("'", "''") + "'" for valeur in TypeContenu
    )
    expression_attendue = f'"type_contenu" IN ({valeurs})'
    for contrainte in inspecteur.get_check_constraints("compos"):
        sqltext = (contrainte.get("sqltext") or "").lower()
        if "type_contenu" not in sqltext:
            continue
        nom = contrainte.get("name")
        if not nom or not re.fullmatch(r"[A-Za-z0-9_]+", nom):
            continue
        connexion.exec_driver_sql(f'ALTER TABLE "compos" DROP CONSTRAINT "{nom}"')
        connexion.exec_driver_sql(
            f'ALTER TABLE "compos" ADD CONSTRAINT "ck_compos_type_contenu_values" CHECK ({expression_attendue})'
        )
        print(f"[init] Contrainte type_contenu mise a jour : {nom}")
        break


def migrer_schema() -> None:
    """Met a niveau les bases creees par une version anterieure."""
    with engine.begin() as connexion:
        inspecteur = inspect(connexion)
        tables_existantes = set(inspecteur.get_table_names())
        for table in TABLES_SUPPRIMEES:
            if table in tables_existantes:
                connexion.exec_driver_sql(f'DROP TABLE "{table}"')
                print(f"[init] Table supprimee : {table}")
                tables_existantes.remove(table)
        for table, colonnes in COLONNES_AJOUTEES.items():
            if table not in tables_existantes:
                continue
            existantes = {colonne["name"] for colonne in inspecteur.get_columns(table)}
            for nom, type_sql in colonnes.items():
                if nom not in existantes:
                    connexion.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{nom}" {type_sql}')
                    print(f"[init] Colonne ajoutee : {table}.{nom}")
        _migrer_contraintes_type_contenu(connexion)


def initialiser_base() -> None:
    migrer_schema()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.scalar(select(Membre).limit(1)) is None:
            db.add(Membre(pseudo=settings.admin_pseudo, mot_de_passe_hash=hacher_mot_de_passe(settings.admin_password), role=RoleMembre.admin))
            db.commit()
            print(f"[init] Compte admin cree : {settings.admin_pseudo}")
        if db.scalar(select(ObjetAlbion).limit(1)) is None and CHEMIN_CATALOGUE.exists():
            compte = importer_catalogue(db)
            print(f"[init] Catalogue Albion charge : {compte['objets']} objets, {compte['sorts']} sorts")


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialiser_base()
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="compos_session", max_age=settings.session_max_age, same_site="lax", https_only=settings.cookie_secure)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(catalogue.router)
app.include_router(compos.router)

@app.exception_handler(RequestValidationError)
async def erreurs_de_validation(_: Request, exception: RequestValidationError) -> JSONResponse:
    details = []
    for erreur in exception.errors():
        chemin = [str(element) for element in erreur["loc"] if element not in ("body",)]
        details.append({"champ": ".".join(chemin), "message": erreur["msg"]})
    return JSONResponse(status_code=422, content={"detail": "Validation echouee", "erreurs": details})

@app.exception_handler(ErreurLigne)
async def erreurs_de_ligne(_: Request, exception: ErreurLigne) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "Validation echouee", "erreurs": exception.erreurs})

@app.get("/api/meta", tags=["meta"])
def meta() -> dict:
    return {"types_contenu": [t.value for t in TypeContenu], "statuts": [s.value for s in StatutCompo], "roles": [r.value for r in RoleMembre]}

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/", include_in_schema=False)
def page_connexion() -> FileResponse: return FileResponse(FRONTEND_DIR / "index.html")
@app.get("/bibliotheque", include_in_schema=False)
def page_bibliotheque() -> FileResponse: return FileResponse(FRONTEND_DIR / "bibliotheque.html")
@app.get("/compo", include_in_schema=False)
def page_compo() -> FileResponse: return FileResponse(FRONTEND_DIR / "compo.html")
@app.get("/admin", include_in_schema=False)
def page_admin() -> FileResponse: return FileResponse(FRONTEND_DIR / "admin.html")
@app.get("/mot-de-passe", include_in_schema=False)
def page_mot_de_passe() -> FileResponse: return FileResponse(FRONTEND_DIR / "mot-de-passe.html")
