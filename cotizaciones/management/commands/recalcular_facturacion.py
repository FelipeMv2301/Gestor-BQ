from django.core.management.base import BaseCommand
from cotizaciones.models import Cotizacion
from cotizaciones.services import actualizar_facturacion


class Command(BaseCommand):
    help = "Backfill: recalcula total_facturado + estado de TODAS las cotizaciones (o las no anuladas)."

    def add_arguments(self, parser):
        parser.add_argument("--todas", action="store_true",
                            help="Incluye también las ANULADO (por defecto se saltan, no cambian).")

    def handle(self, *args, **options):
        qs = Cotizacion.objects.all()
        if not options["todas"]:
            qs = qs.exclude(estado=Cotizacion.Estado.ANULADO)
        n = actualizar_facturacion(qs)
        self.stdout.write(f"Facturación recalculada en {n} cotizaciones.")
