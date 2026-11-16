#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "secrets.h"
#include "pronostico.h"
#include "test_vectors.h"

// El servicio de inventario publica aquí el historial de cada producto (con retain).
const char* TEMA_HISTORIAL = "inventario/+/historial";
const char* DIAS[7] = {"lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"};

WiFiClient clienteRed;
PubSubClient mqtt(clienteRed);

void conectarWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Conectando a WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nWiFi conectado. IP del ESP32: %s\n", WiFi.localIP().toString().c_str());
}

void conectarMQTT() {
  while (!mqtt.connected()) {
    Serial.print("Conectando a MQTT... ");
    if (mqtt.connect("esp32-inventario", MQTT_USER, MQTT_PASS)) {
      Serial.println("conectado");
      mqtt.subscribe(TEMA_HISTORIAL);  // al suscribirse llegan los historiales retenidos de todos los productos
    } else {
      Serial.printf("falló (código %d), reintento en 5 s\n", mqtt.state());
      delay(5000);
    }
  }
}

// Llega inventario/<producto>/historial → pronóstico → se publica en inventario/<producto>/pronostico
void alRecibirHistorial(char* tema, byte* datos, unsigned int largo) {
  // 1. Nombre del producto: lo que hay entre "inventario/" y "/historial"
  char producto[32];
  const char* inicio = tema + strlen("inventario/");
  const char* fin = strchr(inicio, '/');
  int n = fin ? fin - inicio : 0;
  if (n <= 0 || n >= (int)sizeof(producto)) return;
  memcpy(producto, inicio, n);
  producto[n] = '\0';

  // 2. JSON → Historial (se valida: viene de la red)
  JsonDocument doc;
  if (deserializeJson(doc, datos, largo)) {
    Serial.printf("%s: el historial no es un JSON válido\n", producto);
    return;
  }
  JsonArray reciente = doc["reciente"];
  JsonArray anio = doc["anio"];
  if (reciente.size() != 28 || anio.size() != 7) {
    Serial.printf("%s: el historial debe traer 28 días recientes y 7 del año anterior\n", producto);
    return;
  }
  Historial h;
  for (int i = 0; i < 28; i++) h.reciente[i] = reciente[i].as<float>();  // as<float>() acepta enteros y decimales
  for (int i = 0; i < 7; i++) h.anio[i] = anio[i].as<float>();
  h.base_anio = doc["base_anio"].as<float>();
  h.dia = doc["dia"] | -1;
  String corte = doc["corte"] | "";  // se copia antes de publicar: publish() reutiliza el búfer de entrada

  // 3. La red
  float salida[7];
  unsigned long t0 = micros();
  if (!pronosticar(h, salida)) {
    Serial.printf("%s: no se pudo pronosticar (modelo sin cargar o día fuera de 0-6)\n", producto);
    return;
  }
  unsigned long microsegundos = micros() - t0;

  // 4. Mensaje: total y un atributo por día de la semana, en unidades enteras
  int unidades[7], total = 0;
  for (int i = 0; i < 7; i++) {
    unidades[i] = max(0L, lroundf(salida[i]));
    total += unidades[i];
  }
  char mensaje[384];
  int pos = snprintf(mensaje, sizeof(mensaje), "{\"total_7d\": %d, \"inicio\": \"%s\"", total, DIAS[h.dia]);
  for (int i = 0; i < 7; i++) {
    pos += snprintf(mensaje + pos, sizeof(mensaje) - pos, ", \"%s\": %d", DIAS[(h.dia + i) % 7], unidades[i]);
  }
  snprintf(mensaje + pos, sizeof(mensaje) - pos, ", \"corte\": \"%s\", \"origen\": \"esp32\", \"microsegundos\": %lu}",
           corte.c_str(), microsegundos);

  char temaSalida[64];
  snprintf(temaSalida, sizeof(temaSalida), "inventario/%s/pronostico", producto);
  bool enviado = mqtt.publish(temaSalida, mensaje, true);
  Serial.printf("%s: %d unidades en 7 días (%lu us) → %s\n", producto, total, microsegundos, enviado ? "publicado" : "NO publicado");
}

void autoprueba() {
  Serial.println("\n=== Autoprueba: ESP32 frente a Python ===");
  int correctos = 0;
  for (int v = 0; v < N_VECTORES; v++) {
    float salida[7];
    if (!pronosticar(VECTORES[v].historial, salida)) {
      Serial.printf("%s: ERROR al pronosticar\n", VECTORES[v].nombre);
      continue;
    }
    float totalEsp = 0, totalPy = 0, difMax = 0;
    for (int d = 0; d < 7; d++) {
      totalEsp += salida[d];
      totalPy += VECTORES[v].esperado[d];
      difMax = fmaxf(difMax, fabsf(salida[d] - VECTORES[v].esperado[d]));
    }
    bool coincide = difMax <= 0.01f * totalPy / 7;  // tolerancia: 1 % del promedio diario
    if (coincide) correctos++;
    Serial.printf("%-26s total ESP32 %6.1f | Python %6.1f | dif. max. %.3f  %s\n",
                  VECTORES[v].nombre, totalEsp, totalPy, difMax, coincide ? "OK" : "DISTINTO");
  }
  Serial.printf("Coinciden %d de %d vectores\n", correctos, N_VECTORES);

  // Tiempo promedio de un pronóstico (100 repeticiones)
  float salida[7];
  unsigned long inicio = micros();
  for (int i = 0; i < 100; i++) pronosticar(VECTORES[0].historial, salida);
  Serial.printf("Tiempo por pronóstico: %lu microsegundos\n\n", (micros() - inicio) / 100);
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  if (iniciarModelo()) {
    autoprueba();
  }
  conectarWiFi();
  mqtt.setServer(MQTT_HOST, 1883);
  mqtt.setBufferSize(1024);  // el historial (36 números en JSON) supera los 256 bytes por defecto
  mqtt.setCallback(alRecibirHistorial);
}

void loop() {
  if (!mqtt.connected()) {
    conectarMQTT();
  }
  mqtt.loop();
}
