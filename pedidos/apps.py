from django.apps import AppConfig
from django.conf import settings
import os, sys

class PedidosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pedidos'

    def ready(self):
        if not (settings.CRON_SAP_ACTIVO or settings.CRON_WOO_ACTIVO):
            return  # ambos apagados por .env — requiere reiniciar el proceso para tomar efecto

        ejecutando_manage_py = bool(sys.argv) and sys.argv[0].endswith("manage.py")
        if ejecutando_manage_py:
            # Bajo manage.py, SOLO runserver sirve de verdad — cualquier otro comando
            # (check, migrate, test, shell, etc.) no debe tocar la BD ni arrancar nada.
            if "runserver" not in sys.argv:
                return
            # El autoreloader de runserver carga la app 2 veces; RUN_MAIN solo está
            # seteado en el proceso real que sirve.
            if os.environ.get("RUN_MAIN") != "true":
                return
        # Si no corre bajo manage.py (gunicorn/uwsgi en producción), arranca directo.

        from .scheduler import iniciar_scheduler
        iniciar_scheduler()