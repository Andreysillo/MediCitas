"""Forma de lo que entra y sale de la API de plataforma. FastAPI los usa para validar y para /docs."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=80)]


class NuevaClinica(BaseModel):
    """RF1. `extra="forbid"`: mandar `id` o `clinica_id` es un 422, no un dato que se ignora en silencio."""

    model_config = ConfigDict(extra="forbid")

    nombre: Nombre
    # Misma regla que el CHECK de clinica.identificador: minúsculas, números y guiones.
    identificador: str = Field(min_length=3, max_length=40, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", examples=["clinica-central"])
    zona_horaria: str = Field(min_length=3, max_length=64, description="Zona IANA", examples=["America/Costa_Rica"])
    admin_nombre: Nombre
    admin_usuario: str = Field(min_length=3, max_length=40, pattern=r"^[a-z0-9]+([._-][a-z0-9]+)*$", examples=["central-admin"])
    # Contraseña TEMPORAL: Keycloak obliga a cambiarla en el primer inicio de sesión. SecretStr evita que salga en logs.
    admin_contrasena: SecretStr = Field(min_length=8, max_length=128)


class Clinica(BaseModel):
    id: UUID
    nombre: str
    identificador: str
    zona_horaria: str
    creada_en: datetime


class Administrador(BaseModel):
    id: UUID
    nombre: str
    rol: str
    activo: bool


class AltaClinica(BaseModel):
    clinica: Clinica
    admin: Administrador


class ClinicaResumen(Clinica):
    usuarios: int
