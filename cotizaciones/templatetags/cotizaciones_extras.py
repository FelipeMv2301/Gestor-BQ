from django import template

register = template.Library()


@register.filter
def clp(valor):
    """Formatea un monto como pesos chilenos: 6169797 -> '$6.169.797'.
    Sin decimales (CLP no los usa). Si el valor no es numérico, lo devuelve tal cual."""
    try:
        entero = int(round(float(valor)))
    except (TypeError, ValueError):
        return valor
    # f"{n:,}" agrupa con coma (6,169,797); en Chile el separador de miles es el punto.
    return "$" + f"{entero:,}".replace(",", ".")
