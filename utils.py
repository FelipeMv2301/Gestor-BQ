import unicodedata

#Valida la aplicación del dígito verificador
def validar_rut(rut):
    cuerpo, guion, dv = rut.partition("-")
    if not guion:
        return False

    suma = 0
    multiplicador = 2
    for digito in reversed(cuerpo):
        if not digito.isdigit():
            return False
        suma += int(digito) * multiplicador
        multiplicador = multiplicador + 1 if multiplicador < 7 else 2

    resto = 11 - (suma % 11)
    if resto == 11:
        dv_esperado = "0"
    elif resto == 10:
        dv_esperado = "K"
    else:
        dv_esperado = str(resto)

    return dv.upper() == dv_esperado

#Normaliza palabras con simbolos y tildes
def quitar_tildes(texto):
    return "".join(
        caracter for caracter in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caracter)
    )