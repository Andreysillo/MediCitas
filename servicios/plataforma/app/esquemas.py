"""Forma de lo que entra y sale de la API de plataforma. FastAPI los usa para validar y para /docs.

MAPA DEL ARCHIVO (cada sección dice a qué requisito pertenece):
  - RF1  Alta de clínicas ........ NuevaClinica, Clinica, Administrador, AltaClinica, ClinicaResumen
  - RF2  Usuarios de la clínica .. RolDeClinica, NuevoUsuario, CambioRol, CambioActivo, UsuarioVista, CambioDeActivo
  - RF3  Catálogo de servicios ... NombreCatalogo, Duracion, NuevaEspecialidad, Especialidad, NuevoServicio,
                                   CambioServicio, Servicio
  - RF4  Profesionales ........... DatosProfesional, NuevoProfesional, Profesional, UsuarioLibre
  - RF14 Pacientes ............... DatosPaciente, PacienteLista, ListaPacientes, Paciente
`Nombre` (justo debajo) lo comparten RF1 y RF2. Todos los modelos de ENTRADA usan `extra="forbid"`: mandar un campo que
no existe (por ejemplo `clinica_id`) es un 422 y no se ignora en silencio, porque la clínica sale de la sesión (I5).
"""

import re
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator

Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=80)]


# ---------- Alta de clínicas (RF1) ----------


class NuevaClinica(BaseModel):
    """RF1. `extra="forbid"`: mandar `id` o `clinica_id` es un 422, no un dato que se ignora en silencio.
    Reúne los datos de la clínica (nombre, identificador, zona horaria) y los del primer administrador (`admin_*`)."""

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


# ---------- Usuarios de la clínica (RF2) ----------

# El administrador de plataforma no se asigna desde una clínica: no pertenece a ninguna.
RolDeClinica = Literal["ADM_CLINICA", "RECEPCION", "PROFESIONAL"]


class NuevoUsuario(BaseModel):
    """`extra="forbid"`: la clínica sale de la sesión, así que mandar `clinica_id` es un 422."""

    model_config = ConfigDict(extra="forbid")

    nombre: Nombre
    rol: RolDeClinica
    usuario: str = Field(min_length=3, max_length=40, pattern=r"^[a-z0-9]+([._-][a-z0-9]+)*$", description="Nombre de usuario en el proveedor de identidad")
    contrasena: SecretStr = Field(min_length=8, max_length=128, description="Temporal: se cambia en el primer inicio de sesión")


class CambioRol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rol: RolDeClinica


class CambioActivo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activo: bool


class UsuarioVista(BaseModel):
    id: UUID
    nombre: str
    rol: str
    activo: bool
    es_profesional: bool
    yo: bool


# ---------- Catálogo de servicios (RF3) ----------

NombreCatalogo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=60)]
# Mismos límites que el frontend: una consulta de menos de 5 minutos o de más de 8 horas es casi seguro un error de captura.
Duracion = Annotated[int, Field(ge=5, le=480, description="Minutos que la cita ocupa en la agenda (I4)")]


class NuevaEspecialidad(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: NombreCatalogo


class Especialidad(BaseModel):
    id: UUID
    nombre: str


class NuevoServicio(BaseModel):
    """`extra="forbid"`: la clínica sale de la sesión (I5), así que mandar `clinica_id` es un 422."""

    model_config = ConfigDict(extra="forbid")

    nombre: NombreCatalogo
    duracion_minutos: Duracion
    especialidad_id: UUID


class CambioServicio(BaseModel):
    """La especialidad no se cambia: los profesionales ya asociados al servicio la comparten (RF4)."""

    model_config = ConfigDict(extra="forbid")

    nombre: NombreCatalogo
    duracion_minutos: Duracion
    activo: bool


class Servicio(BaseModel):
    id: UUID
    nombre: str
    duracion_minutos: int
    especialidad_id: UUID
    especialidad: str
    activo: bool


# ---------- Profesionales (RF4) ----------


class DatosProfesional(BaseModel):
    """Lo que se puede editar de un profesional. `extra="forbid"`: la clínica sale de la sesión (I5)."""

    model_config = ConfigDict(extra="forbid")

    especialidad_id: UUID
    numero_colegiado: str = Field(min_length=3, max_length=20)
    servicios_ids: list[UUID] = Field(max_length=200, description="Exactamente los servicios que atiende; los demás quedan deshabilitados")


class NuevoProfesional(DatosProfesional):
    usuario_id: UUID = Field(description="Un usuario activo de la clínica con rol PROFESIONAL que aún no esté registrado")


class Profesional(BaseModel):
    id: UUID
    nombre: str
    especialidad_id: UUID
    especialidad: str
    numero_colegiado: str
    activo: bool
    servicios_ids: list[UUID]


class UsuarioLibre(BaseModel):
    id: UUID
    nombre: str


# ---------- Pacientes (RF14) ----------


class DatosPaciente(BaseModel):
    """RF14. `extra="forbid"`: la clínica sale de la sesión (I5), así que mandar `clinica_id` o `id` es un 422.
    Teléfono y correo son opcionales; una cadena vacía se guarda como NULL."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    identificacion: str = Field(min_length=3, max_length=30, description="Cédula u otro documento. Única dentro de la clínica")
    nombre: Nombre
    fecha_nacimiento: date
    telefono: str | None = Field(default=None, max_length=30)
    correo: str | None = Field(default=None, max_length=120)

    @field_validator("fecha_nacimiento")
    @classmethod
    def _fecha_razonable(cls, f: date) -> date:
        if f > date.today() or f < date(1900, 1, 1):
            raise ValueError("La fecha de nacimiento está fuera de rango")
        return f

    @field_validator("telefono")
    @classmethod
    def _telefono(cls, v: str | None) -> str | None:
        if not v:
            return None
        if not re.fullmatch(r"[+\d][\d\s-]{6,}", v):
            raise ValueError("El teléfono no es válido")
        return v

    @field_validator("correo")
    @classmethod
    def _correo(cls, v: str | None) -> str | None:
        if not v:
            return None
        v = v.lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", v):
            raise ValueError("El correo no es válido")
        return v


class PacienteLista(BaseModel):
    """Lo que sale al listar: sin teléfono ni correo, que solo salen al abrir la ficha (y eso se audita)."""

    id: UUID
    nombre: str
    identificacion: str
    fecha_nacimiento: date


class ListaPacientes(BaseModel):
    total: int = Field(description="Coincidencias en la clínica, aunque `pacientes` traiga solo las primeras")
    pacientes: list[PacienteLista]


class Paciente(PacienteLista):
    telefono: str | None
    correo: str | None


class CambioDeActivo(BaseModel):
    usuario: UsuarioVista
    citas_pendientes: int = Field(description="Citas reservadas a futuro del profesional dado de baja; recepción las reprograma")
