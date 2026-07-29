"""Lock de BD que evita que 2 procesos corran el cron in-process a la vez (pedidos/scheduler.py)."""
import datetime
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from pedidos.models import LockTarea
from pedidos.scheduler import _tomar_lock, _refrescar_lock, iniciar_scheduler, NOMBRE_LOCK, UMBRAL_INACTIVIDAD


class TomarLockTest(TestCase):
    def test_sin_lock_previo_lo_crea_y_toma(self):
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            self.assertTrue(_tomar_lock())
        lock = LockTarea.objects.get(nombre=NOMBRE_LOCK)
        self.assertEqual(lock.pid, 111)

    def test_lock_fresco_de_pid_vivo_no_se_puede_tomar(self):
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            _tomar_lock()  # dueño original
        with patch("pedidos.scheduler.os.getpid", return_value=222), \
             patch("pedidos.scheduler.psutil.pid_exists", return_value=True):
            self.assertFalse(_tomar_lock())
        self.assertEqual(LockTarea.objects.get(nombre=NOMBRE_LOCK).pid, 111)  # sigue siendo del original

    def test_lock_inactivo_se_puede_robar_por_tiempo_aunque_el_pid_siga_vivo(self):
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            _tomar_lock()
        hace_mucho = timezone.now() - UMBRAL_INACTIVIDAD - datetime.timedelta(minutes=1)
        LockTarea.objects.filter(nombre=NOMBRE_LOCK).update(tomado_en=hace_mucho)

        with patch("pedidos.scheduler.os.getpid", return_value=222), \
             patch("pedidos.scheduler.psutil.pid_exists", return_value=True):
            self.assertTrue(_tomar_lock())
        self.assertEqual(LockTarea.objects.get(nombre=NOMBRE_LOCK).pid, 222)

    def test_lock_a_punto_de_vencer_pero_no_vencido_no_se_roba_si_pid_vivo(self):
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            _tomar_lock()
        casi_vencido = timezone.now() - UMBRAL_INACTIVIDAD + datetime.timedelta(seconds=5)
        LockTarea.objects.filter(nombre=NOMBRE_LOCK).update(tomado_en=casi_vencido)

        with patch("pedidos.scheduler.os.getpid", return_value=222), \
             patch("pedidos.scheduler.psutil.pid_exists", return_value=True):
            self.assertFalse(_tomar_lock())

    def test_lock_fresco_pero_pid_muerto_se_roba_de_inmediato(self):
        # El caso real de hoy: reinicio limpio, el PID viejo ya no existe, no hace falta esperar
        # los 30 min del umbral de silencio.
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            _tomar_lock()  # tomado_en = ahora mismo, muy fresco

        with patch("pedidos.scheduler.os.getpid", return_value=222), \
             patch("pedidos.scheduler.psutil.pid_exists", return_value=False):
            self.assertTrue(_tomar_lock())
        self.assertEqual(LockTarea.objects.get(nombre=NOMBRE_LOCK).pid, 222)


class IniciarSchedulerTest(TestCase):
    """No debe arrancar un BackgroundScheduler real (dispararía sincronizaciones reales) — se mockea la clase."""

    def test_ambos_activos_registra_los_2_jobs(self):
        with patch("pedidos.scheduler.BackgroundScheduler") as MockScheduler, \
             patch("django.conf.settings.CRON_SAP_ACTIVO", True), \
             patch("django.conf.settings.CRON_WOO_ACTIVO", True):
            iniciar_scheduler()
        instancia = MockScheduler.return_value
        ids_registrados = {llamada.kwargs["id"] for llamada in instancia.add_job.call_args_list}
        self.assertEqual(ids_registrados, {"sincronizar_sap", "sincronizar_woo"})
        instancia.start.assert_called_once()

    def test_primera_corrida_es_inmediata_no_espera_el_intervalo(self):
        with patch("pedidos.scheduler.BackgroundScheduler") as MockScheduler, \
             patch("django.conf.settings.CRON_SAP_ACTIVO", True), \
             patch("django.conf.settings.CRON_WOO_ACTIVO", True):
            antes = datetime.datetime.now()
            iniciar_scheduler()
            despues = datetime.datetime.now()
        instancia = MockScheduler.return_value
        for llamada in instancia.add_job.call_args_list:
            next_run_time = llamada.kwargs.get("next_run_time")
            self.assertIsNotNone(next_run_time, "cada job debe traer next_run_time — si no, espera el intervalo completo")
            self.assertTrue(antes <= next_run_time <= despues)

    def test_solo_sap_activo_registra_1_job(self):
        with patch("pedidos.scheduler.BackgroundScheduler") as MockScheduler, \
             patch("django.conf.settings.CRON_SAP_ACTIVO", True), \
             patch("django.conf.settings.CRON_WOO_ACTIVO", False):
            iniciar_scheduler()
        instancia = MockScheduler.return_value
        ids_registrados = {llamada.kwargs["id"] for llamada in instancia.add_job.call_args_list}
        self.assertEqual(ids_registrados, {"sincronizar_sap"})

    def test_solo_woo_activo_registra_1_job(self):
        with patch("pedidos.scheduler.BackgroundScheduler") as MockScheduler, \
             patch("django.conf.settings.CRON_SAP_ACTIVO", False), \
             patch("django.conf.settings.CRON_WOO_ACTIVO", True):
            iniciar_scheduler()
        instancia = MockScheduler.return_value
        ids_registrados = {llamada.kwargs["id"] for llamada in instancia.add_job.call_args_list}
        self.assertEqual(ids_registrados, {"sincronizar_woo"})

    def test_sin_lock_no_registra_nada(self):
        with patch("pedidos.scheduler.os.getpid", return_value=999):
            _tomar_lock()  # otro proceso ya tiene el lock, y sigue vivo
        with patch("pedidos.scheduler.BackgroundScheduler") as MockScheduler, \
             patch("pedidos.scheduler.os.getpid", return_value=111), \
             patch("pedidos.scheduler.psutil.pid_exists", return_value=True):
            iniciar_scheduler()
        MockScheduler.assert_not_called()


class RefrescarLockTest(TestCase):
    def test_refresca_tomado_en_del_dueno_actual(self):
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            _tomar_lock()
            viejo = timezone.now() - datetime.timedelta(minutes=5)
            LockTarea.objects.filter(nombre=NOMBRE_LOCK).update(tomado_en=viejo)
            _refrescar_lock()
        lock = LockTarea.objects.get(nombre=NOMBRE_LOCK)
        self.assertGreater(lock.tomado_en, viejo)

    def test_no_toca_lock_de_otro_pid(self):
        with patch("pedidos.scheduler.os.getpid", return_value=111):
            _tomar_lock()
            viejo = timezone.now() - datetime.timedelta(minutes=5)
            LockTarea.objects.filter(nombre=NOMBRE_LOCK).update(tomado_en=viejo)
        with patch("pedidos.scheduler.os.getpid", return_value=222):
            _refrescar_lock()  # este pid no es dueño, no debería actualizar nada
        lock = LockTarea.objects.get(nombre=NOMBRE_LOCK)
        self.assertEqual(lock.tomado_en, viejo)
