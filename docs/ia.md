# Uso de inteligencia artificial

La IA apoyó implementación, documentación, diseño y depuración. Las decisiones
de producto y arquitectura, su revisión y aprobación corresponden al candidato.
Los prompts siguientes están reformulados en primera persona a partir de
indicaciones que di durante el desarrollo; no son citas textuales.

## Herramientas utilizadas

- **OpenCode** con GPT-6 Luna y GPT-6.2 Sol: análisis, implementación,
  depuración y documentación.
- **Playwright MCP**: usado para escenarios de navegador con contextos aislados y
  observar el mismo vuelo desde varios clientes.
- **Chrome DevTools MCP**: configurado en OpenCode para inspección de páginas y
  consola.
- **Context7 CLI**: consulta de documentación de Next.js y pnpm.
- `create-next-app`: scaffold inicial de Next.js.

## Prompts representativos

| Caso de uso | Prompt |
| --- | --- |
| Límites de dominio | «Definamos los módulos. La propuesta de módulos no corresponde a lo que necesito: trabajemos con Inventory, Reservations y Payments. El tablero de estadísticas debe ser una vista de consulta, no otro módulo dueño de datos.» |
| Mensajería | «La comunicación entre módulos debe pasar por un puerto/event bus; quiero poder cambiar más adelante el transporte por SQS, Kafka o RabbitMQ.» |
| Selección de asiento | «En arquitectura agrega los diagramas de flujo y explica por qué seleccionar un asiento no lo bloquea inmediatamente. Enfatiza las llamadas innecesarias, que no se informa quién lo bloqueó y que una selección exploratoria podría producir muchas solicitudes de reservar/cancelar.» |
| Vencimiento y pago | «Si una reserva vence sin confirmar, Payments debe anular una autorización pendiente o compensar el pago antes de liberar el asiento. Las reservas confirmadas no deben vencer ni liberar sus asientos.» |
| Aviso en tiempo real | «El evento del asiento llega, pero no veo la notificación. Investiga el flujo entre dos clientes y verifica que el aviso se pueda cerrar y desaparezca a los siete segundos.» |
| Estadísticas | «Completa la vista de estadísticas con ocupación en tiempo real por vuelo: disponibles, bloqueados y confirmados.» |
| Logs para debugging | «Los logs estructurados son obligatorios para observabilidad; agreguémoslos en los módulos para poder seguir los flujos y diagnosticar errores.» |

## Correcciones y criterio propio

- La IA propuso inicialmente límites distintos a los aprobados: separar Flights,
  agregar Booking como módulo y dar propiedad de datos al Dashboard. El candidato
  rechazó esa propuesta y definió Inventory, Reservations y Payments.
- Se corrigió el uso inicial de npm: el frontend usa pnpm y mantiene su lockfile
  dentro de `frontend/`.
- Se encontró que un evento recibido no garantizaba que el aviso fuera visible.
  La verificación separó recepción del frame, presentación del aviso y respaldo
  HTTP; además se probó entre clientes aislados.
- Una prueba PostgreSQL detectó que una reserva incompleta podía expirar sin
  liberar correctamente su asiento. Se conectó el adaptador ficticio de Payments
  al proceso de expiración y se verificó que el worker no libere reservas
  confirmadas.
- Algunas propuestas de arquitectura y documentación describieron mecanismos
  como operativos antes de estar implementados. Se revisaron contra el código y
  se separó explícitamente el estado real de lo pendiente.

## Impacto estimado

**Estimación orientativa: unas 2 horas netas de ahorro**, tomando como
referencia una jornada de 8 horas para la prueba. No es una medición: no se
cronometraron las tareas ni hubo una ejecución comparable sin IA. La cifra
considera el tiempo que también exigieron la revisión y las correcciones.

El mayor aporte estuvo en la implementación y la documentación, con apoyo
adicional para comparar alternativas, preparar pruebas y depurar el flujo.
