// RANU table sensor node — ESP32 + PIR (HC-SR501) or IR break-beam / FSR pressure pad.
// Low-cost option (~₹600 per table). Sends HTTPS events straight to the server.
// For offline resilience prefer the Raspberry Pi gateway (it queues events).
//
// Wiring: sensor OUT -> GPIO 27, VCC 5V, GND.  Optional start button -> GPIO 14 (to GND).
#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>

const char* WIFI_SSID = "RANU-CLUB";
const char* WIFI_PASS = "********";
const char* SERVER    = "https://club.ranusnookers.in";
const char* DEVICE_ID = "TABLE4_SENSOR";
const char* API_KEY   = "rdk_PASTE_KEY";   // from Admin > Devices > Register

const int SENSOR_PIN = 27;
const int BUTTON_PIN = 14;
const unsigned long DEBOUNCE_MS = 10000;   // max one ACTIVITY event per 10 s
unsigned long lastActivity = 0, lastHeartbeat = 0;
uint32_t counter = 0;

String isoNow() {
  time_t now; time(&now); struct tm t; gmtime_r(&now, &t);
  char buf[32]; strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &t); return String(buf);
}

bool postJson(const char* path, const String& body) {
  if (WiFi.status() != WL_CONNECTED) return false;
  HTTPClient http;
  http.begin(String(SERVER) + path);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Id", DEVICE_ID);
  http.addHeader("X-Device-Key", API_KEY);
  int code = http.POST(body);
  http.end();
  return code >= 200 && code < 300;
}

void sendEvent(const char* ev) {
  // event_id = device + boot-unique counter + time => server de-duplicates retries
  String id = String(DEVICE_ID) + "-" + String((uint32_t)ESP.getEfuseMac(), HEX) + "-" + String(millis()) + "-" + String(counter++);
  String body = "{\"event_id\":\"" + id + "\",\"event\":\"" + ev + "\",\"timestamp\":\"" + isoNow() + "\"}";
  for (int i = 0; i < 3 && !postJson("/api/v1/devices/ingest/events", body); i++) delay(1000 * (i + 1));
}

void setup() {
  pinMode(SENSOR_PIN, INPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(500);
  configTime(0, 0, "pool.ntp.org");   // accurate clock: server rejects stale / future events
}

void loop() {
  unsigned long now = millis();
  if (digitalRead(SENSOR_PIN) == HIGH && now - lastActivity > DEBOUNCE_MS) { lastActivity = now; sendEvent("ACTIVITY_DETECTED"); }
  if (digitalRead(BUTTON_PIN) == LOW) { sendEvent("START_REQUEST"); delay(1500); }
  if (now - lastHeartbeat > 30000) {
    lastHeartbeat = now;
    postJson("/api/v1/devices/ingest/heartbeat", "{\"firmware_version\":\"esp32-1.0\",\"uptime_seconds\":" + String(now / 1000) + "}");
  }
  delay(100);
}
