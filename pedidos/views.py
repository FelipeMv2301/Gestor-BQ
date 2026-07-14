from django.shortcuts import render
from django.forms.models import model_to_dict
from pedidosRechazados.models import PedidoRechazado

# Create your views here.

#Arma un Snapshot del pedido rechazado
def rechazar_pedido(pedido, motivo, usuario):
    snapshot = model_to_dict(pedido)  # copia todos los campos del Pedido a un dict
    PedidoRechazado.objects.create(
        num_pedido=pedido.num_pedido,
        snapshot=snapshot,
        motivo=motivo,
        rechazado_por=usuario,
    )
    pedido.delete()