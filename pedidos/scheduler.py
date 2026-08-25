import logging
import os
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from django.db import IntegrityError, transaction
from django.utils import timezone
from .models import LockTarea
from .services import sincronizar_sap_reciente, sincronizar_woo_reciente
from django.conf import settings
from envios.services import refrescar_estados_recientes

logger = logging.getLogger("pedidos.scheduler")
NOMBRE_LOCK = "sincronizar_pedidos"

#Cada proceso (cada worker de gunicorn) corre un SUPERVISOR cada minuto: si es dueño del lock da
#señal de vida, y si no lo es, reintenta tomarlo.
#
#Ese reintento es lo que faltaba. Antes `iniciar_scheduler()` se ejecutaba UNA sola vez en
#`apps.ready()`: un proceso que al arrancar encontraba el lock tomado no volvía a intentarlo nunca.
#Si el dueño anterior había muerto dejando el lock atrás, el cron quedaba caído de forma
#PERMANENTE. Pasó en producción entre el 10 y el 13 de agosto de 2026: tres días sin ingesta, y se
#detectó de casualidad.
#
#Como el latido ahora es cada minuto (y no cada corrida de sincronización, que es cada 10), el
#relevo puede exigir mucho menos silencio: 3 minutos en vez de 30.
INTERVALO_SUPERVISION = 1
UMBRAL_INACTIVIDAD = datetime.timedelta(minutes=INTERVALO_SUPERVISION * 3)

ID_JOBS_SINCRONIZACION = ("sincronizar_sap", "sincronizar_woo", "refrescar_estados")

_scheduler = None
_soy_dueno = False


def _job_refrescar_estados():
    logger.info("Cron estados: refrescando estado de couriers con consulta por API...")
    try:
        total = refrescar_estados_recientes()
        logger.info("Cron estados: %s envío(s) actualizado(s).", total)
    except Exception:
        logger.exception("Cron estados: falló el refresco.")

def _tomar_lock():
    """Intenta quedarse con el lock. El único criterio es el reloj: si el dueño no dio señales de
    vida en UMBRAL_INACTIVIDAD, se lo da por muerto y se le roba.

    Acá antes había un atajo: `psutil.pid_exists(lock.pid)`, para no esperar el umbral tras un
    reinicio limpio. Era correcto con gunicorn nativo, pero NO dentro de Docker — los PID se
    renumeran desde abajo en cada contenedor nuevo, así que el PID de un dueño muerto casi siempre
    "existe" en el contenedor siguiente, apuntando a un proceso sin ninguna relación. El lock
    parecía vivo para siempre y nadie arrancaba el scheduler. Ese atajo se eliminó."""
    try:
        with transaction.atomic():
            LockTarea.objects.create(nombre=NOMBRE_LOCK, pid=os.getpid())
        return True
    except IntegrityError:
        pass  # ya existe, ver si el dueño sigue dando señales

    with transaction.atomic():
        lock = LockTarea.objects.select_for_update().filter(nombre=NOMBRE_LOCK).first()
        if lock is None:
            return False  # lo borraron entremedio; el próximo ciclo lo crea de nuevo

        if timezone.now() - lock.tomado_en <= UMBRAL_INACTIVIDAD:
            return False

        logger.warning(
            "Cron pedidos: el dueño (PID %s) no da señales hace más de %s, tomo el relevo (PID %s).",
            lock.pid, UMBRAL_INACTIVIDAD, os.getpid(),
        )
        lock.pid = os.getpid()
        lock.save(update_fields=["pid", "tomado_en"])
        return True


def _refrescar_lock():
    """Señal de vida del dueño. Devuelve False si la fila ya no es nuestra — o sea, si alguien tomó
    el relevo mientras estábamos callados.

    Filtra por el PID propio, que identifica bien al dueño DENTRO de un mismo contenedor (que es
    donde importa para no pisarnos entre workers). Queda una ventana teórica de dos dueños si el
    anterior revive después de que le robaron el lock y su PID coincide con el del nuevo; el daño
    sería una sincronización duplicada, que la ingesta ya absorbe con `pedido_ya_existe`."""
    filas_actualizadas = LockTarea.objects.filter(
        nombre=NOMBRE_LOCK, pid=os.getpid()
    ).update(tomado_en=timezone.now())
    return filas_actualizadas > 0


def _agregar_jobs_de_sincronizacion():
    ahora = datetime.datetime.now()
    if settings.CRON_SAP_ACTIVO:
        _scheduler.add_job(_job_sincronizar_sap, "interval", minutes=settings.INTERVALO_SYNC_PEDIDOS,
                           id="sincronizar_sap", next_run_time=ahora,  # primera corrida ya, no esperar el intervalo
                           replace_existing=True)
    if settings.CRON_WOO_ACTIVO:
        _scheduler.add_job(_job_sincronizar_woo, "interval", minutes=settings.INTERVALO_SYNC_PEDIDOS,
                           id="sincronizar_woo", next_run_time=ahora, replace_existing=True)
    if settings.CRON_REFRESCAR_ESTADOS_ACTIVO:
        _scheduler.add_job(_job_refrescar_estados, "interval", minutes=settings.INTERVALO_REFRESCAR_ESTADOS,
                           id="refrescar_estados", next_run_time=ahora, replace_existing=True)
    logger.info("Cron pedidos: tomé el lock, sincronizo yo (cada %s minutos, SAP=%s, WEB=%s, estados=%s).",
                settings.INTERVALO_SYNC_PEDIDOS, settings.CRON_SAP_ACTIVO, settings.CRON_WOO_ACTIVO,
                settings.CRON_REFRESCAR_ESTADOS_ACTIVO)


def _quitar_jobs_de_sincronizacion():
    for id_job in ID_JOBS_SINCRONIZACION:
        try:
            _scheduler.remove_job(id_job)
        except Exception:
            pass  # no estaba registrado (ej. su CRON_*_ACTIVO está en False)


def _supervisar():
    """Corre en TODOS los procesos, cada minuto. El dueño late; los demás reintentan el relevo."""
    global _soy_dueno
    try:
        if _soy_dueno:
            if not _refrescar_lock():
                logger.warning("Cron pedidos: perdí el lock, otro proceso tomó el relevo. Dejo de sincronizar.")
                _soy_dueno = False
                _quitar_jobs_de_sincronizacion()
            return

        if _tomar_lock():
            _soy_dueno = True
            _agregar_jobs_de_sincronizacion()
    except Exception:
        #Un problema puntual (ej. la BD momentáneamente inalcanzable) no puede matar al supervisor:
        #se loguea y se reintenta al minuto siguiente. Sin esto volveríamos al agujero original.
        logger.exception("Cron pedidos: falló la supervisión del lock, reintento en el próximo ciclo.")


def _job_sincronizar_sap():
    logger.info("Cron SAP: iniciando sincronización (ayer + hoy)...")
    try:
        resultado = sincronizar_sap_reciente()
        logger.info("Cron SAP: %s creados, %s omitidos, %s con error.",
                    resultado["creados"], resultado["omitidos"], resultado.get("fallidos", 0))
    except Exception:
        logger.exception("Cron SAP: falló la sincronización.")


def _job_sincronizar_woo():
    logger.info("Cron WEB: iniciando sincronización (ayer + hoy)...")
    try:
        resultado = sincronizar_woo_reciente()
        logger.info("Cron WEB: %s creados, %s omitidos.", resultado["creados"], resultado["omitidos"])
    except Exception:
        logger.exception("Cron WEB: falló la sincronización.")


def iniciar_scheduler():
    """Arranca el scheduler de ESTE proceso. Siempre registra el supervisor, tenga o no el lock: los
    jobs de sincronización los agrega el propio supervisor cuando le toca ser dueño."""
    global _scheduler
    if _scheduler is not None:
        return  # ya iniciado en este proceso

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(_supervisar, "interval", minutes=INTERVALO_SUPERVISION,
                       id="supervisar_lock", next_run_time=datetime.datetime.now())
    _scheduler.start()
    logger.info("Cron pedidos: supervisor iniciado (revisa el lock cada %s min, relevo tras %s sin señales).",
                INTERVALO_SUPERVISION, UMBRAL_INACTIVIDAD)
