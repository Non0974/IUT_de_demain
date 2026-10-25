// CampusTwin — nœud salle (Seeed XIAO ESP32S3)
//  - SCD-41 : CO2, température, humidité (I2C, commandes du datasheet Sensirion, sans bibliothèque)
//  - PN532  : lecteur de carte étudiante NFC (I2C). On n'envoie qu'une empreinte SHA-256 du numéro de carte.
//  - écran e-paper 2,9" (optionnel) : CO2 et confirmation du badge
// Les mesures partent en HTTP vers le serveur (POST /api/mesure, JSON).
// Bibliothèques : Adafruit PN532, GxEPD2 (si écran). Carte : "XIAO_ESP32S3" (paquet esp32 d'Espressif).

#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <time.h>
#include <Adafruit_PN532.h>
#include "mbedtls/sha256.h"
#include "config.h"

#if AVEC_ECRAN
#include <GxEPD2_BW.h>
#include <Fonts/FreeSansBold18pt7b.h>
#include <Fonts/FreeSans9pt7b.h>
// Waveshare 2,9" V2 : CS D1, DC D2, RST D3, BUSY D0 ; SPI matériel (SCK D8, MOSI D10)
GxEPD2_BW<GxEPD2_290_T94_V2, GxEPD2_290_T94_V2::HEIGHT> ecran(GxEPD2_290_T94_V2(D1, D2, D3, D0));
#endif

// ---------- broches ----------
const int PN532_IRQ = D6;
const int PN532_RESET = D7;
const int LED = LED_BUILTIN;          // LED utilisateur (allumée à l'état bas)

Adafruit_PN532 nfc(PN532_IRQ, PN532_RESET, &Wire);

// ---------- file d'attente des messages (si le Wi-Fi ou le serveur ne répond pas) ----------
struct Message { String json; unsigned long cree; };
const int TAILLE_FILE = 60;
Message file_[TAILLE_FILE];
int debutFile = 0, nbFile = 0;

void mettreEnFile(const String &json) {
  if (nbFile == TAILLE_FILE) { debutFile = (debutFile + 1) % TAILLE_FILE; nbFile--; }   // on perd le plus ancien
  file_[(debutFile + nbFile) % TAILLE_FILE] = { json, millis() };
  nbFile++;
}

bool heureValide() { return time(nullptr) > 1700000000; }

// Ajoute l'heure : vraie heure si le NTP a répondu, sinon l'âge du message (le serveur recalcule l'heure)
String horodater(const Message &m) {
  String j = m.json.substring(0, m.json.length() - 1);
  if (heureValide()) {
    double t = (double)time(nullptr) - (millis() - m.cree) / 1000.0;
    j += ",\"t\":" + String(t, 1);
  } else {
    j += ",\"age_ms\":" + String(millis() - m.cree);
  }
  return j + "}";
}

void viderFile() {
  if (WiFi.status() != WL_CONNECTED) return;
  while (nbFile > 0) {
    HTTPClient http;
    http.begin(String(SERVEUR_URL) + "/api/mesure");
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Cle", CLE_CAPTEURS);
    http.setTimeout(3000);
    int code = http.POST(horodater(file_[debutFile]));
    http.end();
    if (code < 200 || code >= 500) return;     // serveur absent : on réessaiera
    debutFile = (debutFile + 1) % TAILLE_FILE;  // 4xx = message refusé, inutile de le renvoyer
    nbFile--;
  }
}

// ---------- SCD-41 ----------
const uint8_t SCD41 = 0x62;

uint8_t crc8(const uint8_t *d, int n) {
  uint8_t crc = 0xFF;
  for (int i = 0; i < n; i++) {
    crc ^= d[i];
    for (int b = 0; b < 8; b++) crc = (crc & 0x80) ? (crc << 1) ^ 0x31 : crc << 1;
  }
  return crc;
}

void scdCommande(uint16_t cmd) {
  Wire.beginTransmission(SCD41);
  Wire.write(cmd >> 8);
  Wire.write(cmd & 0xFF);
  Wire.endTransmission();
}

void scdCommandeMot(uint16_t cmd, uint16_t mot) {
  uint8_t d[2] = { (uint8_t)(mot >> 8), (uint8_t)(mot & 0xFF) };
  Wire.beginTransmission(SCD41);
  Wire.write(cmd >> 8);
  Wire.write(cmd & 0xFF);
  Wire.write(d, 2);
  Wire.write(crc8(d, 2));
  Wire.endTransmission();
}

bool scdLire(uint16_t cmd, uint16_t *mots, int n) {
  scdCommande(cmd);
  delay(2);
  if (Wire.requestFrom(SCD41, (uint8_t)(3 * n)) != 3 * n) return false;
  for (int i = 0; i < n; i++) {
    uint8_t d[2] = { (uint8_t)Wire.read(), (uint8_t)Wire.read() };
    if (Wire.read() != crc8(d, 2)) return false;
    mots[i] = (d[0] << 8) | d[1];
  }
  return true;
}

void scdDemarrer() {
  scdCommande(0x3F86);           // arrêt d'une mesure éventuelle
  delay(500);
  // Pas d'auto-calibration du capteur : c'est le serveur qui vérifie la dérive (mesure du soir),
  // sinon le capteur se recale tout seul sur 400 ppm et cache le problème (vu dans ROBOD)
  scdCommandeMot(0x2416, 0);
  delay(2);
  scdCommande(0x21B1);           // mesure périodique, une valeur toutes les 5 s
}

bool scdMesure(float &co2, float &temp, float &hum) {
  uint16_t pret;
  if (!scdLire(0xE4B8, &pret, 1) || (pret & 0x07FF) == 0) return false;
  uint16_t m[3];
  if (!scdLire(0xEC05, m, 3)) return false;
  co2 = m[0];
  temp = -45 + 175.0 * m[1] / 65535.0;
  hum = 100.0 * m[2] / 65535.0;
  return true;
}

// ---------- badge ----------

// Empreinte = SHA-256(sel + numéro de carte en hexadécimal), 16 premiers caractères : comme le serveur
String empreinte(const uint8_t *uid, uint8_t n) {
  String texte = SEL_CARTES;
  char h[3];
  for (int i = 0; i < n; i++) { sprintf(h, "%02X", uid[i]); texte += h; }
  uint8_t sortie[32];
  mbedtls_sha256((const unsigned char *)texte.c_str(), texte.length(), sortie, 0);
  String r;
  for (int i = 0; i < 8; i++) { sprintf(h, "%02x", sortie[i]); r += h; }
  return r;
}

// ---------- écran ----------
float dernierCO2 = 0;
unsigned long badgeAffiche = 0;

void afficher(const char *ligne2) {
#if AVEC_ECRAN
  ecran.setPartialWindow(0, 0, ecran.width(), ecran.height());
  ecran.firstPage();
  do {
    ecran.fillScreen(GxEPD_WHITE);
    ecran.setTextColor(GxEPD_BLACK);
    ecran.setFont(&FreeSans9pt7b);
    ecran.setCursor(6, 20);
    ecran.print(SALLE);
    ecran.setFont(&FreeSansBold18pt7b);
    ecran.setCursor(6, 62);
    ecran.print(dernierCO2 > 0 ? String((int)dernierCO2) + " ppm" : String("..."));
    ecran.setFont(&FreeSans9pt7b);
    ecran.setCursor(6, 90);
    ecran.print(dernierCO2 >= 1200 ? "Air mauvais : il faut aerer" : dernierCO2 >= 800 ? "Air moyen" : "Air bon");
    ecran.setCursor(6, 116);
    ecran.print(ligne2);
  } while (ecran.nextPage());
#endif
}

// ---------- programme ----------

void connecterWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_NOM, WIFI_MOT_DE_PASSE);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
}

void setup() {
  Serial.begin(115200);
  pinMode(LED, OUTPUT);
  digitalWrite(LED, HIGH);
  Wire.begin();
  Wire.setClock(100000);
  scdDemarrer();
  nfc.begin();
  if (!nfc.getFirmwareVersion()) Serial.println("PN532 introuvable : vérifier le câblage");
  nfc.SAMConfig();
#if AVEC_ECRAN
  ecran.init(115200, true, 2, false);
  ecran.setRotation(1);
  afficher("Badgez en entrant");
#endif
  connecterWifi();
  configTime(0, 0, NTP_SERVEUR);      // heure exacte pour horodater les mesures
}

unsigned long dernierCO2Envoi = 0;
unsigned long dernierEcran = 0;
String derniereCarte;
unsigned long derniereCarteMs = 0;

void loop() {
  connecterWifi();

  // CO2 : le capteur donne une valeur toutes les 5 s, on en envoie une toutes les PERIODE_CO2_S
  float co2, temp, hum;
  if (millis() - dernierCO2Envoi >= PERIODE_CO2_S * 1000UL && scdMesure(co2, temp, hum)) {
    dernierCO2Envoi = millis();
    dernierCO2 = co2;
    mettreEnFile("{\"type\":\"co2\",\"salle\":\"" SALLE "\",\"co2\":" + String(co2, 0) + ",\"temp\":" + String(temp, 2) + ",\"hum\":" + String(hum, 1) + "}");
  }

  // Badge : lecture rapide (50 ms) pour ne pas bloquer la boucle
  uint8_t uid[10];
  uint8_t n = 0;
  if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &n, 50)) {
    String carte = empreinte(uid, n);
    // la même carte posée longtemps ne compte qu'une fois
    if (carte != derniereCarte || millis() - derniereCarteMs > 5000) {
      mettreEnFile("{\"type\":\"badge\",\"salle\":\"" SALLE "\",\"carte\":\"" + carte + "\"}");
      digitalWrite(LED, LOW);
      afficher("Badge enregistre");
      badgeAffiche = millis();
    }
    derniereCarte = carte;
    derniereCarteMs = millis();
  }
  if (badgeAffiche && millis() - badgeAffiche > 1500) {
    digitalWrite(LED, HIGH);
    badgeAffiche = 0;
    afficher("Badgez en entrant");
  }

  // Écran : rafraîchi toutes les 2 min (l'e-paper n'aime pas être redessiné trop souvent)
  if (millis() - dernierEcran > 120000) {
    dernierEcran = millis();
    afficher("Badgez en entrant");
  }

  viderFile();
}
