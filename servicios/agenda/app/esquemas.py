"""Forma de lo que entra y sale de la API de la agenda (horarios, bloqueos y disponibilidad). FastAPI los usa para validar y para /docs."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

# "08:00", no "8:00" ni "08:00:30": con ceros a la izquierda, comparar el texto es comparar la hora.
Hora = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", examples=["08:00"])]

Motivo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]


class ProfesionalResumen(BaseModel):
    id: UUID
    nombre: str
    especialidad: str


class NuevoHorario(BaseModel):
    dia_semana: int = Field(ge=1, le=7, description="ISO: 1 lunes ... 7 domingo")
    hora_inicio: Hora
    hora_fin: Hora

    @model_validator(mode="after")
    def fin_despues_del_inicio(self):
        if self.hora_fin <= self.hora_inicio:
            raise ValueError("La hora de fin debe ser posterior a la de inicio")
        return self


class Horario(NuevoHorario):
    id: UUID
    profesional_id: UUID


class NuevoBloqueo(BaseModel):
    # AwareDatetime exige zona horaria ("...-06:00" o "...Z"): un instante sin zona es ambiguo.
    inicio: AwareDatetime
    fin: AwareDatetime
    motivo: Motivo

    @model_validator(mode="after")
    def fin_despues_del_inicio(self):
        if self.fin <= self.inicio:
            raise ValueError("El fin del bloqueo debe ser posterior a su inicio")
        return self


class CitaEnConflicto(BaseModel):
    """Una cita reservada que un bloqueo o un cambio de horario dejó sin cubrir. Recepción decide qué hacer."""

    id: UUID
    profesional_id: UUID
    paciente_id: UUID
    servicio_id: UUID
    inicio: datetime
    fin: datetime
    estado: str
    paciente: str
    servicio: str


class Bloqueo(BaseModel):
    id: UUID
    profesional_id: UUID
    inicio: datetime
    fin: datetime
    motivo: str
    conflictos: list[CitaEnConflicto]


class HorarioEliminado(BaseModel):
    conflictos: list[CitaEnConflicto]


# ---------- Disponibilidad (RF7, RF8) ----------


class EspaciosDelDia(BaseModel):
    profesional_id: UUID
    servicio_id: UUID
    fecha: date
    duracion_minutos: int
    espacios: list[datetime] = Field(description="Instantes en que puede empezar la cita, en orden")


class DisponibilidadDia(BaseModel):
    fecha: date
    espacios: list[datetime]


class DisponibilidadDeProfesional(BaseModel):
    profesional: ProfesionalResumen
    dias: list[DisponibilidadDia]


# ---------- Citas (RF9 a RF13) ----------


class Error(BaseModel):
    """Forma de toda respuesta de error de la API."""

    detalle: str
    restriccion: str | None = Field(default=None, description="La restricción del motor que rechazó la operación, si la hubo")


class _Espacio(BaseModel):
    """Un instante de inicio. `extra="forbid"`: enviar `fin` o `clinica_id` es un error 422, no un dato que se ignora en
    silencio. El fin lo fija el servicio (I4) y la clínica la sesión (I5)."""

    model_config = ConfigDict(extra="forbid")

    profesional_id: UUID
    inicio: AwareDatetime

    @model_validator(mode="after")
    def en_minutos_exactos(self):
        if self.inicio.second or self.inicio.microsecond:
            raise ValueError("El inicio debe ser en minutos exactos")
        return self


class SolicitudReserva(_Espacio):
    paciente_id: UUID
    servicio_id: UUID


class Reprogramacion(_Espacio):
    """El nuevo espacio. El paciente y el servicio no cambian: los pone la cita original."""


class Cancelacion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motivo: Motivo


class Desenlace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    desenlace: Literal["ATENDIDA", "AUSENTE"]


class Cita(BaseModel):
    id: UUID
    paciente_id: UUID
    profesional_id: UUID
    servicio_id: UUID
    inicio: datetime
    fin: datetime
    estado: str
    creada_por: UUID
    creada_en: datetime
    cancelada_por: UUID | None
    cancelada_en: datetime | None
    motivo_cancelacion: str | None
    cita_origen_id: UUID | None = Field(description="La cita que ésta reprograma")
    paciente: str
    servicio: str
