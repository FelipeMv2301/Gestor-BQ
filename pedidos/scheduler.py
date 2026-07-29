import logging
import os
import datetime
import psutil
from apscheduler.schedulers.background import BackgroundScheduler
from django.db import IntegrityError, transaction
from django.utils import timezone
from .models import LockTarea
from .services import sincronizar_sap_reciente, sincronizar_woo_reciente
from django.conf import settings

logger = logging.getLogger("pedidos.scheduler")
NOMBRE_LOCK = "sincronizar_pedidos"
UMBRAL_INACTIVIDAD = datetime.timedelta(minutes=settings.INTERVALO_SYNC_PEDIDOS * 3)  # respaldo: 3 corridas sin señal de vida = dueño anterior murió


def _tomar_lock():
    try:
        with transaction.atomic():
            LockTarea.objects.create(nombre=NOMBRE_LOCK, pid=os.getpid())
        return True
    except IntegrityError:
        pass  # ya existe, ver si el dueño sigue vivo

    with transaction.atomic():
        lock = LockTarea.objects.select_for_update().filter(nombre=NOMBRE_LOCK).first()
        if not lock:
            return False

        # Un solo host siempre (nunca varias máquinas) — si el PID guardado ya no existe en
        # este mismo sistema, el dueño murió de verdad, sin importar cuánto silencio lleve.
        # Evita quedar esperando el umbral de tiempo tras un reinicio limpio (no un crash).
        pid_muerto = not psutil.pid_exists(lock.pid)
        vencido_por_tiempo = timezone.now() - lock.tomado_en > UMBRAL_INACTIVIDAD

        if pid_muerto or vencido_por_tiempo:
            motivo = "el PID ya no existe" if pid_muerto else "inactivo hace rato (más de %s)" % UMBRAL_INACTIVIDAD
            logger.warning("Cron pedidos: lock de PID %s %s, lo tomo yo (PID %s).", lock.pid, motivo, os.getpid())
            lock.pid = os.getpid()
            lock.save(update_fields=["pid", "tomado_en"])
            return True
    return False


def _refrescar_lock():
    LockTarea.objects.filter(nombre=NOMBRE_LOCK, pid=os.getpid()).update(tomado_en=timezone.now())


def _job_sincronizar_sap():
    _refrescar_lock()  # da señal de vida en cada corrida, para que nadie nos declare "muertos"
    logger.info("Cron SAP: iniciando sincronización (ayer + hoy)...")
    try:
        resultado = sincronizar_sap_reciente()
        logger.info("Cron SAP: %s creados, %s omitidos.", resultado["creados"], resultado["omitidos"])
    except Exception:
        logger.exception("Cron SAP: falló la sincronización.")


def _job_sincronizar_woo():
    _refrescar_lock()
    logger.info("Cron WEB: iniciando sincronización (ayer + hoy)...")
    try:
        resultado = sincronizar_woo_reciente()
        logger.info("Cron WEB: %s creados, %s omitidos.", resultado["creados"], resultado["omitidos"])
    except Exception:
        logger.exception("Cron WEB: falló la sincronización.")


def iniciar_scheduler():
    if not _tomar_lock():
        logger.info("Cron pedidos: otro proceso ya tiene el lock, no arranco el scheduler acá.")
        return

    scheduler = BackgroundScheduler()
    ahora = datetime.datetime.now()
    if settings.CRON_SAP_ACTIVO:
        scheduler.add_job(_job_sincronizar_sap, "interval", minutes=settings.INTERVALO_SYNC_PEDIDOS,
                           id="sincronizar_sap", next_run_time=ahora)  # primera corrida ya, no esperar el intervalo
    if settings.CRON_WOO_ACTIVO:
        scheduler.add_job(_job_sincronizar_woo, "interval", minutes=settings.INTERVALO_SYNC_PEDIDOS,
                           id="sincronizar_woo", next_run_time=ahora)
    scheduler.start()
    logger.info("Cron pedidos: scheduler iniciado (cada %s minutos, SAP=%s, WEB=%s).",
                settings.INTERVALO_SYNC_PEDIDOS, settings.CRON_SAP_ACTIVO, settings.CRON_WOO_ACTIVO)