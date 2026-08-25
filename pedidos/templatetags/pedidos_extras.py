from django import template
from .. import permisos

register = template.Library()


@register.simple_tag
def puede_editar_courier(usuario, pedido):
    return permisos.puede_editar_courier(usuario, pedido)

@register.simple_tag
def puede_editar_pedido(usuario, pedido):
    return permisos.puede_editar(usuario, pedido)

@register.simple_tag
def puede_duplicar_pedido(usuario, pedido):
    return permisos.puede_duplicar_pedido(usuario, pedido)


