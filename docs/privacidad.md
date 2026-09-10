# Política de Privacidad — barrapp

Última actualización: 11 de septiembre de 2026

barrapp es una herramienta de medición: cuenta tus repeticiones a partir de un
vídeo que grabas y te devuelve números (tiempos, rangos de movimiento, número de
repeticiones). No es un entrenador, no es un médico y no es una red social.

Esta política explica qué datos tratamos, para qué, con quién se comparten y
cuánto tiempo los conservamos.

**Responsable del tratamiento:** barrapp (alektebel), España.
**Contacto:** el correo de contacto que aparece en la ficha de barrapp en Google
Play. *(Sustituye esta línea por tu dirección de contacto antes de publicar.)*

---

## 1. Qué datos tratamos

### El vídeo que eliges
El clip que seleccionas o grabas se sube a nuestro servidor en Amazon Web
Services para analizarlo. La app usa el selector y la cámara del sistema: barrapp
no pide permiso de cámara ni acceso a toda tu galería, solo recibe el clip que
tú eliges.

### Identificador de dispositivo
En el teléfono se genera un identificador aleatorio (un UUID) que se guarda solo
en tu dispositivo. Sirve para asociar tu historial a este teléfono sin
necesidad de nombre, correo ni cuenta de Google. Puedes usar barrapp de forma
totalmente anónima.

### Cuenta (opcional)
Si decides crear una cuenta, tratamos tu **correo electrónico** y tu
**contraseña**. La contraseña la gestiona Amazon Cognito y se guarda cifrada;
barrapp nunca la ve. En el teléfono solo se guardan los tokens de sesión. La
cuenta es lo que hace que tu historial sobreviva a un cambio de teléfono.

### Resultados de medición
Los números que produce el análisis (repeticiones, tiempos, rangos, avisos de
técnica) se guardan en nuestra base de datos asociados a tu identificador de
dispositivo o a tu cuenta, para que puedas consultar tu historial. Estos
resultados **no incluyen el vídeo**.

### Asistente de objetivos (opcional)
Los mensajes que escribes en el chat de objetivos se envían a nuestro servidor y
a un proveedor externo de inteligencia artificial (nan.builders, modelo
`qwen3.8-flash`) para generar tu perfil. El perfil resultante (nombre, edad,
frecuencia de entrenamiento y objetivo) se guarda en tu teléfono. Ten en cuenta
que la conversación que lo genera sí sale del dispositivo tal como se describe
aquí, así que no escribas en ese chat datos que no quieras enviar.

### Diagnóstico
Guardamos trazas técnicas de cada análisis (identificador de la ejecución,
etapas, métricas) para poder detectar y corregir errores. Estas trazas no
contienen el vídeo.

### Notificaciones
La app usa notificaciones locales (por ejemplo, tu revisión semanal). No tratan
datos personales más allá de lo necesario para mostrarlas.

## 2. Para qué usamos los datos

- Medir tus repeticiones y devolverte el informe.
- Mantener tu historial de entrenamiento y sincronizarlo con tu cuenta.
- Gestionar tu cuenta y el correo de confirmación o recuperación.
- Redactar el texto del informe y la revisión de técnica.
- Responder al asistente de objetivos.
- Garantizar la seguridad y depurar fallos del servicio.

No vendemos tus datos. No mostramos publicidad. No compartimos tu clip con otros
usuarios.

## 3. Con quién se comparten

Usamos proveedores que tratan datos por cuenta nuestra:

- **Amazon Web Services (AWS)** — alojamiento. Guarda el vídeo (S3), los
  resultados (DynamoDB), las credenciales de la cuenta (Cognito) y ejecuta el
  análisis (Lambda), en la región `eu-west-1` (Irlanda).
- **DeepSeek** (`api.deepseek.com`) — recibe el **informe numérico** (sin el
  vídeo) para redactar el texto del informe.
- **nan.builders** (`api.nan.builders`) — recibe **fotogramas fijos extraídos de
  tu clip** junto con el informe medido, para un análisis técnico de la técnica,
  y recibe la conversación del asistente de objetivos.

Estos proveedores pueden tratar datos fuera del Espacio Económico Europeo,
amparándose en sus propias garantías (decisiones de adecuación o cláusulas
contractuales tipo). No usamos tus datos para entrenar modelos.

## 4. Cuánto tiempo los conservamos

- **Vídeo:** se borra automáticamente **30 días** después de subirlo. Puedes
  borrarlo antes desde la pantalla del informe de la sesión.
- **Resultados y trazas:** mientras mantengas tu historial. Al borrar una sesión
  se elimina también su registro.
- **Cuenta:** hasta que la elimines. Puedes solicitar el borrado de tu cuenta y
  de los datos asociados escribiendo al correo de contacto.
- **Fotogramas enviados a los proveedores de IA:** no los almacenamos nosotros;
  se procesan solo para generar el informe.

## 5. Seguridad

El vídeo viaja y se guarda cifrado (HTTPS/TLS en tránsito, AES-256 en reposo en
S3), el bucket es privado y no accesible públicamente, y cada dato está ligado a
tu identificador o tu cuenta. La app tiene desactivadas las copias de seguridad
automáticas de Android.

## 6. Tus derechos

Si te encuentras en el Espacio Económico Europeo, puedes ejercer tus derechos de
acceso, rectificación, supresión, portabilidad, limitación y oposición
escribiendo al correo de contacto. También puedes reclamar ante la Agencia
Española de Protección de Datos (www.aepd.es).

## 7. Menores

barrapp no está dirigida a menores de 16 años y no recopilamos conscientemente
sus datos. Si eres madre, padre o tutor y crees que un menor nos ha enviado
datos, escríbenos para eliminarlos.

## 8. Lo que barrapp no es

Los números son mediciones, no un diagnóstico, un plan de entrenamiento ni una
afirmación de que una repetición sea "buena" o "mala". No sustituyen el consejo
de un profesional sanitario.

## 9. Cambios en esta política

Si cambiamos esta política, actualizaremos la fecha de arriba. Los cambios
importantes se anunciarán en la ficha de la app.

## 10. Contacto

Para cualquier duda sobre privacidad, usa el correo de contacto de la ficha de
barrapp en Google Play.
