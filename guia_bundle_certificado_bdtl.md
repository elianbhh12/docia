# Guía: resolver `self-signed certificate in certificate chain` en `insert_bdtl_lambda`

## 1. Situación actual

Lo que muestra CloudWatch:

```
CERT=/opt/lambda_layer_bancolombia_certs.crt
EXISTS=True
...
CERTIFICATE_VERIFY_FAILED ... self-signed certificate in certificate chain
```

- ✅ La layer está asociada y el archivo existe en la ruta correcta. **La configuración está bien.**
- ❌ El servidor BDTL (`opv-apis-dev.apps.ambientesbc.lab`) presenta una cadena de certificados que termina en una **CA raíz que no está en el archivo** de confianza.

**Objetivo:** armar un solo archivo PEM (bundle) que contenga la CA raíz (y los intermedios) que firman el certificado del servidor BDTL, publicarlo en la layer y apuntar `BDTL_CERT_PATH` a él.

> Todos los comandos se ejecutan en **Git Bash** (Windows). `openssl` viene incluido con Git for Windows.

---

## 2. Qué es un bundle PEM

Un archivo PEM puede contener **varios certificados uno debajo del otro**:

```
-----BEGIN CERTIFICATE-----
MIIF... (certificado 1)
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIE... (certificado 2)
-----END CERTIFICATE-----
```

`requests` lee todos los certificados del archivo y confía en cualquiera de ellos. Por eso se juntan los necesarios en un solo archivo.

---

## 3. Paso a paso

### Paso 1 — Identificar el formato de cada certificado

Abrir cada archivo con el Bloc de notas:

| Si se ve... | Formato | Acción |
|---|---|---|
| `-----BEGIN CERTIFICATE-----` | PEM | Ninguna, ya sirve |
| Símbolos ilegibles | DER (binario) | Convertir (Paso 2) |
| `-----BEGIN PKCS7-----` o extensión `.p7b` | PKCS#7 (puede traer varios certificados) | Extraer (Paso 2) |
| Extensión `.pfx` / `.p12` | Contiene llave privada | **No usar.** Pedir el certificado público |

### Paso 2 — Convertir a PEM los que no lo estén

**DER → PEM:**
```bash
openssl x509 -inform der -in certificado1.cer -out certificado1.pem
```

**PKCS#7 (.p7b) → PEM** (extrae todos los certificados que contenga):
```bash
openssl pkcs7 -print_certs -in archivo.p7b -out archivo.pem
# si da error, el .p7b es binario:
openssl pkcs7 -inform der -print_certs -in archivo.p7b -out archivo.pem
```

### Paso 3 — Identificar qué es cada certificado

Ejecutar para cada archivo:
```bash
openssl x509 -in certificado1.pem -noout -subject -issuer -enddate
```

| Resultado | Qué es | ¿Incluir? |
|---|---|---|
| `subject` = `issuer` | **CA raíz** | ✅ Obligatorio (es la que falta) |
| `subject` ≠ `issuer` y el subject es una CA | **Intermedio** | ✅ Recomendado |
| `subject` contiene `opv-apis-dev...` | Certificado del **servidor** | Opcional (no hace falta, no estorba) |
| `enddate` ya pasó | **Vencido** | ❌ No sirve; pedir uno vigente |

### Paso 4 — Ver qué cadena presenta el servidor

```bash
openssl s_client -connect opv-apis-dev.apps.ambientesbc.lab:443 -showcerts </dev/null
```

Al inicio de la salida aparece la cadena:
```
 0 s:CN = opv-apis-dev...      i:CN = <Intermedia>
 1 s:CN = <Intermedia>         i:CN = <Raíz>
```

- Anotar el nombre de la **raíz** (el último `i:`).
- Confirmar que esa raíz está entre los certificados del Paso 3.

> ⚠️ Si la raíz que aparece es la del **proxy corporativo** (p. ej. Zscaler u otro proxy), se está viendo el certificado del proxy y no el real. En ese caso, pedir la cadena oficial al equipo dueño del API BDTL.

### Paso 5 — Unir los certificados en un solo archivo

Solo los certificados nuevos:
```bash
cat certificado1.pem certificado2.pem certificado3.pem certificado4.pem > bdtl_bundle.pem
```

Conservando también el archivo corporativo actual de la layer (recomendado si otros llamados dependen de él):
```bash
cat lambda_layer_bancolombia_certs.crt certificado1.pem certificado2.pem certificado3.pem certificado4.pem > bdtl_bundle.pem
```

**Revisión obligatoria:** abrir `bdtl_bundle.pem` y confirmar que cada `-----END CERTIFICATE-----` queda en **su propia línea**, antes del siguiente `-----BEGIN CERTIFICATE-----`. Si quedan pegados en la misma línea, el archivo falla; corregir con un Enter entre ellos.

> ⚠️ No unir los archivos con PowerShell sin `-Encoding ascii`: puede guardarlos en UTF-16 y `requests` no los lee.

### Paso 6 — Probar el bundle antes de subirlo a AWS

```bash
openssl s_client -connect opv-apis-dev.apps.ambientesbc.lab:443 -CAfile bdtl_bundle.pem </dev/null
```

| Resultado al final | Significado |
|---|---|
| `Verify return code: 0 (ok)` | ✅ El bundle funciona |
| `Verify return code: 19 (self-signed certificate in certificate chain)` | ❌ Sigue faltando la raíz correcta |
| `Verify return code: 20 (unable to get local issuer certificate)` | ❌ Falta un intermedio o la raíz |
| `Verify return code: 10 (certificate has expired)` | ❌ Algún certificado de la cadena está vencido |

No pasar al Paso 7 hasta obtener `0 (ok)`.

### Paso 7 — Publicar el bundle en la layer

1. Crear el zip con el archivo en la raíz del zip → quedará en `/opt/bdtl_bundle.pem`.
2. Subir el zip a S3.
3. Publicar una **nueva versión** de la layer desde S3 (consola: Lambda → Layers → Create version → Upload a file from Amazon S3).
4. Actualizar la versión de la layer en el template de la función.
5. Actualizar la variable de entorno en el template:
   ```
   BDTL_CERT_PATH=/opt/bdtl_bundle.pem
   ```
6. Desplegar por el pipeline.

### Paso 8 — Validar en AWS

Ejecutar la Lambda y revisar CloudWatch:
- ✅ La llamada al API BDTL responde → resuelto.
- ❌ Sigue `self-signed certificate in certificate chain` → confirmar con un `print` justo antes del `.post(...)` en `call_api` que `BDTL_CERT_PATH` vale `/opt/bdtl_bundle.pem`, y que la Lambda tomó la nueva versión de la layer.

---

## 4. Diagnóstico adicional desde la Lambda (opcional)

Para ver qué CAs contiene el archivo que realmente carga la Lambda, agregar temporalmente al inicio de `lambda_handler` y quitar después:

```python
import ssl
_ctx = ssl.create_default_context(cafile="/opt/bdtl_bundle.pem")
print("STATS:", _ctx.cert_store_stats())
for _c in _ctx.get_ca_certs():
    print("CA:", _c.get("subject"), "| emisor:", _c.get("issuer"), "| vence:", _c.get("notAfter"))
```

- Lista las CAs cargadas con su vencimiento.
- Si `x509_ca` sale en `0`, el archivo no contiene ninguna CA.

---

## 5. Buenas prácticas

1. **Pedir la CA oficial.** Solicitar al equipo dueño del API BDTL o al dueño de la layer corporativa: *"el certificado de la CA raíz y los intermedios que firman `opv-apis-dev.apps.ambientesbc.lab`, en formato PEM"*. No usar certificados sacados del navegador para uso definitivo.
2. **Preferir actualizar la layer corporativa.** Si el dueño de `lambda_layer_bancolombia_certs.crt` agrega la CA del lab y publica nueva versión, todos los equipos se benefician y hay un solo punto de mantenimiento. Crear un bundle propio solo si eso no es posible.
3. **Certificado por ambiente.** Configurar `BDTL_CERT_PATH` y la versión de layer por ambiente (dev, QA, prod) en el template. La CA del lab no debería ir en prod.
4. **Nunca `verify=False`** en AWS, ni siquiera temporalmente.
5. **Controlar vencimientos.** Registrar el `enddate` de cada certificado del bundle y planear la renovación.
6. **No incluir llaves privadas** en la layer. Para validar al servidor solo se necesitan certificados públicos.

---

## 6. Nota sobre los reintentos en los logs

Los mismos `RequestId` aparecen varias veces con minutos de diferencia: es la Lambda **reintentando automáticamente** el mismo evento tras fallar. Mientras el certificado no se corrija, cada archivo se procesa y falla varias veces. Se resuelve solo al corregir el certificado.

---

## 7. Checklist

- [ ] Identificar formato de los 4 certificados (Paso 1)
- [ ] Convertir a PEM los que no lo estén (Paso 2)
- [ ] Identificar raíz, intermedios y servidor (Paso 3)
- [ ] Confirmar la raíz que presenta el servidor (Paso 4)
- [ ] Crear `bdtl_bundle.pem` y revisar saltos de línea (Paso 5)
- [ ] Obtener `Verify return code: 0 (ok)` (Paso 6)
- [ ] Publicar nueva versión de la layer y actualizar template (Paso 7)
- [ ] Validar en CloudWatch (Paso 8)
