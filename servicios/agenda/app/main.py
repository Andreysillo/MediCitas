"""Servicio de agenda y citas (persona A).

RF5 y RF6 (horarios y bloqueos), RF7 y RF8 (disponibilidad), RF9 a RF13 (reservar, reprogramar, cancelar,
desenlace y estados) y RF20 (agenda del día). Es el único servicio que escribe en cita.
"""

from medicitas_comun import crear_app

app = crear_app("agenda")

# Cada grupo de requisitos va en su propio router dentro de app/, y se registra aquí:
# app.include_router(disponibilidad.router)
