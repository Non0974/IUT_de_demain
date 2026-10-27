// CampusTwin — lecteur de badge seul (Seeed XIAO ESP32S3), pour équiper une salle sans le nœud complet.
//  - PN532 : lecteur de carte étudiante NFC (I2C). On n'envoie qu'une empreinte SHA-256 du numéro de carte.
//  - deux LED (verte, rouge) et un buzzer actif : l'étudiant voit tout de suite si son badge est pris.
//      vert + 1 bip        carte connue, badge enregistré
//      orange + 2 bips     carte inconnue : à enregistrer dans la page « Cartes » du site
//      rouge clignotant    serveur injoignable : le badge est gardé et renvoyé plus tard
// Le badge part tout de suite en HTTP (POST /api/mesure) et la réponse du serveur dit si la carte est connue.
// Bibliothèque : Adafruit PN532. Carte : "XIAO_ESP32S3" (paquet esp32 d'Espressif).

#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <time.h>
#include <Adafruit_PN532.h>
#include "mbedtls/sha256.h"
#include "config.h"

// ---------- broches ----------
const int PN532_IRQ = D6;
const int PN532_RESET = D7;

Adafruit_PN532 nfc(PN532_IRQ, PN532_RESET, &Wire);

// ---------- voyants ----------
void voyant(bool vert, bool rouge) {
  digitalWrite(LED_VERTE, vert ? HIGH : LOW);
  digitalWrite(LED_ROUGE, rouge ? HIGH : LOW);
}

void bip(int n, int duree_ms) {
  for (int i = 0; i < n; i++) {
    digitalWrite(BUZZER, HIGH);
    delay(duree_ms);
    digitalWrite(BUZZER, LOW);
    if (i < n - 1) delay(90);
  }
}

// ---------- badges en attente (serveur injoignable) ----------
struct Badge { String carte; unsigned long cree; };
const int TAILLE_FILE = 40;
Badge file_[TAILLE_FILE];
int debutFile = 0, nbFile = 0;

void mettreEnFile(const String &carte) {
  if (nbFile == TAILLE_FILE) { debutFile = (debutFile + 1) % TAILLE_FILE; nbFile--; }   // on perd le plus ancien
  file_[(debutFile + nbFile) % TAILLE_FILE] = { carte, millis() };
  nbFile++;
}

bool heureValide() { return time(nullptr) > 1700000000; }

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

// Envoie un badge. Renvoie 1 si la carte est connue, 0 si inconnue, -1 si le serveur ne répond pas.
int envoyer(const String &carte, unsigned long cree) {
  if (WiFi.status() != WL_CONNECTED) return -1;
  String json = "{\"type\":\"badge\",\"salle\":\"" SALLE "\",\"carte\":\"" + carte + "\"";
  if (heureValide()) {
    json += ",\"t\":" + String((double)time(nullptr) - (millis() - cree) / 1000.0, 1);
  } else {
    json += ",\"age_ms\":" + String(millis() - cree);     // le serveur recalcule l'heure
  }
  json += "}";
  HTTPClient http;
  http.begin(String(SERVEUR_URL) + "/api/mesure");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Cle", CLE_CAPTEURS);
  http.setTimeout(2000);
  int code = http.POST(json);
  String reponse = code > 0 ? http.getString() : "";
  http.end();
  if (code < 200 || code >= 500) return -1;
  return reponse.indexOf("\"connue\": true") >= 0 || reponse.indexOf("\"connue\":true") >= 0 ? 1 : 0;
}

void renvoyerFile() {
  while (nbFile > 0) {
    if (envoyer(file_[debutFile].carte, file_[debutFile].cree) < 0) return;    // toujours injoignable
    debutFile = (debutFile + 1) % TAILLE_FILE;
    nbFile--;
  }
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
  pinMode(LED_VERTE, OUTPUT);
  pinMode(LED_ROUGE, OUTPUT);
  pinMode(BUZZER, OUTPUT);
  voyant(false, false);
  Wire.begin();
  Wire.setClock(100000);
  nfc.begin();
  if (!nfc.getFirmwareVersion()) {
    Serial.println("PN532 introuvable : vérifier le câblage et les interrupteurs (mode I2C)");
    voyant(false, true);
  }
  nfc.SAMConfig();
  connecterWifi();
  configTime(0, 0, NTP_SERVEUR);      // heure exacte pour horodater les badges
  bip(1, 60);                         // prêt
}

String derniereCarte;
unsigned long derniereCarteMs = 0;
unsigned long dernierRenvoi = 0;

void loop() {
  connecterWifi();

  uint8_t uid[10];
  uint8_t n = 0;
  if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &n, 100)) {
    String carte = empreinte(uid, n);
    // la même carte posée longtemps ne compte qu'une fois
    if (carte != derniereCarte || millis() - derniereCarteMs > 5000) {
      int connue = envoyer(carte, millis());
      if (connue == 1) {
        voyant(true, false);
        bip(1, 80);
        delay(900);
      } else if (connue == 0) {
        voyant(true, true);           // orange
        bip(2, 80);
        delay(1400);
      } else {
        mettreEnFile(carte);
        for (int i = 0; i < 3; i++) { voyant(false, true); bip(1, 40); delay(160); voyant(false, false); delay(160); }
      }
      voyant(false, false);
    }
    derniereCarte = carte;
    derniereCarteMs = millis();
  }

  // Badges en attente : on réessaie toutes les 10 s
  if (nbFile > 0 && millis() - dernierRenvoi > 10000) {
    dernierRenvoi = millis();
    renvoyerFile();
  }
}
