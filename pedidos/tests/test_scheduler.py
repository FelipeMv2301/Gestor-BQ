"""Lock de BD que evita que 2 procesos corran el cron in-process a la vez, y el supervisor que
reintenta tomarlo (pedidos/scheduler.py)."""
import datetime
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from pedidos.models import LockTarea
from pedidos import scheduler
from pedidos.scheduler import (
    _tomar_lock, _refrescar_lock, _supervisar, iniciar_scheduler,
    NOMBRE_LOCK, UMBRAL_INACTIVIDAD,
)


class _EstadoDeModuloLimpio(TestCase):
    """`_scheduler` y `_soy_dueno` son globales de módulo: sin resetearlos, un test contagia al
    siguiente."""

    def setUp(self):
        scheduler._scheduler = None
        scheduler._soy_dueno = False
        self.addCleanup(setattr, scheduler, "_scheduler", None)
        self.addCleanup(setattr, scheduler, "_soy_dueno", False)


class TomarLockTest(_EstadoDeModuloLimpio):
    def test_sin_lock_previo_lo_crea_y_toma(self):
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            self.assertTrue(_tomar_lock())
        self.assertEqual(LockTarea.objects.get(nombre=NOMBRE_LOCK).pid, 111)

    def test_lock_fresco_no_se_puede_tomar(self):
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            _tomar_lock()
        with patch("pedidos.scheduler.os.getpid", return_value=222):
            self.assertFalse(_tomar_lock())
        self.assertEqual(LockTarea.objects.get(nombre=NOMBRE_LOCK).pid, 111)

    def test_lock_inactivo_se_puede_robar_por_tiempo(self):
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            _tomar_lock()
        hace_mucho = timezone.now() - UMBRAL_INACTIVIDAD - datetime.timedelta(minutes=1)
        LockTarea.objects.filter(nombre=NOMBRE_LOCK).update(tomado_en=hace_mucho)

        with patch("pedidos.scheduler.os.getpid", return_value=222):
            self.assertTrue(_tomar_lock())
        self.assertEqual(LockTarea.objects.get(nombre=NOMBRE_LOCK).pid, 222)

    def test_lock_a_punto_de_vencer_pero_no_vencido_no_se_roba(self):
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            _tomar_lock()
        casi_vencido = timezone.now() - UMBRAL_INACTIVIDAD + datetime.timedelta(seconds=5)
        LockTarea.objects.filter(nombre=NOMBRE_LOCK).update(tomado_en=casi_vencido)

        with patch("pedidos.scheduler.os.getpid", return_value=222):
            self.assertFalse(_tomar_lock())

    def test_el_pid_ya_no_decide_nada(self):
        """El lock ya NO se roba por "el PID no existe". Dentro de Docker los PID se renumeran en
        cada contenedor, así que un PID de un dueño muerto casi siempre existe en el contenedor
        nuevo — mirarlo era justamente lo que dejaba el cron caído para siempre."""
        with patch("pedidos.scheduler.os.getpid", return_value=999999):
            _tomar_lock()  # PID que con toda seguridad no corre en esta máquina
        with patch("pedidos.scheduler.os.getpid", return_value=222):
            self.assertFalse(_tomar_lock())  # fresco: no se roba, exista o no ese PID


class RefrescarLockTest(_EstadoDeModuloLimpio):
    def test_refresca_y_confirma_que_seguimos_siendo_duenos(self):
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            _tomar_lock()
            viejo = timezone.now() - datetime.timedelta(minutes=5)
            LockTarea.objects.filter(nombre=NOMBRE_LOCK).update(tomado_en=viejo)
            self.assertTrue(_refrescar_lock())
        self.assertGreater(LockTarea.objects.get(nombre=NOMBRE_LOCK).tomado_en, viejo)

    def test_no_toca_el_lock_de_otro_y_avisa_que_ya_no_somos_duenos(self):
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            _tomar_lock()
        viejo = timezone.now() - datetime.timedelta(minutes=5)
        LockTarea.objects.filter(nombre=NOMBRE_LOCK).update(tomado_en=viejo)

        with patch("pedidos.scheduler.os.getpid", return_value=222):
            self.assertFalse(_refrescar_lock())
        self.assertEqual(LockTarea.objects.get(nombre=NOMBRE_LOCK).tomado_en, viejo)


class IniciarSchedulerTest(_EstadoDeModuloLimpio):
    """No debe arrancar un BackgroundScheduler real (dispararía sincronizaciones reales) — se mockea
    la clase."""

    def test_registra_el_supervisor_incluso_sin_tener_el_lock(self):
        """La clave del arreglo: arrancar el supervisor NO depende de conseguir el lock. Antes, un
        proceso que lo encontraba tomado no volvía a intentarlo nunca."""
        with patch("pedidos.scheduler.os.getpid", return_value=999):
            _tomar_lock()  # otro proceso ya es dueño

        with patch("pedidos.scheduler.BackgroundScheduler") as MockScheduler, \
             patch("pedidos.scheduler.os.getpid", return_value=111):
            iniciar_scheduler()

        instancia = MockScheduler.return_value
        ids = {llamada.kwargs["id"] for llamada in instancia.add_job.call_args_list}
        self.assertEqual(ids, {"supervisar_lock"})
        instancia.start.assert_called_once()

    def test_no_se_inicia_dos_veces_en_el_mismo_proceso(self):
        with patch("pedidos.scheduler.BackgroundScheduler") as MockScheduler:
            iniciar_scheduler()
            iniciar_scheduler()
        self.assertEqual(MockScheduler.call_count, 1)

    def test_el_supervisor_corre_de_inmediato_no_espera_el_intervalo(self):
        with patch("pedidos.scheduler.BackgroundScheduler") as MockScheduler:
            antes = datetime.datetime.now()
            iniciar_scheduler()
            despues = datetime.datetime.now()
        llamada = MockScheduler.return_value.add_job.call_args_list[0]
        self.assertTrue(antes <= llamada.kwargs["next_run_time"] <= despues)


class SupervisarTest(_EstadoDeModuloLimpio):
    def _arrancar_con_scheduler_falso(self):
        with patch("pedidos.scheduler.BackgroundScheduler") as MockScheduler:
            iniciar_scheduler()
        return MockScheduler.return_value

    def _ids_de_sincronizacion(self, scheduler_falso):
        return {llamada.kwargs["id"] for llamada in scheduler_falso.add_job.call_args_list
                if llamada.kwargs["id"] != "supervisar_lock"}

    def test_sin_lock_previo_lo_toma_y_registra_los_dos_jobs(self):
        scheduler_falso = self._arrancar_con_scheduler_falso()
        with patch("django.conf.settings.CRON_SAP_ACTIVO", True), \
             patch("django.conf.settings.CRON_WOO_ACTIVO", True):
            _supervisar()
        self.assertTrue(scheduler._soy_dueno)
        self.assertEqual(self._ids_de_sincronizacion(scheduler_falso),
                         {"sincronizar_sap", "sincronizar_woo"})

    def test_solo_sap_activo_registra_un_job(self):
        scheduler_falso = self._arrancar_con_scheduler_falso()
        with patch("django.conf.settings.CRON_SAP_ACTIVO", True), \
             patch("django.conf.settings.CRON_WOO_ACTIVO", False):
            _supervisar()
        self.assertEqual(self._ids_de_sincronizacion(scheduler_falso), {"sincronizar_sap"})

    def test_solo_woo_activo_registra_un_job(self):
        scheduler_falso = self._arrancar_con_scheduler_falso()
        with patch("django.conf.settings.CRON_SAP_ACTIVO", False), \
             patch("django.conf.settings.CRON_WOO_ACTIVO", True):
            _supervisar()
        self.assertEqual(self._ids_de_sincronizacion(scheduler_falso), {"sincronizar_woo"})

    def test_con_el_lock_de_otro_fresco_no_registra_nada(self):
        with patch("pedidos.scheduler.os.getpid", return_value=999):
            _tomar_lock()
        scheduler_falso = self._arrancar_con_scheduler_falso()
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            _supervisar()
        self.assertFalse(scheduler._soy_dueno)
        self.assertEqual(self._ids_de_sincronizacion(scheduler_falso), set())

    def test_reintenta_y_toma_el_relevo_cuando_el_lock_queda_huerfano(self):
        """El incidente del 10 al 13 de agosto de 2026, en un test: el dueño muere dejando el lock,
        y el proceso que arrancó sin conseguirlo tiene que quedárselo en un ciclo posterior."""
        with patch("pedidos.scheduler.os.getpid", return_value=999):
            _tomar_lock()  # dueño que después "muere" sin soltar el lock
        scheduler_falso = self._arrancar_con_scheduler_falso()

        with patch("pedidos.scheduler.os.getpid", return_value=111), \
             patch("django.conf.settings.CRON_SAP_ACTIVO", True), \
             patch("django.conf.settings.CRON_WOO_ACTIVO", True):
            _supervisar()                                    # primer ciclo: el lock está fresco
            self.assertFalse(scheduler._soy_dueno)

            LockTarea.objects.filter(nombre=NOMBRE_LOCK).update(
                tomado_en=timezone.now() - UMBRAL_INACTIVIDAD - datetime.timedelta(minutes=1))

            _supervisar()                                    # ciclo posterior: ya venció, lo toma
            self.assertTrue(scheduler._soy_dueno)

        self.assertEqual(self._ids_de_sincronizacion(scheduler_falso),
                         {"sincronizar_sap", "sincronizar_woo"})
        self.assertEqual(LockTarea.objects.get(nombre=NOMBRE_LOCK).pid, 111)

    def test_el_dueno_late_en_cada_ciclo(self):
        scheduler_falso = self._arrancar_con_scheduler_falso()
        with patch("django.conf.settings.CRON_SAP_ACTIVO", True), \
             patch("django.conf.settings.CRON_WOO_ACTIVO", False):
            _supervisar()
            viejo = timezone.now() - datetime.timedelta(minutes=5)
            LockTarea.objects.filter(nombre=NOMBRE_LOCK).update(tomado_en=viejo)
            _supervisar()
        self.assertGreater(LockTarea.objects.get(nombre=NOMBRE_LOCK).tomado_en, viejo)
        #No re-registra los jobs en cada latido: solo al tomar el lock.
        self.assertEqual(len([l for l in scheduler_falso.add_job.call_args_list
                              if l.kwargs["id"] == "sincronizar_sap"]), 1)

    def test_si_le_roban_el_lock_deja_de_sincronizar(self):
        scheduler_falso = self._arrancar_con_scheduler_falso()
        with patch("pedidos.scheduler.os.getpid", return_value=111), \
             patch("django.conf.settings.CRON_SAP_ACTIVO", True), \
             patch("django.conf.settings.CRON_WOO_ACTIVO", True):
            _supervisar()
            self.assertTrue(scheduler._soy_dueno)

            LockTarea.objects.filter(nombre=NOMBRE_LOCK).update(pid=222)  # otro tomó el relevo

            _supervisar()

        self.assertFalse(scheduler._soy_dueno)
        self.assertEqual(scheduler_falso.remove_job.call_count, len(scheduler.ID_JOBS_SINCRONIZACION))

    def test_un_error_de_bd_no_mata_al_supervisor(self):
        self._arrancar_con_scheduler_falso()
        with patch("pedidos.scheduler._tomar_lock", side_effect=Exception("BD caída")):
            _supervisar()  # no debe propagar
        self.assertFalse(scheduler._soy_dueno)
