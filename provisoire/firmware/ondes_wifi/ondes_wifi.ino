// CampusTwin — compter avec les ondes Wi-Fi (Seeed XIAO ESP32S3, deux cartes).
//
// Une carte (émetteur) envoie 50 petits paquets ESP-NOW par seconde. L'autre (récepteur) lit pour chaque
// paquet le CSI : comment le signal arrive sur chacune des 52 sous-porteuses du canal Wi-Fi. Quand
// quelqu'un bouge entre les deux cartes, les ondes rebondissent autrement et le CSI change.
//   - turbulence d'un paquet : écart-type des amplitudes sur les 52 sous-porteuses ;
//   - mouvement sur 10 s : écart-type de la turbulence (idée reprise du projet ESPectre).
// Toutes les 10 s, le récepteur envoie au serveur le mouvement, la turbulence moyenne, le nombre de
// paquets reçus et l'amplitude moyenne de chaque sous-porteuse. Le serveur compare au comptage de la
// porte, ce qui donne une base pour apprendre à compter avec les ondes.
//
// Pas de bibliothèque à installer. Carte : "XIAO_ESP32S3" (paquet esp32 d'Espressif, CSI activé).

#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>
#include <math.h>
#include "esp_wifi.h"
#include "esp_now.h"
#include "config.h"

const uint8_t MAC_EMETTEUR[6] = EMETTEUR_MAC;
const uint8_t DIFFUSION[6] = { 0xff, 0xff, 0xff, 0xff, 0xff, 0xff };
const int NB_SOUS_PORTEUSES = 52;               // L-LTF 20 MHz : -26..-1 et 1..26 (sans le centre ni les bords)

// Sommes de la fenêtre en cours, remplies par la fonction CSI (tâche Wi-Fi) et vidées par loop()
struct Fenetre {
  uint32_t paquets;
  double somme_t, somme_t2;                      // turbulence de chaque paquet
  double somme_rssi;
  float somme_amp[NB_SOUS_PORTEUSES];
};
Fenetre fen = {};
portMUX_TYPE verrou = portMUX_INITIALIZER_UNLOCKED;

void connecterWifi() {
  if (strlen(WIFI_NOM) == 0 || WiFi.status() == WL_CONNECTED) return;
  WiFi.begin(WIFI_NOM, WIFI_MOT_DE_PASSE);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
}

void demarrerWifi() {
  WiFi.mode(WIFI_STA);
  if (ROLE_EMETTEUR) esp_wifi_set_mac(WIFI_IF_STA, MAC_EMETTEUR);
  if (strlen(WIFI_NOM) > 0) {
    connecterWifi();                             // le canal devient celui du réseau
  } else {
    esp_wifi_set_channel(CANAL, WIFI_SECOND_CHAN_NONE);
  }
  if (esp_now_init() != ESP_OK) Serial.println("ESP-NOW ne démarre pas");
}

// =====================================================================
// Émetteur
// =====================================================================

uint32_t numero = 0;

void demarrerEmetteur() {
  esp_now_peer_info_t pair = {};
  memcpy(pair.peer_addr, DIFFUSION, 6);
  pair.channel = 0;                              // canal actuel
  pair.ifidx = WIFI_IF_STA;
  esp_now_add_peer(&pair);
  Serial.printf("Émetteur prêt, canal %d, %d paquets/s\n", WiFi.channel(), PAQUETS_PAR_SECONDE);
}

void boucleEmetteur() {
  static unsigned long prochain = 0;
  if (millis() < prochain) return;
  prochain = millis() + 1000 / PAQUETS_PAR_SECONDE;
  uint8_t paquet[8] = { 'C', 'T' };
  memcpy(paquet + 2, &numero, 4);
  numero++;
  esp_now_send(DIFFUSION, paquet, sizeof(paquet));
}

// =====================================================================
// Récepteur
// =====================================================================

// Index dans le tampon CSI (L-LTF : sous-porteuses 0..31 puis -32..-1, deux octets chacune : imaginaire, réel)
int indexSousPorteuse(int k) {                   // k = 0..51
  return k < 26 ? 1 + k : 38 + (k - 26);         // 1..26, puis 38..63 (= -26..-1)
}

void recevoirCsi(void *ctx, wifi_csi_info_t *info) {
  if (memcmp(info->mac, MAC_EMETTEUR, 6) != 0 || info->len < 128) return;
  const int8_t *b = info->buf;
  float amp[NB_SOUS_PORTEUSES];
  float moyenne = 0;
  for (int k = 0; k < NB_SOUS_PORTEUSES; k++) {
    int i = indexSousPorteuse(k);
    if (info->first_word_invalid && i < 2) { amp[k] = 0; continue; }
    float im = b[2 * i], re = b[2 * i + 1];
    amp[k] = sqrtf(re * re + im * im);
    moyenne += amp[k];
  }
  moyenne /= NB_SOUS_PORTEUSES;
  float ecart = 0;
  for (int k = 0; k < NB_SOUS_PORTEUSES; k++) ecart += (amp[k] - moyenne) * (amp[k] - moyenne);
  float turbulence = sqrtf(ecart / NB_SOUS_PORTEUSES);
  portENTER_CRITICAL(&verrou);
  fen.paquets++;
  fen.somme_t += turbulence;
  fen.somme_t2 += (double)turbulence * turbulence;
  fen.somme_rssi += info->rx_ctrl.rssi;
  for (int k = 0; k < NB_SOUS_PORTEUSES; k++) fen.somme_amp[k] += amp[k];
  portEXIT_CRITICAL(&verrou);
}

void demarrerRecepteur() {
  esp_wifi_set_promiscuous(true);
  wifi_csi_config_t csi = {};
  csi.lltf_en = true;
  csi.htltf_en = false;
  csi.stbc_htltf2_en = false;
  csi.ltf_merge_en = false;
  csi.channel_filter_en = false;                 // garder chaque sous-porteuse indépendante
  csi.manu_scale = false;
  esp_err_t e = esp_wifi_set_csi_config(&csi);
  if (e == ESP_OK) e = esp_wifi_set_csi_rx_cb(recevoirCsi, nullptr);
  if (e == ESP_OK) e = esp_wifi_set_csi(true);
  if (e != ESP_OK) Serial.printf("CSI indisponible (erreur %d)\n", e);
  configTime(0, 0, NTP_SERVEUR);
  Serial.printf("Récepteur prêt, canal %d\n", WiFi.channel());
}

void envoyer(const Fenetre &f) {
  float mouvement = 0, turbulence = 0, rssi = 0;
  if (f.paquets > 1) {
    turbulence = f.somme_t / f.paquets;
    mouvement = sqrt(fmax(0.0, f.somme_t2 / f.paquets - (double)turbulence * turbulence));
    rssi = f.somme_rssi / f.paquets;
  }
  Serial.printf("%u paquets, turbulence %.2f, mouvement %.3f, RSSI %.0f dBm\n", f.paquets, turbulence, mouvement, rssi);
  if (strlen(WIFI_NOM) == 0 || WiFi.status() != WL_CONNECTED) return;
  String json = "{\"type\":\"ondes\",\"salle\":\"" SALLE "\"";
  json += ",\"paquets\":" + String(f.paquets);
  json += ",\"mouvement\":" + String(mouvement, 4);
  json += ",\"turbulence\":" + String(turbulence, 3);
  json += ",\"rssi\":" + String(rssi, 1);
  json += ",\"amplitudes\":[";
  for (int k = 0; k < NB_SOUS_PORTEUSES; k++) {
    if (k) json += ",";
    json += String(f.paquets ? f.somme_amp[k] / f.paquets : 0, 1);
  }
  json += "]";
  if (time(nullptr) > 1700000000) json += ",\"t\":" + String((double)time(nullptr), 0);
  json += "}";
  HTTPClient http;
  http.begin(String(SERVEUR_URL) + "/api/mesure");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Cle", CLE_CAPTEURS);
  http.setTimeout(2000);
  int code = http.POST(json);
  http.end();
  if (code != 200) Serial.printf("Serveur : réponse %d\n", code);
}

void boucleRecepteur() {
  static unsigned long prochain = PERIODE_ENVOI_MS;
  if (millis() < prochain) return;
  prochain = millis() + PERIODE_ENVOI_MS;
  Fenetre copie;
  portENTER_CRITICAL(&verrou);
  copie = fen;
  fen = {};
  portEXIT_CRITICAL(&verrou);
  connecterWifi();
  envoyer(copie);
}

// =====================================================================

void setup() {
  Serial.begin(115200);
  delay(500);
  demarrerWifi();
  if (ROLE_EMETTEUR) demarrerEmetteur(); else demarrerRecepteur();
}

void loop() {
  if (ROLE_EMETTEUR) boucleEmetteur(); else boucleRecepteur();
}
